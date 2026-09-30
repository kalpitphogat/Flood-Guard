# Handoff — round 3 (2026-09-30, compute laptop + server)

Round 3 made the dashboard answer instantly from **precomputed preset runs**,
added a labelled **quick-estimate** mode for everything else, fixed **four
solver/pipeline bugs that the first real-terrain runs exposed**, and ported the
§5.1 features from the other codebase. Round 2's handoff follows below,
unchanged, for reference.

**Read R3.3 before quoting any number from a run made before 2026-09-30 06:00 UTC** —
every such run was affected by at least one of the bugs fixed there.

## R3.1 Machines and measured timings

| | Compute laptop | Server (user7@172.16.121.24) |
|---|---|---|
| CPU | Intel i7-13650HX, 14 cores / 20 threads | Intel i9-12900K, 16 cores / 24 threads |
| RAM | 15.7 GB | 62 GB |
| OS / Python | Windows 11, CPython 3.12.5 in `.venv` (NOT the MSYS2 python on PATH) | RHEL, conda env `floodguard`, Python 3.12 |
| Node | 24.12 | — |

Preset batch, final runs (fixed solver), `floodguard precompute`, **measured
wall time per run** (also in `data/library/index.json`):

| Preset (120 m, `swe_fv`) | Simulated | Machine | Wall time |
|---|---|---|---|
| Tehri, complete break, FRL 830.00 m | 6 h | laptop | 178.5 s |
| Tehri, complete break, mid 785.00 m | 6 h | laptop | 160.8 s |
| Tehri, complete break, MDDL 740.00 m | 6 h | laptop | 139.2 s |
| Hirakud, complete break, FRL 192.02 m | 24 h | server | 428.4 s |
| Hirakud, complete break, mid 185.93 m | 24 h | server | 344.8 s |
| Hirakud, complete break, MDDL 179.83 m | 24 h | server | 279.6 s |

Input acquisition is not in those times (Tehri: 6 min 28 s on the laptop,
mostly the 466 MB WorldPop India file, whose first download broke at 291 MB and
had to be retried). Preprocessing is ~1 s at 120 m, so the §4.4 preprocess
cache was **not built** — it would save nothing measurable.

## R3.2 What is new

| Area | Files |
|---|---|
| Preset library + `floodguard precompute` (resumable, `--dry-run/--limit/--force/--type`, `--force` moves the old run to `runs/.superseded/`) | `backend/floodguard/library.py`, `cli.py::cmd_precompute`, `Makefile` target `precompute` |
| Preset API: `GET /api/presets`; `POST /api/simulate` with `preset_key` (instant, never falls back) or `quick: true` (200 m, 1 h, `swe_fv`); `run_mode` in result.json, summary, runs list | `app/api/presets.py`, `app/api/simulate.py`, `app/core/jobs.py`, `app/schemas/models.py`, `floodguard/pipeline.py` (`run_meta`) |
| Frontend: "Preset — instant" / "Custom — quick estimate" switch, preset dropdowns with unavailable combinations disabled and explained, result badge, instant load of precomputed runs | `components/PresetPicker.tsx`, `InputPanel.tsx`, `RunModeBadge.tsx`, `pages/Simulation.tsx`, `api/hooks.ts`, `types/api.ts` |
| Per-resolution processed data `data/processed/<id>/r<res>/` with fallback to the old flat folder when its DEM matches | `backend/floodguard/processed.py`; `data/acquire.py`, `floodguard/pipeline.py`, `preprocess/pipeline.py`, `cli.py`, `app/api/results.py`, `app/api/catalog.py` |
| Data packs `.fgpack`: checksummed, all-or-nothing import, zip-slip safe, never overwrites different content, merges the preset index, preserves file times | `backend/floodguard/packs.py`, `cli.py::cmd_pack` |
| Loss of life, **Graham (1999) USBR DSO-99-06 Table 7**, transcribed from the report (p.38) and tested; per-cell severity (10 ft rule) × warning category; range always shown; officials-only section in the bulletin, never in SMS/CAP; PDF §5.2 | `floodguard/impact/life_loss.py`, `cli.py::cmd_life_loss`, `app/api/results.py` (`/life-loss`), `app/api/warning.py`, `report.py`, `components/LifeLossPanel.tsx` |
| Time-animated KMZ of the instantaneous wet extent per frame (advancing AND receding), generated on first request | `postprocess/exports.py::write_wave_animation_kmz`, export `wave_kmz` |
| Thacker (1981) parabolic bowl + Nash-Sutcliffe efficiency in `floodguard validate` | `floodguard/validation/thacker.py` |
| Playback speed 0.5×/1×/2×/4× | `components/PlaybackSpeed.tsx` |
| GitHub Actions CI (pytest; tsc, Vitest, build) | `.github/workflows/ci.yml` — **never executed** (needs a push) |
| River blockage (partial §5.2.7): `landslide_dam_breach` now requires `dam_type: natural_blockage` and user-supplied breach width/formation time; routed peak cross-checked against **Costa (1985) USGS OFR 85-560** landslide-dam regression (eqs. 20-22, Table 7, verified from the report) | `floodguard/breach/natural_dam.py`, `breach/parameters.py`, `floodguard/pipeline.py::_natural_dam_check`, example `data/scenarios/examples/hypothetical_blockage_bhagirathi.yaml` |
| Dataset catalogue with licences (`GET /api/datasets`, About page) | `app/api/datasets.py`, `pages/About.tsx` |
| Doc citation checker | `scripts/check_citations.py` |

