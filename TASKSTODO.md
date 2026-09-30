# TASKSTODO — precomputed demo library + features ported from OtherContestProject

Written 2026-09-30 on the dev laptop, for the Claude session on the **compute laptop**.
Read this whole file, then `CLAUDE.md`, then `docs/HANDOFF.md`, before touching code.

---

## 0. Situation in one paragraph

FloodGuard (this repo) is an SIH PS 26161 dam-break prototype. It is correct but slow:
a Tehri run at 90 m takes ~16 min, at 30 m ~7 h, and more with SPH. The user is
recording a **demo video** and has a **~10 hour budget** on this laptop. The goal is
(1) make the dashboard answer in seconds by serving **real, precomputed runs** for a
fixed set of presets, with a fast labelled "quick estimate" for anything else, and
(2) port selected features from the user's other codebase,
`../OtherContestProject/SIH-prototype/` (also the user's own code — no attribution
needed anywhere). Both folders must sit side by side, e.g. `D:\SIHFloodGuard\Flood-Guard`
and `D:\SIHFloodGuard\OtherContestProject\SIH-prototype`.

## 1. Rules for THIS laptop (they override parts of CLAUDE.md)

- **This laptop IS the compute machine.** CLAUDE.md says "do not run long simulations
  locally" — that was written for the dev laptop. Here you **may and must** run the
  precompute batch, the test suite and `floodguard validate`. Run long jobs in the
  background and keep working while they run.
- All of CLAUDE.md's **non-negotiable rules still apply**: no fabricated numbers (unknown =
  null / em dash, never 0), honest engine labels, provenance on every output, engine
  substitution only in `pipeline.py::_select_engine`, everything is config, tests are part of done.
- A quarantined / unverified formula stays quarantined (raises). Never ship a coefficient
  you cannot cite. If a feature below cannot be done honestly, skip it and say so.
- Do not commit or push unless the user asks.
- Keep the user posted: after each numbered task, one short status line.

## 2. Priority order and time budget (~10 h total)

The critical path is the precompute batch (~5 h of compute). **Start it as early as
possible** and build everything else while it runs.

| Order | Task | Budget | Must-have for demo? |
|---|---|---|---|
| A | Environment setup + data check (§3) | 0.5 h | yes |
| B | `floodguard precompute` command (§4.1) → **start the batch** | 1–1.5 h | **yes** |
| C | Preset API + quick-estimate mode (§4.2) | 1.5 h | **yes** |
| D | Input panel preset mode + result labels (§4.3) | 1.5 h | **yes** |
| E | Per-resolution processed dirs + preprocess cache (§4.4) | 1 h | yes (quick mode) |
| F | Tests for A–E, run backend + frontend suites (§4.5) | 0.5 h | yes |
| G | Tier-1-small features (§5.1) | remaining | nice |
| H | Larger ports (§5.2) — only if time remains; otherwise leave notes | — | no |

If the batch is slower than estimated, **do not** cut corners on correctness — let the
batch keep its priority order (most important presets first) and stop it when needed.

## 3. Task A — setup on this laptop

1. Do not reuse a copied `.venv` from another machine; create a fresh one:
   `python -m venv .venv`, then `./.venv/Scripts/python -m pip install -r requirements.txt`
   and `./.venv/Scripts/python -m pip install -e backend`; `cd frontend && npm install`.
   (`fiona` has no py3.14 wheel and is not needed — pyogrio is used.)
2. Record the machine: CPU model, **core count**, RAM, OS, Python version. Put it in
   HANDOFF at the end. Numba parallel kernels scale with cores; RAM is not the limit.
3. Check inputs: `data/processed/<scenario>/dem_utm.tif` and cached DEM tiles under
   `data/raw/` for `tehri_bhagirathi` and `hirakud_mahanadi`. If missing, run
   `./.venv/Scripts/python -m floodguard.cli data --scenario data/scenarios/<id>.yaml`
   (needs internet). Note: a run at a new resolution re-mosaics the DEM (no download if
   tiles are cached) and re-fetches ESA WorldCover onto the new grid (needs internet).
