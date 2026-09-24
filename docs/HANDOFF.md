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
