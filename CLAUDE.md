# FloodGuard India — context for Claude Code sessions

Dam-break / flash-flood inundation modelling platform for **Smart India
Hackathon PS 26161** ("Dam Break Inundation Modelling Using Hydrodynamic
Modelling of any River"). Stay inside that problem statement.

- `SPEC.md` — the contract. §1 = non-negotiable rules.
- `docs/HANDOFF.md` — **round-3 handoff (R3.x sections) on top of round 2: what changed, what is untested, exact commands, measured timings. Read it first.**
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

## Current state (end of round 3, 2026-09-30)

Round 3 (details: `docs/HANDOFF.md` R3.1-R3.8):
- **Preset library.** `floodguard precompute` computes presets into `data/runs/lib_<key>/`
  with an index at `data/library/index.json` (`backend/floodguard/library.py`). Six are done:
  Tehri + Hirakud × complete dam break × FRL / mid / MDDL, 120 m, `swe_fv` only. The dashboard
  opens on "Preset — instant" (`GET /api/presets`, `POST /api/simulate {preset_key}`); anything
  else runs as a labelled quick estimate (200 m, 1 h, `swe_fv`, `quick: true`). `run_mode`
  (`precomputed` / `quick_estimate` / `full`) is in result.json, the summary, the badge, the PDF.
- **Failure types:** `overtopping` is a label only (routed like a complete break), listed as
  "not modelled distinctly yet". `partial_breach` is modelled LIVE ONLY: it requires
  `breach.depth_fraction` (0-1, user assumption, never predicted; `Scenario.breach_depth_m`)
  which raises the breach invert, and every output labels the fraction as an assumption; it is
  not precomputed (`library.not_precomputed_reason`). `landslide_dam_breach` requires
  `dam_type: natural_blockage` and user-supplied breach width/time; the peak is cross-checked
  against Costa (1985) (`breach/natural_dam.py`); the barrier is burned into the solver's DEM
  wall to wall (`preprocess/blockage.py`, `blockage:` section of the scenario) with lake storage
  from the pre-event DEM.
- **Jobs run in a detached worker process** (`app/core/worker.py`): they survive an API restart
  (reattached via `data/jobs/<id>/` files + heartbeat), and Stop kills the process tree at once
  and discards partial output. `JobRunner(detached=False)` keeps the in-thread runner.
- **CLI input is validated** at parse time (`cli.py` `_positive_float` etc., `CliError`): one
  line + exit 2 instead of a traceback; `-v` keeps tracebacks.
- **Four solver/pipeline bugs fixed** (routing created water; reservoir curve built at the
  starting level instead of FRL; breach inflow added for un-elapsed time; positivity clipping
  created water → outflow limiter in `engines/_swe_kernels.py::outflow_limiter`). Every run now
  records `volume_created_by_positivity_m3` (0 on all six presets) and warns on any numerical
  mass gain > 1%. Runs made before 2026-09-30 06:00 UTC are superseded.
- New: data packs (`floodguard pack export/import`, `backend/floodguard/packs.py`), Graham (1999)
  loss of life (`impact/life_loss.py`, officials-only in the bulletin), per-frame wave KMZ,
  Thacker bowl + NSE in `validate`, playback speed, `/api/datasets`, per-resolution processed
  dirs (`backend/floodguard/processed.py`, `data/processed/<id>/r<res>/`), CI workflow (never run),
  `scripts/check_citations.py`.
- 60 m presets also done (both dams × FRL/mid/MDDL, keys `__r60`, with 60 m preprocess + life-loss);
  demo pack `data/library/floodguard_demo_presets.fgpack` = all 12 presets (HANDOFF R3.9).
- UI: dark theme by default with a header toggle (`src/theme.ts`, theme layer in `src/index.css`) — HANDOFF R3.11.
- Last measured (2026-09-30 ~21:30 IST): backend **326 passed, 3 skipped** (the SPH
  `test_depth_is_the_kernel_sum_and_recovers_a_uniform_layer` passed this once after failing every
  earlier run — flaky, not fixed; skips = EE-unconfigured tests); frontend **34 passed**, build clean; `validate` **12/13** (FV 8/8, SPH 4/5 — SPH Ritter h(dam) 10.03% > 5%).

## Remaining work, in priority order

1. **SPH regression** (Ritter h(dam) 10% and the kernel-sum test) — most likely round 2's last
   SPH-settings patch; then the open SPH real-terrain performance bug from round 2
   (`scripts/profile_sph.py`). SPH is not used by any preset.
2. **Model overtopping distinctly** (needs a cited basis and an inflow flood). Partial breach is
   done as a user-set fraction; a cited partial-breach geometry would allow presets.
3. **Check Tehri at 120 m against an independent study** (Devprayag 149 m peak depth at the town point;
   the river at Rishikesh is reached at 264 min, still rising at 6 h — extend to 12 h) and make the 30 m publication run.
4. River blockage, remaining: Walder & O'Connor / Peng & Zhang only once transcribed from the
   primary sources; a measured barrier base length instead of the two-cell numerical minimum.
5. Run the CI workflow (needs a push) and `docker compose up --build` (never executed).
6. Not doable without data/credentials — do NOT fabricate: Idukki catalog entry, Malpasset
   benchmark, GEE on real Sentinel-1, Delft3D without `dflowfm`, ANUGA/PySPH.

## Layout pointers

- API: `backend/app/api/` — `results.py` (summary, comparison, tiles with `layer/engine/frame`,
  frames, legend, cross-section, export), `views.py` (runs list, share links, 3D assets, AOI stats),
  `app/api/uploads.py` (DEM/hydrograph/AOI validation), `simulate.py` (jobs; accepts `dem_upload_id`,
  `hydrograph_upload_id`, `dam_id`).
- Science: `backend/floodguard/pipeline.py` (`ensure_inputs`, `load_user_hydrograph`,
  per-engine rasters, `frames_<engine>.npz`, `bed.tif`), `data/landcover.py`, `data/uploads.py`.
- Frontend: `frontend/src/pages/Simulation.tsx` (Demo Mode, share, layers, animation),
  `components/{MapView,SwipeMap,Scene3D,UploadPanel,InputPanel,ResultsPanel}.tsx`; tests `*.test.tsx`.
- Presets: `backend/floodguard/library.py`, `app/api/presets.py`, `components/PresetPicker.tsx`.
- Commands: `make test | validate | precompute | serve | profile-sph` (see `Makefile`);
  `python -m floodguard.cli pack import <file>.fgpack` to load precomputed runs.