4. Quick sanity: `python -m floodguard.cli engines`, `npx tsc --noEmit` in `frontend/`.

## 4. The precompute + fast-demo work

### Agreed product decisions (do not relitigate)

- **Presets only** for instant results: the UI offers dropdowns of precomputed choices.
- **18 presets**: dams {`tehri_bhagirathi`, `hirakud_mahanadi`} ×
  failure types {`complete_dam_break`, `partial_breach`, `overtopping`} ×
  reservoir levels {`frl`, `mid`, `mddl`}.
  - `frl` = `dam.frl_m`, `mddl` = `dam.mddl_m`, `mid` = (frl + mddl) / 2 rounded to 0.01 m.
    Tehri: 830.0 / 785.0 / 740.0. Hirakud: 192.02 / 185.93 (185.925) / 179.83. Compute them
    from the YAML, do not hardcode. If a dam lacks mddl, skip `mid`/`mddl` for it.
  - Resolution **120 m**, engines **`["swe_fv"]` only** (SPH has an open perf bug), duration
    = the scenario's own (Tehri 6 h, Hirakud 24 h), breach model = scenario default
    (Froehlich 2008), everything else from the YAML.
  - `landslide_dam_breach` is NOT a preset (it is a label with no implementation yet).
- **Custom inputs** (anything not a preset, incl. catalog dams): run live as a
  **quick estimate** — 200 m, 1 h simulated, `swe_fv` only — labelled
  "Quick estimate — 200 m, 1 h simulated" everywhere (UI, result.json, PDF).
- Precomputed results are labelled "Precomputed on <UTC date>" — never presented as
  computed just now.

Estimated compute (scaled from the one measured number: Tehri 90 m FV = 2.6 min per
simulated hour, cost ∝ 1/res³): Tehri ~7 min/run (~1 h for 9), Hirakud ~25 min/run
(~4 h for 9, **unmeasured** — wide floodplain may be slower). Total ~5 h; ~4 h if both
dams run as two parallel processes on a machine with ≥16 cores.

### 4.1 Task B — `floodguard precompute`

New module `backend/floodguard/library.py` (pure logic, testable without running a solver):
- `PRESET_TYPES`, `PRESET_LEVELS`, `LIBRARY_RESOLUTION_M = 120.0`,
  `QUICK_RESOLUTION_M = 200.0`, `QUICK_DURATION_H = 1.0`.
- `preset_key(scenario_id, scenario_type, level_name) -> str`, e.g.
  `tehri_bhagirathi__complete_dam_break__frl`. Run id = `lib_<key>` (deterministic, so
  "done" == `data/runs/lib_<key>/result.json` exists → resumable).
- `iter_presets(scenario)` in **priority order**: (`complete_dam_break`, `frl`) first, then
  the other levels of complete break, then partial breach, then overtopping.
- `build_preset_scenario(base: Scenario, type, level) -> Scenario`: deep copy, set
  `scenario_type`, `reservoir.initial_level_m`, `domain.resolution_m = 120`,
  `engines = ["swe_fv"]`, then re-validate with `Scenario.model_validate(...)`.
  Keep `scenario.id` unchanged (it is the processed-data folder key).
- Index at `data/library/index.json`: `{key: {run_id, scenario_id, scenario_type, level,
  level_m, resolution_m, duration_hours, completed_utc, wall_seconds}}`. Write atomically
  (temp file + replace) after **each** successful run.
- `lookup(data_dir, key)` returns the entry only if the run's `result.json` exists.