## R3.3 Bugs found by the first real runs, and fixed

The Tehri presets first came out with 339 m of water at Devprayag and a *mid*
level peak 2.6× the FRL peak. Four independent defects, each fixed, each with a
regression test:

1. **Level-pool routing created water** (`breach/routing.py`). Storage was
   clamped at zero but the full outflow was still counted; when the
   elevation-storage curve stops above the breach invert, the weir kept
   discharging from an empty pool. Measured: 31,478 MCM released from a
   3,540 MCM reservoir. Now a step can release at most what is stored.
   Test: `test_routing_never_releases_more_than_the_reservoir_holds`.
2. **Reservoir curve built at the starting level instead of FRL**
   (`preprocess/pipeline.py`). `reservoir.build()`'s parameter is `frl_m` but
   received `initial_level_m`; a DSM that sees the lake surface then finds no
   pool below it (0.01 km² "reservoir" at MDDL), and the published
   `area_at_frl_km2` was applied at the wrong level. Now always built to FRL.
   Tehri also gained `area_at_frl_km2: 52.0` (CWC NRLD-2019, Uttarakhand p.263,
   PIC UA34VH0012, from `data/catalog/dams.geojson`) → reconstructed storage
   3,526 MCM vs NRLD 3,540 (−0.4%).
3. **Breach inflow added for time that never elapsed** (`engines/swe_fv.py`).
   The source used the CFL dt, then `_step` could shorten dt to its positivity
   limit: 3.87e9 m³ injected from a 3.53e9 m³ hydrograph. Now added after the
   step with the dt actually taken. Test:
   `test_engine_injects_exactly_the_hydrograph_volume_on_a_steep_bed`.
4. **Positivity clipping created water** (`engines/_swe_kernels.py`). Setting
   negative depths to zero added 7–29% to Tehri's flood volume (measured
   through new counters `volume_created_by_positivity_m3`). Fixed with an
   **outflow limiter** (per-cell drain factor on outgoing fluxes, Bollermann
   et al. 2013), plus the SSP-RK2 intermediate is no longer clipped before
   averaging. Tehri now closes to 0.03% with **0 m³ created**; all 8 FV
   verification checks unchanged. Tests: `tests/test_swe_mass.py`.

Also fixed: a misleading "reservoir not finished draining" warning after the
pool is exhausted; a solver mass check that only warned above 50% and could not
tell a gain from boundary outflow (now any gain > 1% is a NUMERICAL MASS GAIN
warning); the breach "spread" warning firing when every model is inapplicable
(reported a factor of 151,100,000); "0 m crest length" in a message.

Runs made before the fixes are in `data/quarantine/` and `data/runs/.superseded/`
(evidence only — never serve them).

## R3.4 Tests and verification (measured on the laptop, final code)

