# FloodGuard India — context for Claude Code sessions

Dam-break / flash-flood inundation modelling platform for **Smart India
Hackathon PS 26161** ("Dam Break Inundation Modelling Using Hydrodynamic
Modelling of any River"). Stay inside that problem statement.

- `SPEC.md` — the contract. §1 = non-negotiable rules.
- `docs/HANDOFF.md` — **round-2 handoff: what changed, what is untested, exact commands. Read it first.**
- `../1.md` (in `D:\SIH_P2`) — round-1 handoff (phases 0–10, the 9 solver bugs not to regress).
- `docs/METHODOLOGY.md`, `docs/DEMO_SCRIPT.md`, `docs/DATA_SOURCES.md`, `docs/AUDIT.md`.

## Working preferences (from the user)

- **Do not run long simulations, profiling or full test/validation suites locally.**
  The user runs those on a separate server. Write the code, then give the exact
  commands to run. Tiny import/type checks (`python -c "import ..."`, `npx tsc --noEmit`) are fine.
- Do not commit or push unless asked. Nothing from round 2 is committed yet.
- Dev machine: Windows, Python 3.14 in `.venv/` (use `./.venv/Scripts/python`), Node 24,
  no conda, no MSVC, no Docker. `fiona` has no 3.14 wheel — not needed (pyogrio).
- Shell heredocs containing quotes break in the Bash tool; write patch scripts with the Write tool.

## Non-negotiable rules (tests enforce them)

1. **No fabricated numbers.** Unknown = `None` / `null` / em dash in the UI. Never 0.
2. **Label engines honestly.** Display names come from `floodguard/engines/availability.py`.
   Never show "Delft3D" without a dflowfm binary; never call FloodGuard-SPH "PySPH".
3. **Provenance on every output** (`app/core/provenance.py`).
4. **Engine substitution only in `floodguard/pipeline.py::_select_engine`.** Adapters raise `EngineUnavailable`.
5. **Everything is config** — a dam is a YAML in `data/scenarios/`.
6. **Tests are part of done.**

## Current state (end of round 2, 2026-09-25)

Done: all P0/P1 features and most P2 — see the Roadmap in `README.md`.
Two engines: `swe_fv` (FloodGuard-SWE, finite volume, verified 7/7) and
`sph_swe` (FloodGuard-SPH, depth-integrated SPH, verified 5/5, files
`engines/sph_swe.py`, `engines/_sph_kernels.py`, `validation/sph_checks.py`).
Both scenario YAMLs default to `engines: [swe_fv, sph_swe]`.
Last local results: 165 backend tests + 14 frontend tests passing; `npm run build` clean.
Round 2b (also done): early warning — `floodguard/warning/` (alert levels, safe ground, EN/HI
bulletin, SMS, CAP 1.2 Exercise-only), `app/api/warning.py`, breach-model ensemble
(`breach_ensemble.json`), PDF §2.1, `WarningPanel.tsx`, `BreachEnsembleChart`; 16 + 1 new tests passed.
Not yet seen on a real run: the warning panel, safe-ground lines and ensemble chart need a
completed run made with this code (older runs lack `bed.tif` / `breach_ensemble.json`).

## Remaining work, in priority order

1. **SPH performance on real terrain (open bug).** Tehri 90 m: FV does 1 h in 2.6 min; SPH
   went to ~11 s/step at ~46k particles with only ~16 wet cells. Mitigations already coded
   but UNTESTED on real terrain: parallel pair forces, one depth pass/step, `h_max_cells` 3→1.5,
   `solver.sph.max_runtime_minutes` budget (truncates + warns), `ms/step` and `hs@max` in progress.
   Diagnose with `python scripts/profile_sph.py --scenario tehri_bhagirathi --seconds 400`
   (user runs it and pastes the output). Hypothesis: thin particle spray at the kernel clamp
   next to a dense pool → neighbour explosion. Possible fixes if confirmed: smaller `h_max_cells`,
   fewer `target_particles`, bucket size decoupled from DEM cell, per-particle neighbour cap.
   Keep volume/momentum conservation exact (test `test_sph_conserves_volume_and_momentum_exactly`).
2. User to run on server: `make test`, `python -m floodguard.cli validate` (expect 12/12,
   regenerates `docs/validation/` incl. SPH plots), then two-engine Tehri + Hirakud runs,
   `floodguard report`, `floodguard demo --check`. Then update README/DEMO_SCRIPT numbers
   (flooded area, arrivals, CSI between engines) from the real runs — only real numbers.
3. Re-run `floodguard data` for both scenarios so `landcover_utm.tif` (ESA WorldCover) exists
   and is in the manifest (Hirakud was fetched before land cover was added).
4. One 30 m publication run (overnight, server).
5. Docker: `docker compose up --build` has never been executed — first run is a test.
6. Not doable without real data — do NOT fabricate: Idukki catalog entry (needs NRLD-2019 Kerala
   sheet with page/PIC citations), Malpasset 1959 benchmark (needs pre-failure DEM), GEE on real
   Sentinel-1 (needs credentials), ANUGA/PySPH (need conda / C compiler).

## Layout pointers

- API: `backend/app/api/` — `results.py` (summary, comparison, tiles with `layer/engine/frame`,
  frames, legend, cross-section, export), `views.py` (runs list, share links, 3D assets, AOI stats),
  `uploads.py` (DEM/hydrograph/AOI validation), `simulate.py` (jobs; accepts `dem_upload_id`,
  `hydrograph_upload_id`, `dam_id`).
- Science: `backend/floodguard/pipeline.py` (`ensure_inputs`, `load_user_hydrograph`,
  per-engine rasters, `frames_<engine>.npz`, `bed.tif`), `data/landcover.py`, `data/uploads.py`.
- Frontend: `frontend/src/pages/Simulation.tsx` (Demo Mode, share, layers, animation),
  `components/{MapView,SwipeMap,Scene3D,UploadPanel,InputPanel,ResultsPanel}.tsx`; tests `*.test.tsx`.
- Commands: `make test | validate | simulate-both | serve | profile-sph` (see `Makefile`).