CLI in `backend/floodguard/cli.py` (follow the existing `cmd_*` / `build_parser` pattern):
```
floodguard precompute --scenario tehri_bhagirathi [--scenario hirakud_mahanadi]
                      [--data-dir D] [--limit N] [--dry-run] [--force]
```
- Calls the existing `floodguard.pipeline.simulate(scenario, data_dir, run_id=..., engines=["swe_fv"])`.
- Skips presets already done unless `--force`. `--dry-run` prints the plan + estimate.
- Prints per-run wall time and a running ETA; flush stdout (server logs).
- A failure in one preset is logged and recorded in the index as failed, then the batch continues.
- Add a `precompute` target to the `Makefile`.

Then **start the batch immediately** in the background, log to `data/library/precompute.log`:
```
./.venv/Scripts/python -m floodguard.cli precompute --scenario tehri_bhagirathi --scenario hirakud_mahanadi
```
(or two processes, one per dam, if the machine has ≥16 cores). After the first Hirakud run
finishes, report its measured time and the revised ETA to the user.

**While the batch runs, do NOT edit files it imports mid-run** in ways that break it
(`pipeline.py`, `preprocess/`, `engines/`, `data/acquire.py`). Python has already imported
them, so edits are safe for the running process, but the next preset in the same process
uses the old code — that is fine. Do not run another simulation at 120 m on the same
scenario concurrently (shared processed dir — see §4.4).

### 4.2 Task C — API

Facts about the current code (verified on the dev laptop):
- `backend/app/api/simulate.py::build_scenario()` turns every request into one validated
  `Scenario` — the single place to hook in.
- `POST /api/simulate` creates a job; `JobRunner._run_one` (`backend/app/core/jobs.py`)
  calls `simulate(..., run_id=job_id)`, so **run id == job id** today.
- Frontend `Simulation.tsx` (~line 93) sets `runId = jobId` when the job succeeds.
- `GET /api/runs` (`app/api/views.py`) lists any `data/runs/*/result.json`.

Changes:
1. `SimulationRequest` (`app/schemas/models.py`): add `preset_key: str | None` and
   `quick: bool = False`. `JobCreated`: add `run_id: str | None` and
   `mode: Literal["precomputed", "quick_estimate", "full"]`.
2. `GET /api/presets`: every defined preset with `available` (from the index), level in m,
   labels, `completed_utc`; plus the quick-estimate settings.
3. `POST /api/simulate`:
   - `preset_key` given and available → create a job record, finish it immediately as
     SUCCEEDED with `result_path` of the library run, return `run_id = lib_<key>`,
     `mode="precomputed"`. Unknown/unavailable key → 404/409 with a clear message
     (never silently fall back to a different run).
   - `quick=True` → force resolution 200, duration 1 h, engines `["swe_fv"]` after
     `build_scenario`, record `run_mode: "quick_estimate"` in provenance, queue normally.
   - neither → unchanged behaviour (`mode="full"`), so the CLI/API full path still works.
4. Put `run_mode` (+ `library_key`, `precomputed_utc` for presets) into `result.json`
   provenance and expose it in `GET /api/results/{run}/summary` and `/api/runs`.
5. Check with grep whether any results endpoint reads `data/processed/...` (e.g.
   `app/core/config.py:47` exposes a processed dir). If yes, the data-pack export (§5.1)
   must include those files too.

### 4.3 Task D — frontend

- `components/InputPanel.tsx`: add a mode switch at the top:
  **"Preset — instant"** (default) and **"Custom — quick estimate"**.
  - Preset mode: three dropdowns (Dam, Failure type, Reservoir level with the metre value),
    fed by `GET /api/presets`; unavailable combos are disabled with "not precomputed yet".
    Run → `{scenario_id, preset_key}`. Hide engine picker / breach fields / resolution.
  - Custom mode: the existing form, sends `quick: true`; show a note "Runs live at 200 m for
    1 simulated hour (~15–60 s). Coarser than presets."
  - Current defaults to change: `selectedEngines` defaults to `['swe_fv','sph_swe']` and
    `resolution` to `'90'` — in custom mode force `['swe_fv']`.