| Suite | Result |
|---|---|
| Backend `pytest backend/tests` | **265 passed, 1 failed** — the failure is `test_sph_swe.py::test_depth_is_the_kernel_sum_and_recovers_a_uniform_layer` (3.0154 vs 3.0, rtol 0.5%); pre-existing, no SPH file was touched this round |
| Frontend `npm test` | **25 passed** (8 files); `tsc --noEmit` clean; `npm run build` clean (chunk-size notice only) |
| `floodguard validate` | **12/13**: FloodGuard-SWE 8/8 (Ritter L2 0.305%, Stoker L2 0.725%, lake at rest 3.92e-12, Thacker period error 0.01%, NSE 0.999997), FloodGuard-SPH 4/5 (Ritter h(dam) 10.03% > 5% — the same pre-existing SPH regression) |

The SPH regression most likely comes from round 2's last SPH-settings patch,
which HANDOFF round 2 says was never re-run. SPH is not used by any preset.

## R3.5 The data pack for the demo laptop

`data/library/floodguard_demo_presets_120m.fgpack` — 63.8 MB, 128 files: the six
`lib_*` runs, their index entries, cached Graham estimates (warning −60/0/+60 min)
and both `preprocess.json` files. Verified by importing into an empty data folder
with no population raster: all six presets load, life-loss, officials bulletin,
wave KMZ and PDF all work.

```bash
# on the demo laptop, from the Flood-Guard folder (same code version)
python -m floodguard.cli pack import floodguard_demo_presets_120m.fgpack
make serve        # or: python -m uvicorn app.main:app --port 8000 (from backend/)
```

## R3.6 §5 status

| Item | Status |
|---|---|
| 5.1.1 Data packs | done |
| 5.1.2 Loss of life (Graham 1999) | done; Jonkman and the "depth-velocity saturating" function NOT ported |
| 5.1.3 Time-animated KML | done (`wave_kmz`) |
| 5.1.4 Thacker + NSE | done |
| 5.1.5 Playback speed | done |
| 5.1.6 CI | written, never executed |
| 5.2.7 River blockage | **done except the extra regressions**: natural-dam rules + Costa (1985) cross-check; barrier burned into the solver's DEM and lake storage above the pre-event water surface (R3.10). NOT done: Walder & O'Connor / Peng & Zhang (quarantined in the source, not transcribed) |
| 5.2.8 Delft3D FM | not done — no `dflowfm` on either machine, so nothing could be verified |
| 5.2.9 Breach uncertainty (Wahl 2004) | **skipped**: every band in the source is marked "TODO: UNVETTED", and Wahl (2004) predates and does not cover Froehlich (2008), FloodGuard's default model. The 3-model spread and breach ensemble remain the honest uncertainty display |
| 5.2.10 Economic damage (₹) | **skipped**: the source's depth-damage constants are "UNVETTED … no published source" and its ₹ unit costs are placeholders; Huizinga (2017) is quarantined there |
| 5.2.11 SAR terrain correction, 5.2.12 lake detection | not done — need Earth Engine credentials to run at all |
| 5.2.13 Dataset catalogue | done (`/api/datasets`); site-readiness registry done in R3.9 |
| 5.2.14 Detached run worker | done (R3.10) |
| 5.2.15 Citation checker | done |

## R3.7 Open questions — do not present as settled

- **Failure types.** `overtopping` is only a label: the breach model and
  routing treat it exactly like a complete break, so it is listed as "not
  modelled distinctly yet" and not computed. `partial_breach` is modelled since
  R3.10, but only live, with a user-set breach-depth fraction that is labelled
  as an assumption; no published source for that fraction was found, so no
  partial-breach preset exists (12 of the 18 planned presets were therefore
  not computed). Overtopping from MDDL is also physically incoherent without an
  inflow flood.
- **Tehri at 120 m**: Devprayag maximum depth 149 m at the town point (FRL). An
  earlier version of this note said the wave "does not reach Rishikesh within
  6 h" — **that was wrong**, an artefact of sampling the town's published point,
  2.3 km from the river. The channel gauge at Rishikesh's chainage (104.9 km)
  is reached at 264 min and Haridwar's (120.1 km) at 313 min, both still rising
  at 6 h (see the Town Gauges panel, `/api/results/<run>/gauges`). Mass closes,
  but 120 m cells average a narrow gorge, the DEM is a surface model, and the
  Koteshwar dam 22 km below Tehri is in the DSM. Unverified against any
  independent study.