- `pages/Simulation.tsx::handleRun`: if the response has `run_id` and
  `mode === "precomputed"`, call `loadRun(run_id)` directly (skip the job socket).
- A visible badge on the results area: "Precomputed on <date> · 120 m" or
  "Quick estimate · 200 m · 1 h simulated".
- Add a `usePresets` hook in `api/hooks.ts` and types in `types/api.ts`.
- Tests: a Vitest for InputPanel preset mode (renders dropdowns, disables unavailable,
  submits `preset_key`) and for the badge.

### 4.4 Task E — per-resolution processed data + preprocess cache

Bug to fix before quick mode is usable: `data/processed/<scenario_id>/dem_utm.tif` is ONE
file per scenario. `pipeline.py::ensure_inputs` re-mosaics it whenever the requested
resolution differs, so alternating 120 m presets and 200 m quick runs thrash it, and two
jobs can overwrite each other. `landcover_utm.tif` is only used when it matches the DEM grid
exactly (`preprocess/pipeline.py` ~line 356) so a mismatch silently degrades to uniform
Manning's n (with a warning).
- Make the processed dir resolution-scoped: `data/processed/<scenario_id>/r<res>/`
  (e.g. `r120`, `r200`). Touch points: `data/acquire.py` (dem_utm, landcover_utm,
  cache keys), `pipeline.py::ensure_inputs` (~line 531) and ~line 832,
  `preprocess/pipeline.py::run_preprocess` (~line 171), `cli.py` (~lines 194, 230),
  `app/core/config.py:47` and any API reading it. Keep a fallback that reads the old flat
  layout when it matches the requested resolution, so existing data still works.
- **Do this after the batch has finished its current scenario, or only for new paths** — the
  running batch must not have its files moved under it. Simplest: implement it with the
  fallback, and only let new runs write to `r<res>/`.
- Cache the expensive part of `run_preprocess` (conditioning: fill, D8, accumulation,
  snap, trace, corridor, catchment, cross-sections, roughness) per
  (scenario id, resolution, DEM sha256) as an `.npz` + json. The reservoir build depends on
  `initial_level_m`, so recompute it (cheap) or key it by level too.

### 4.5 Task F — tests

- `backend/tests/test_library.py`: preset keys/ordering, level derivation (mid rounding,
  missing mddl), `build_preset_scenario` overrides, index atomic write, lookup requires
  result.json, precompute skip/resume logic with `simulate` monkeypatched.
- API tests (extend `tests/test_api.py` style): `/api/presets`; preset submit returns
  `run_id` + `precomputed` using a fake `data/runs/lib_x/result.json` in a tmp data dir;
  unknown preset → 404; `quick=True` forces 200 m / 1 h / swe_fv (inspect the scenario
  passed to the runner, do not solve).
- Run: `./.venv/Scripts/python -m pytest backend/tests -q` and `cd frontend && npm test`
  and `npm run build`. Previous baseline: 165 backend + 14 frontend passing.

## 5. Features to port from `../OtherContestProject/SIH-prototype/`

Read each source file fully before porting; re-express it in FloodGuard's structure and
naming (`backend/floodguard/...`, FastAPI routers in `backend/app/api/`, React+TS panels).
Carry over its honesty notes; drop anything it itself marks as fabricated/quarantined.

### 5.1 Do within the 10 h if at all possible (small, safe)

1. **Data packs** — `services/api/temporaryproject_service/data_packs.py`. CLI
   `floodguard pack export --runs lib_* --out demo.fgpack` / `floodguard pack import demo.fgpack`
   (zip: run folders + `data/library/index.json` + manifest with sha256). This is how the
   finished library gets to the laptop that records the demo. Do this right after §4.
2. **Loss-of-life estimate** — `temporaryproject/impact/fatality.py`, the **Graham (1999)
   USBR DSO-99-06** method only. Keep Jonkman quarantined; do not port the renamed
   "depth-velocity saturating" function. Inputs already exist in FloodGuard
   (`impact/exposure.py` population at risk, warning lead time from `warning/`). Show in the
   impact panel, warning bulletin and PDF with the method name and its caveats.
3. **Time-animated KML** — `temporaryproject/export/kml.py::export_time_animated_kml`
   (TimeSpan). Add to `postprocess/exports.py` and the export panel.
4. **Thacker 2D parabolic bowl + NSE** — Thacker from the other solver's gated tests
   (`temporaryproject/solver/__init__.py` names it; find the test in `tests/test_solver.py`),
   NSE from `temporaryproject/validation/metrics.py`. Add to `floodguard validate`.
5. **Playback speed control** — `frontend/src/panels/PlaybackRate.jsx` → TS in `Simulation.tsx`.
6. **GitHub Actions CI** — adapt `.github/workflows/ci.yml` (pytest + vitest + build).
   Skip the Windows installer workflow.

### 5.2 Larger ports — only if time remains, else leave precise notes in HANDOFF

7. **River blockage / landslide dam** (fills the "river blockage" part of PS 26161; today
   `landslide_dam_breach` is only an enum in `scenario.py` and `models.py`):
   `terrain/blockage.py` (barrier on DEM, lake stage-storage above pre-event water surface),
   `terrain/dem_update.py` (DEM with barrier burned in, metadata says so),
   `terrain/natural_dam.py` (Costa 1985 active with its own bands; Walder & O'Connor and
   Peng & Zhang stay quarantined). Also `scripts/run_blockage.py` for the flow.
8. **Real Delft3D FM** — `delft3d/dfm_model.py`, `delft3d/ugrid.py`,
   `validation/delft3d_benchmark.py`, `scripts/validate_against_delft3d.py`. Compare with
   FloodGuard's `engines/delft3d_adapter.py`; the UGRID `*_net.nc` writer is the likely gap.
   Only label anything "Delft3D" if `dflowfm` is actually found (`engines/availability.py`).
9. **Breach uncertainty** — Monte Carlo + Wahl (2004) bands from `terrain/breach.py`,
   OAT sensitivity from `validation/sensitivity.py` (it has a `TODO: VERIFY` on its
   coefficient table — verify or leave out).
10. **Economic damage (₹)** — `impact/damage.py` + `gee/built_up.py`. Port ONLY if the
    depth-damage curves carry real citations; otherwise skip and say so.
11. **SAR terrain correction** — `gee/terrain_correction.py` (radar shadow in gorges);
    integrate with `data/gee.py`.
12. **Lake detection from Sentinel-1** — `gee/blockage_detect.py`; "built, never executed"
    without Earth Engine credentials.
13. **Dataset catalogue with licences** — `services/.../datasets.py`; **site readiness
    registry** — `services/.../registry.py`; small API + panels.
14. **Detached run worker** — `services/.../run_worker.py`, `script_runs.py` (runs survive
    an API restart).
15. **Citation checker** — `tools/check_citations.py`.

Do NOT port: CUDA solver, PySPH/DualSPHysics, Electron app, ParaView/MATLAB/Cesium,
.docx report, Celery/Redis, FD2320/evacuation directives (FloodGuard has its own
equivalents), Malpasset/Chamoli benchmarks (needs data FloodGuard does not have).

## 6. Deliverables at the end

1. The 18 presets (or as many as finished) in `data/runs/lib_*` + `data/library/index.json`,
   with the **measured** wall time per run.
2. A data pack file for the demo laptop, with the exact import command.
3. All tests passing (paste the counts), `npm run build` clean.
4. `docs/HANDOFF.md` updated: what changed, what is untested, measured timings, machine
   specs, which §5 items were done / skipped and why.
5. `docs/DEMO_SCRIPT.md` updated for the preset flow, using **only real numbers** from the
   finished runs.
6. `CLAUDE.md` "Current state" section updated. Do not copy the compute-laptop exception
   from §1 into CLAUDE.md; it applies to this laptop only and lives in this file.