- **Hirakud**: Boudh and Sonepur lie beyond the end of the 150 km traced reach,
  so their channel gauges fall back to the same last section (the gauges panel
  says so); their town-table rows are valley sections 3.8–5.9 km off the
  channel. Population at risk ~0.8 million (WorldPop).
- **Tehri curve**: the conic reconstruction gives 540 MCM at MDDL; NRLD live
  storage implies ~920 MCM, so live storage is ~14% high.
- **Velocity cap** engages on ~1e-5 of cell-updates on Tehri; reported per run.

## R3.9 Round 3b (afternoon of 2026-09-30)

| Area | Files |
|---|---|
| Presets at more than one resolution (`LIBRARY_RESOLUTIONS = (120, 60)`); 120 m keys unchanged, others suffixed `__r60`; `precompute --resolution`; resolution dropdown in the preset picker | `floodguard/library.py`, `cli.py`, `app/api/presets.py`, `app/api/simulate.py`, `components/PresetPicker.tsx` |
| **Town gauges**: depth-time curves at each town point AND at the river beside it (lowest bed point of the town's section); arrival, peak frame, still-rising-at-end, near-edge, shared-section flags | `floodguard/postprocess/gauges.py`, `/api/results/{run}/gauges`, `components/GaugesPanel.tsx` |
| **Provenance panel**: every value with the result.json / GeoTIFF-tag field it came from; honesty labels derived from those fields | `floodguard/postprocess/run_provenance.py`, `/api/results/{run}/provenance`, `components/ProvenancePanel.tsx` |
| **Site readiness registry**: tier computed from files (DEM must COVER the AOI, not merely exist), inputs present, presets stored per resolution | `floodguard/registry.py`, `/api/registry`, `components/RegistryPanel.tsx` (Home) |
| **Breach sensitivity (tornado)**: one-at-a-time, re-routed through the run's curve; ranges = span of the three breach models FloodGuard computes + MDDL-FRL (no assumed coefficient). Tehri: formation time dominates; Hirakud: breach width dominates | `floodguard/breach/sensitivity.py`, `/api/results/{run}/sensitivity`, `components/SensitivityPanel.tsx` |
| Fix: `preprocess.json` is found by its own recorded grid when the DEM is absent (a data-pack machine), and a run is never drawn with another resolution's sections | `floodguard/processed.py::find_preprocess_json`, `app/api/results.py::cross_section` |

Tests after 3b: backend **278 passed, 1 failed** (the same pre-existing SPH test);
frontend **30 passed** (12 files); build clean.

60 m presets: Hirakud on the server, Tehri on the laptop, started 13:38 IST;
all six succeeded. Measured wall time per run (`swe_fv`, `precompute --resolution 60`,
also in `data/library/index.json`):

| Preset (60 m, `swe_fv`) | Simulated | Machine | Wall time |
|---|---|---|---|
| Tehri, complete break, FRL | 6 h | laptop | 4198.1 s (overlapped ~2 min of test load; may be slightly inflated) |
| Tehri, complete break, mid | 6 h | laptop | 2082.1 s |
| Tehri, complete break, MDDL | 6 h | laptop | 1932.9 s |
| Hirakud, complete break, FRL | 24 h | server | 4114.5 s |
| Hirakud, complete break, mid | 24 h | server | 3436.8 s |
| Hirakud, complete break, MDDL | 24 h | server | 2636.9 s |

Hirakud batch total 2h50m19s (server). Before packing
them run `floodguard preprocess --scenario <yaml> --resolution 60` (cross-sections,
channel gauges, sensitivity) and `floodguard life-loss --runs "lib_*__r60" ...`.

Done for both dams (Tehri on the laptop, Hirakud on the server with round-3c code,
exported as `data/library/hirakud_60m.fgpack`, 65 files, 206.9 MB, imported on the
laptop). Combined pack **`data/library/floodguard_demo_presets.fgpack`** — 12 runs
(six at 120 m, six at 60 m), 262 files, 295.9 MB — supersedes
`floodguard_demo_presets_120m.fgpack`. Verified by importing into an empty data
folder (plus `data/scenarios` and `data/catalog` copied in): 12 presets added; for
all 12 runs `/api/presets`, summary, gauges, provenance, sensitivity, life-loss
(warning 0 min), frames return 200, and cross-section finds that run's own
resolution's sections. PDF, KMZ and the officials bulletin were not re-checked
for this pack.

## R3.10 Round 3c — remaining features (2026-09-30, afternoon)

| Area | What | Files |
|---|---|---|
| **Partial breach** | `breach.depth_fraction` (0-1 of structural height; mutually exclusive with `depth_m`). `scenario_type: partial_breach` without a fraction below 1 is refused. The fraction raises the breach invert, so routing leaves the pool below it behind (conic test: releases 7/8 of the volume at 0.5). The caveat "PARTIAL BREACH — ASSUMPTION …" is the first breach caveat and a run warning. Live only: listed in the preset API with the reason `library.not_precomputed_reason`. UI: "Breach Depth Fraction" field with an assumption note replaces Breach Depth for this type | `floodguard/scenario.py` (`breach_depth_m`), `breach/parameters.py`, `library.py`, `floodguard/pipeline.py`, `app/schemas/models.py`, `app/api/simulate.py`, `components/InputPanel.tsx` |
| **Barrier burned into the DEM** (§5.2.7) | For `dam_type: natural_blockage` (`blockage.burn_into_dem`, default on): a wall perpendicular to the traced path at the snapped point, walked out both ways in half-cell steps (4-connected, watertight) until the ground reaches the crest; crest length therefore MEASURED from the terrain. Thickness `blockage.base_length_m`, else 2 cells labelled a numerical minimum. Unconfined wall (no ground above the crest within 5 km, a void, or the DEM edge) → warning. Lake curve built on the PRE-EVENT DEM before the burn (storage above the pre-event water surface). Solver release point moved to the first path cell below the wall; breach cells never on the wall. Writes `barrier_mask.tif`, `dem_barrier_utm.tif` (tags `FG_BARRIER*`), `preprocess.json` `barrier` | `floodguard/preprocess/blockage.py`, `preprocess/pipeline.py`, `floodguard/pipeline.py::_build_engine_input` |
| **Detached run worker** (§5.2.14) | Each API job runs as its own detached OS process (`python -m app.core.worker`), talking through `data/jobs/<id>/` (scenario, run_meta, worker.json, progress.jsonl, heartbeat, status.json, worker.log). API restart: live worker (pid running AND heartbeat < 30 s) → reattached; finished → real outcome recorded; gone → `interrupted`. Stop kills the process tree immediately (`taskkill /T /F` / `killpg`) and deletes the partial `runs/<id>`. UI: "Stop run" button + stopped / interrupted notes | `app/core/worker.py`, `app/core/jobs.py`, `components/StopButton.tsx`, `pages/Simulation.tsx` |
| **CLI hardening** | Parse-time checks: positive/finite resolution & duration, `--limit ≥ 1`, ports 1-65535, warning minutes within ±1440, `pack import` file exists, `--data-dir` not a file, `precompute --type` choices, `precompute --resolution` must be a library resolution, unknown engine ids named. Bad scenario files → one line naming the field (`dam.lon: …`) or "not valid YAML"; exit 2; `-v` keeps tracebacks | `floodguard/cli.py` |

Detached worker, checked live on the laptop (a second API on port 8001,
Tehri quick estimates): the API process was killed mid-solve → the worker kept
running (heartbeat 4 s old); the API was restarted → it logged "reattaching to 1
running worker(s)" and recorded the job's real outcome (succeeded, 37.3 s run).
A second job was stopped mid-solve → status `cancelled` 1.7 s after the request,
no worker process left (including the venv launcher's child interpreter), and
the partial `runs/<id>` folder deleted. On Windows the venv `python.exe` is a
launcher that starts the real interpreter as a child, which is why Stop uses
`taskkill /T`.

Real-terrain check of the barrier (preprocess only, 120 m, the hypothetical
Bhagirathi blockage): wall confined on both sides, 240 m across the valley at
the 580 m crest, pre-event water surface 516.0 m at the barrier cell, lake
71.1 MCM above it.

**Full solve, burn on vs off** (laptop, 2026-09-30 20:19-20:23 IST, 120 m, 3 h, `swe_fv`;
same user-set hydrograph: peak 36,398 m³/s at 60 min, 71 MCM; runs
`hypothetical_blockage_bhagirathi_1790779960` (on) and `_1790779815` (off, from a
scratch copy of the YAML with only `burn_into_dem: false`)). HYPOTHETICAL inputs —
a machinery check, not an assessment:

| | burn ON | burn OFF |
|---|---|---|
| Flooded area | 3.96 km² | 4.02 km² |
| Max depth / max velocity | 70.39 m / 14.79 m/s | 68.13 m / 13.92 m/s |
| Devprayag arrival / depth | 71 min / 32.02 m | 74 min / 30.47 m |
| Wet cells (> 0.3 m) | 275 | 279 |
| Solver mass error / created by positivity | 7.8e-5 / 0 m³ | 1.2e-4 / 0 m³ |
| Solver runtime | 5.9 s | 39.2 s (overlapped the frontend tests + build; not comparable) |

Cell by cell (same grid): 27 cells (0.39 km²) are wet only with the burn OFF — 25 of
them lie 0.06-1.34 km **behind** the barrier (signed offset along the river's
downstream direction), i.e. breach outflow spreading back into the lake valley,
which the burn-off warning predicts. 23 cells (0.33 km²) are wet only with the
burn ON, all 1.9-10.4 km downstream. Where both are wet, burn ON is deeper by a
median 2.02 m (p5 1.10, p95 3.45). The Costa (1985) cross-check (6,585 m³/s,
ratio 5.53) is identical in both, as it depends only on the hydrograph.

Bug found by this run and fixed: the static KML export crashed ("cannot convert
float NaN to integer") when a flood polygon's arrival time was unknown — pandas
gives NaN, not None, so it passed the `is not None` check (and would have printed
"nan" in the description). `exports.py::write_kml` now treats NaN as unknown; test
`tests/test_kml_export.py`. The two crashed partial runs were moved to
`data/runs/.superseded/`.

Tests after 3c + the KML fix (laptop, 2026-09-30 ~20:30 IST): backend **321 passed,
1 failed, 3 skipped** (the failure is the pre-existing SPH
`test_depth_is_the_kernel_sum_and_recovers_a_uniform_layer`; the skips are the
"Earth Engine unconfigured" tests on this configured machine); frontend **32
passed** (13 files), `tsc --noEmit` clean, `npm run build` clean (chunk-size notice
only); `check_citations.py` 157 references: OK 149, OUTPUT_NAME 7, OUTSIDE_REPO 1,
no failures. `floodguard validate` not re-run. Dashboard on :8000 restarted on the
round-3c code (logs `data/library/server_3c.log`, `server_3c.err.log`).

## R3.8 Commands

```bash
python -m venv .venv && ./.venv/Scripts/python -m pip install -r requirements.txt && ./.venv/Scripts/python -m pip install -e backend
python -m floodguard.cli precompute --scenario tehri_bhagirathi --scenario hirakud_mahanadi [--dry-run]
python -m floodguard.cli preprocess --scenario data/scenarios/<id>.yaml --resolution 120   # cross-sections, reservoir curve
python -m floodguard.cli life-loss --runs "lib_*" --warning-min -60 --warning-min 0 --warning-min 60
python -m floodguard.cli pack export --runs "lib_*" --out demo.fgpack
python -m floodguard.cli pack import demo.fgpack
python -m floodguard.cli validate --out docs/validation
python scripts/check_citations.py
```

---

# Handoff — round 2

What was built on top of the round-1 handoff (`1.md`), what has and has not
been executed, and exactly what to run next. **Read §3 before quoting any SPH
number from a real-terrain run.**

---

## 1. What is new

### Second engine — FloodGuard-SPH (deliverable #2)

| File | What |
| --- | --- |
| `backend/floodguard/engines/_sph_kernels.py` | numba kernels: Wendland C2, cell-list neighbour search on the DEM grid, depth summation, **parallel** symmetric pair forces with per-thread buffers, bed slope, friction, wall sliding, rasterisation |
| `backend/floodguard/engines/sph_swe.py` | `SmoothedParticleSWE` engine, breach injector (critical-flow velocity), `SPHSettings`, 1-D verification harness (periodic strip) |
| `backend/floodguard/validation/sph_checks.py` | 5 checks wired into `make validate`: Ritter, Stoker, exact conservation, lake at rest (measured), refinement |
| `backend/floodguard/engines/availability.py` | `sph_swe` probe; `sph_pysph` and `dualsphysics` now substitute to `sph_swe` (same method family), labelled |
| `backend/floodguard/scenario.py` | `solver.sph` block (`SPHSpec`) — every SPH knob configurable from YAML |

Label everywhere: `FloodGuard-SPH (depth-integrated SWE-SPH)`. It is **not** a
3D WCSPH; `test_sph_is_labelled_as_depth_integrated_and_never_as_pysph` pins that.

### Pipeline

- Per-engine rasters `max_depth_<engine>.tif` etc. — the comparison code expected
  them but they were never written, so the table could not have populated even
  with two engines. Fixed.
- `frames_<engine>.npz` — one compressed array per stored frame → animated tiles.
- `bed.tif` (compute-window bed) → 3D view.
- `towns_by_engine` in `result.json`; `resolution_m`, `crs`, `completed_utc` too.
- `ensure_inputs()` — auto-acquires the DEM for a catalog dam picked in the GUI,
  and **re-mosaics when the cached DEM is at a different resolution** (it used to
  silently reuse 90 m for a 30 m request).
- User-supplied outflow hydrograph (`inflow_hydrograph_csv`) replaces the breach
  model; level/breach width are NaN ("not modelled"), never zero.
- ESA WorldCover fetched onto the DEM grid (`floodguard/data/landcover.py`) →
  mapped Manning's n + **agricultural-land metric** (was "not computed").

### API (new: `app/api/uploads.py`, `app/api/views.py`)

`/api/uploads/{dem|hydrograph|aoi}`, `/api/runs`, `/api/results/{id}/share`,
`/api/share/{code}`, `/api/results/{id}/frames`, `/legend`, `/towns-by-engine`,
`/3d/{meta,terrain.png,terrain-texture.png,water.png,water-texture.png}`,
`/aoi-stats`. Tiles take `?layer=depth|velocity|arrival|hazard|difference&engine=&frame=`.
The PDF export now generates on first request. The API serves `frontend/dist`
when it exists → one process, one port.

### Frontend

Demo Mode toggle, URL-synced view state, Share link (`/s/<code>`), layer +
engine pickers, frame animation, swipe map (`SwipeMap.tsx`), 3D view
(`Scene3D.tsx`, lazy-loaded), Upload Custom Data panel, "Any catalog dam"
source, AOI panel, per-engine town table, extra exports. Vitest + Testing
Library with 14 tests.

### Bugs found and fixed this round

1. **Overpass 406** — overpass-api.de rejects requests without an identifying
   User-Agent. Every OSM layer had been failing. Fixed; Tehri now has 23,826
   buildings, 19,913 roads, 111 health, 90 education, plus bridges/emergency/settlements.
2. Per-engine rasters never written → comparison could never populate.
3. Resolution silently ignored when a DEM mosaic existed at another resolution.
4. `summary.resolution_m` fell back to **0.0** (a fabricated number). Now read from the run; null if unknown.
5. Cross-section water surface was `bed + domain-wide max depth` (115 m everywhere near the thalweg). Now samples the local depth along the stored section coordinates; dry = null.
6. "Generate Report (PDF)" 404'd unless the CLI had been run.
7. "Dam in catalog" dropdown was permanently disabled.
8. A user DEM would have been mosaicked together with cached Copernicus tiles of other scenarios.
9. `docker-compose.yml` referenced two Dockerfiles that did not exist.
10. CLI progress was block-buffered, invisible in a redirected log.

---

### Round 2b — beyond the brief (HADR)

| File | What |
| --- | --- |
| `backend/floodguard/warning/bulletin.py` | alert levels (stated convention), EN/HI bulletin, SMS with segment counts, CAP 1.2 XML (Exercise/Test/Draft only, certainty Possible) |
| `backend/floodguard/warning/safe_ground.py` | nearest cell ≥ 2 m above the computed flood surface, via distance transform |
| `backend/app/api/warning.py` | `/warning`, `/warning/bulletin.txt?lang=`, `/warning/cap.xml`, `/breach-ensemble` |
| `backend/floodguard/pipeline.py` | `_write_breach_ensemble` → `breach_ensemble.json` (all 3 models routed) |
| `backend/floodguard/report.py` | PDF §2.1 Early-warning levels |
| `frontend/src/components/WarningPanel.tsx`, `Charts.tsx::BreachEnsembleChart`, `MapView` safe-ground layer | UI |
| `backend/tests/test_warning.py` (16), `frontend/src/components/WarningPanel.test.tsx` (1) | tests — both passed locally |

## 2. What was executed, and what was not

| Item | Status on the dev machine (Windows, Python 3.14, no conda/MSVC/Docker) |
| --- | --- |
| Backend tests | **165 passed** (before the last SPH-settings patch; re-run) |
| Frontend tests | **14 passed** |
| `tsc` / `npm run build` | clean |
| SPH verification checks | 5/5 pass (numbers in METHODOLOGY §4.5) |
| FV verification (7 checks) | not re-run this round — kernels untouched |
| `make validate` full, regenerating `docs/validation/` | **NOT run** — do it (writes the SPH plots) |
| Tehri data (DEM 90 m, WorldPop, all OSM layers, WorldCover) | fetched |
| Hirakud data | fetch was started in the background; check `data/raw/osm/hirakud_mahanadi/` |
| Any real-terrain two-engine run | **NOT completed** — see §3 |
| Docker build | **NOT run** (no Docker here) |

---

## 3. Known open issue — SPH cost on real terrain

On Tehri at 90 m the FV engine did 1 simulated hour in 2.6 min. The SPH engine
(first version: serial forces, `h_max_cells = 3`) slowed from milliseconds per
step to **~11 s per step at ~46,000 particles**, while only ~16 cells were wet.

Working hypothesis (not yet confirmed — the diagnostic was not run): particles
spray thinly over steep hillslopes, sit at the smoothing-length clamp, and each
such particle searches 169 buckets next to a dense pool of deep-water particles
— so neighbour counts explode. Changes already made in response:

- pair forces now run in parallel (conservation still exact, tested);
- one depth pass per step instead of two;
- `h_max_cells` 3 → **1.5** (search 169 → 49 buckets);
- `solver.sph.max_runtime_minutes` wall-clock budget: the run stops, keeps its
  results, and prints `SPH RUN TRUNCATED ...` at the top of the warnings;
- progress messages now show `ms/step` and `hs@max` (share of particles at the clamp).

**Run the diagnostic first** (≈ minutes):

```bash
python scripts/profile_sph.py --scenario tehri_bhagirathi --seconds 400
```

Read: `ms/step` over time, `at hs clamp (spray)`, `particles per cell max`.
If ms/step still climbs: try `--h-max-cells 1.0` and/or `--target-particles 60000`
and put the winning values in the scenario's `solver.sph` block. If `particles
per cell max` is in the thousands, the pool at the breach is the problem, not
the spray — report back with the printout.

---

## 4. Commands, in order

```bash
pip install -r requirements.txt && pip install -e backend    # fiona no longer needed
cd frontend && npm install && cd ..

make test                                   # backend + frontend
python -m floodguard.cli validate           # expect 12/12; regenerates docs/validation/
python scripts/profile_sph.py --seconds 400 # §3

# Data (re-run for WorldCover if landcover_utm.tif is missing)
python -m floodguard.cli data --scenario data/scenarios/tehri_bhagirathi.yaml --resolution 90
python -m floodguard.cli data --scenario data/scenarios/hirakud_mahanadi.yaml --resolution 120

# Runs — both engines are the scenario default now
python -m floodguard.cli simulate --scenario data/scenarios/tehri_bhagirathi.yaml --resolution 90 --duration 6
python -m floodguard.cli simulate --scenario data/scenarios/hirakud_mahanadi.yaml --resolution 120
#   FV only, if SPH is still slow:   --engines swe_fv
python -m floodguard.cli report                     # or the PDF button in the UI

python -m floodguard.cli demo --check       # all rows OK incl. "Two-engine comparison"
make serve                                  # http://localhost:8000, Demo Mode on
```

Publication run (overnight): `--resolution 30`. Record the runtime.

---

## 5. Not done, deliberately

- **Idukki** in the catalog: needs the NRLD-2019 Kerala sheet transcribed with
  page and PIC citations. Not guessed.
- **Malpasset 1959**: needs the digitised pre-failure DEM (EDF/TELEMAC benchmark).
- **GEE on real Sentinel-1**: needs `GOOGLE_APPLICATION_CREDENTIALS`.
- **ANUGA / PySPH**: need conda / a C compiler; the adapters are unchanged and
  report themselves unavailable honestly.
