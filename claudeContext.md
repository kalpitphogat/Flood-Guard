# claudeContext.md — pick up exactly where the last session stopped

Written 2026-09-30 14:15 IST; last updated 16:00 IST (after round 3c and the paused Earth Engine work) at the end of a long Claude Code session on the
**compute laptop** (`E:\SIH_FLOOG_GUARD\Flood-Guard`). Read this first, then
`CLAUDE.md` (project rules), then `docs/HANDOFF.md` sections **R3.1–R3.10**
(everything done on 2026-09-30, with measured numbers). `TASKSTODO.md` is the
original brief for this round.

---

## 1. How this user wants you to work (non-negotiable)

- **Plan first.** For any multi-part request, state what you will do and wait
  for the user's go-ahead before implementing. Offer choices with a
  recommendation (the user answers quickly).
- **OtherContestProject** (`E:\SIH_FLOOG_GUARD\OtherContestProject\OtherContestProject\SIH-prototype`)
  is the user's own code, used **as a reference only**: read its logic, then
  write FloodGuard's own version with **new names**. Never copy its code
  verbatim, never take its **data** (rasters, runs, coefficient tables). Take
  every coefficient from the **primary publication** and cite page/table.
- Work **only inside `Flood-Guard/`**. **NEVER commit or push** — the user said
  explicitly: "do not push anything to github i will do it on my own".
- **Never open, print or read the Earth Engine key file** (the user rejected even
  printing its metadata). Only pass its path to the library.
- **No fabricated numbers** (unknown = null / "—", never 0); honest engine labels;
  every output carries provenance; tests are part of done (see CLAUDE.md).
- If something cannot be done honestly, skip it and say why.
- Give the user one short status line after each task.

## 2. State at hand-off

### Update 20:10 IST — steps 1–3 of section 3 DONE
Hirakud 60 m batch finished (3/3; MDDL 2636.9 s). Server synced to round-3c code.
60 m preprocess + life-loss done for both dams; `data/library/floodguard_demo_presets.fgpack`
(12 runs, 262 files, 295.9 MB) exported and verified — see HANDOFF R3.9.
Steps 4–6 also DONE (~20:30 IST): blockage burn on/off full solve compared (HANDOFF R3.10;
it exposed and fixed a KML NaN crash, `tests/test_kml_export.py`); dashboard :8000 restarted
on 3c code; backend 321 passed / 1 failed (SPH, pre-existing) / 3 skipped, frontend 32 passed,
build clean, citations OK. Still open: Earth Engine (paused — ask), 12 h Tehri, overtopping,
SPH regression. The Tehri 60 m preprocess log could not be read (auto-mode classifier denial);
the r60 preprocess.json exists and is used by the API.
~21:30 IST: demo polish done — dark theme (default) + toggle, Esri dark basemap, chart
axis fixes, "nan" settlement fix, cross-section reset on dam switch, Monitoring marked
experimental (HANDOFF R3.11). Dashboard :8000 restarted with it. Backend 326 passed /
3 skipped, frontend 34 passed. Server copy lacks R3.10-KML + R3.11 backend changes.
The table below is the 16:00 state, kept for history.

### Running right now (check before doing anything)
| What | Where | Status at 16:00 IST |
|---|---|---|
| `precompute --scenario hirakud_mahanadi --resolution 60` | server, `~/Flood-Guard/data/library/precompute.log` | FRL + mid DONE; **MDDL still running** |
| Tehri 60 m batch | laptop | **finished**: 3 succeeded, 0 failed |
| Dashboard `uvicorn app.main:app --port 8000` | laptop, http://localhost:8000 | running **round-3b code** — restart it to serve 3c |

Measured 60 m wall times (`swe_fv`, index `data/library/index.json`):
Tehri FRL 4198 s, mid 2082 s, MDDL 1933 s (laptop; the FRL run overlapped ~2 min
of test load, so it may be slightly inflated); Hirakud FRL 4114 s, mid 3437 s
(server); Hirakud MDDL pending. Not yet written into HANDOFF.

Check the server:
```bash
ssh -i ~/.ssh/floodguard_server -o BatchMode=yes user7@172.16.121.24 \
  'sed -n "/60 m presets/,\$p" ~/Flood-Guard/data/library/precompute.log | grep -E "DONE|FAILED|Batch finished"'
```
The log prints a solver line only when a frame lands on a step divisible by
500, so **absence of log lines is not slowness**. Check CPU instead. The server
still has round-3b code; sync it (section 4) only AFTER its batch finishes.

### Done and verified
- **6 presets at 120 m** (Tehri + Hirakud × complete break × FRL/mid/MDDL), fixed
  solver, mass closes (0 m³ created). Measured wall times (s): Tehri 178.5 / 160.8
  / 139.2 (laptop), Hirakud 428.4 / 344.8 / 279.6 (server). Index:
  `data/library/index.json`.
- **Demo pack** `data/library/floodguard_demo_presets_120m.fgpack` (63.8 MB, 128
  files, the six 120 m presets) — verified by importing into an empty data dir.
  **It does NOT include the new 60 m presets or the round-3b features' caches.**
- Features: preset library + `precompute`, preset/quick-estimate API + UI,
  per-resolution processed dirs, data packs, Graham (1999) loss of life, wave
  KMZ, Thacker + NSE, playback speed, CI file (never run), dataset catalogue,
  citation checker, natural-dam (Costa 1985) path, **resolution dropdown**,
  **town gauges**, **provenance panel**, **site registry**, **breach
  sensitivity tornado** (last four = round 3b, see HANDOFF R3.9).
- Round 3c (HANDOFF R3.10), user said "implement the rest of the remaining
  features": **partial breach** (user-set `breach.depth_fraction`, live only,
  labelled an assumption), **barrier burned into the DEM** for natural
  blockages (`preprocess/blockage.py`), **detached run worker + Stop**
  (`app/core/worker.py`; restart-survival and Stop verified live on port 8001),
  **CLI input hardening** (`cli.py`, `CliError`).
- Four solver/pipeline bugs fixed (HANDOFF R3.3) — do not regress them;
  `tests/test_swe_mass.py`, `test_breach.py` guard them.
- Tests (last full run, 14:45 IST, before one CLI test fix): backend **316
  passed, 2 failed** — `test_packs.py::test_cli_round_trip` (fixed since:
  `pack import` of a missing file keeps exit code 1; that file + the CLI tests
  pass, 30/30) and the pre-existing SPH
  `test_sph_swe.py::test_depth_is_the_kernel_sum_and_recovers_a_uniform_layer`.
  Frontend **32 passed**; `npm run build` clean; `check_citations.py` all OK.
  Tests written after that run: `test_sar_geometry.py` (7 pass). Re-run the whole
  suite before quoting counts. `floodguard validate` last: **12/13** (FV 8/8, SPH 4/5).

### Earth Engine — IN PROGRESS, NOT VALIDATED (user approved plan "A + B + C + D")
- Access works: project `flood-analysis-510209`, service-account key; path and
  project are in the git-ignored `Flood-Guard/.env` (`GOOGLE_APPLICATION_CREDENTIALS`,
  `EE_PROJECT`), read by `floodguard/data/gee.py::_setting`. Test: 7 Sentinel-1
  IW scenes over Tehri in Aug 2024, first 2024-08-06 00:44 UTC descending, mean
  VV −9.18 dB.
- Plan approved: **A** per-scene layover/shadow masks (Vollrath, Mullissa & Reiche
  2020, Remote Sensing 12(11):1867, doi 10.3390/rs12111867 — formulas checked
  against the authors' `javascript/slope_correction_module.js`; Small 2011 IEEE
  TGRS **49(8)**:3081-3093 — the reference project's "49(10)" is wrong). **B**
  blockage-lake check (new/lost open water around a river point, candidates
  REPORTED with measurements, never filtered by unvetted thresholds). **C**
  validation on real events. **D** Monitoring-page panel. NOT E (lake → scenario).
- Done in code: `floodguard/data/sar_geometry.py` (+ `tests/test_sar_geometry.py`,
  7 pass); `gee.py` reworked — per-scene masking inside `sentinel1_collection`,
  speckle filter in linear power (was in dB), `copernicus_dem()` keeps native
  projection, `COP_DEM = COPERNICUS/DEM/GLO30_2024_1` (old id deprecated),
  **bug fix** `permanent_water_mask()` now `unmask(0)` (before, every And() with
  "not permanent water" limited detection to ground that was water before — this
  affected the existing flood detector too), `water_threshold()` = Otsu within
  200 m of the JRC max_extent edge (Donchyts et al. 2016 idea; threshold moved
  only 0.4 dB for 100/200/400 m), fallback to whole AOI with a warning;
  `floodguard/data/blockage_lake.py::check_blockage_lake` (no `bestEffort` —
  it silently coarsened vectors, 92.8 → 9.7 ha).
- **South Lhonak test (27.9144306 N, 88.1835861 E, event 2023-10-04, radius 3 km,
  24-day windows)**: pre-event water within 1.5 km ≈ 157–165 ha with the edge
  threshold. ISRO's own page (isro.gov.in/Satellite_studies_South_Lhonak_Lake.html)
  says only "about 105 Hectares area has been drained out (28 September 2023
  image versus 04 October 2023)"; the "167.4 ha on 28 Sep" figure comes from news
  summaries — NOT verified at source, do not cite it as ISRO's.
  **Unsolved:** with a separate Otsu per window (−13.5 dB pre, −11.7 dB post) the
  check reports 134.9 ha lost AND 158.7 ha "new" water — the new water is an
  artefact (the drained, wet lake bed and wet snow stay radar-dark). The next
  experiment (interrupted by the user) was ONE common threshold for both windows
  (justified: both windows hold the same relative orbits, 12 days apart) and a
  per-scene water-area time series near the lake. Do not present any lost/new
  area as validated until this is resolved.
- Rishiganga 2021 lake: location not sourced (sources give 350 m long [CWC] /
  ~500×100 m / 0.44 km² — inconsistent); only a detectability check if a
  coordinate can be cited.
- Not started: D (API endpoint `/api/monitoring/blockage-lake` + panel), tests
  for `blockage_lake.py` pure helpers (`windows`, `candidate_from_feature`),
  opt-in live tests, docs (HANDOFF R3.11, CLAUDE.md). `tests/test_gee.py` skips
  its "unconfigured" tests now that this machine is configured.

## 3. Next steps, in order

1. **Tehri 60 m follow-up (laptop is free now):**
   ```bash
   ./.venv/Scripts/python -m floodguard.cli preprocess --scenario data/scenarios/tehri_bhagirathi.yaml --resolution 60
   ./.venv/Scripts/python -m floodguard.cli life-loss --runs "lib_tehri*__r60" --warning-min -60 --warning-min 0 --warning-min 60
   ```
   `preprocess` at 60 m is required: without it a 60 m run has no cross-sections,
   no channel gauges and no sensitivity (by design).
2. **When the Hirakud batch finishes** (server), then sync round-3c code to the
   server (section 4) if you want, and:
   ```bash
   cd ~/Flood-Guard && source ~/miniconda3/etc/profile.d/conda.sh && conda activate floodguard
   python -m floodguard.cli preprocess --scenario data/scenarios/hirakud_mahanadi.yaml --resolution 60
   python -m floodguard.cli life-loss --runs "lib_hirakud*__r60" --warning-min -60 --warning-min 0 --warning-min 60
   python -m floodguard.cli pack export --runs "lib_hirakud*__r60" --out data/library/hirakud_60m.fgpack
   # laptop:
   scp -i ~/.ssh/floodguard_server user7@172.16.121.24:Flood-Guard/data/library/hirakud_60m.fgpack data/library/
   ./.venv/Scripts/python -m floodguard.cli pack import data/library/hirakud_60m.fgpack
   ./.venv/Scripts/python -m floodguard.cli pack export --runs "lib_*" --out data/library/floodguard_demo_presets.fgpack
   ```
   Re-verify the new pack by importing into an empty data dir. Put the measured
   60 m times into HANDOFF (R3.9) and DEMO_SCRIPT if used.
3. Full solve of `data/scenarios/examples/hypothetical_blockage_bhagirathi.yaml`
   at 120 m with `blockage.burn_into_dem` true vs false; report the measured
   difference (HANDOFF R3.10 has the preprocess-only check).
4. Restart the dashboard on :8000 (round-3c code). The detached worker means a
   restart no longer kills a running job.
5. **Earth Engine** — only if the user says to continue (they paused it; ask
   whether to finish it or leave it as work in progress). Resume at the
   "common threshold" experiment above, then D, tests, docs.
6. Re-run backend + frontend suites, `npm run build`, `scripts/check_citations.py`;
   update HANDOFF / CLAUDE.md / this file with measured numbers only.
3. **Open decisions awaiting the user** (ask, do not start):
   - Tehri 12 h runs (the river at Rishikesh/Haridwar is still rising at 6 h).
   - Overtopping as a distinct failure mode (needs a cited basis + inflow flood).
4. **Known open issues**: SPH regression (above); CI never executed (needs a push);
   Tehri 120 m depths (Devprayag 149 m) unverified against an independent study;
   Docker never run.
5. Skipped on purpose (do not port without a verified source): Wahl (2004) bands,
   ₹ damage curves, Walder & O'Connor / Peng & Zhang, Delft3D without `dflowfm`,
   Earth Engine items. Not to port at all (TASKSTODO): CUDA, PySPH/DualSPHysics,
   Electron, ParaView/MATLAB/Cesium, .docx, Celery/Redis, FD2320 evacuation
   directives, Malpasset/Chamoli. The user offered credentials for anything that
   needs them; only Earth Engine was set up. Delft3D needs a `dflowfm` binary,
   OpenTopography an API key (optional), CI a push the user will do themselves.

## 4. Machines and access

- **Laptop**: Windows 11, i7-13650HX 14C/20T, 15.7 GB. Python venv at `.venv`
  (CPython 3.12.5). **Gotcha:** `python` on the Git Bash PATH is MSYS2 (no
  geospatial wheels) — always use `./.venv/Scripts/python`; to recreate the venv
  use `C:\Users\Ridwan umar\AppData\Local\Programs\Python\Python312\python.exe`.
  Node 24; `cd frontend && npm test | npm run build | npx tsc --noEmit`.
- **Server**: `user7@172.16.121.24` (RHEL, i9-12900K 16C/24T, 62 GB), key login
  `ssh -i ~/.ssh/floodguard_server -o BatchMode=yes user7@172.16.121.24`.
  Code copy at `~/Flood-Guard`, conda env `floodguard` (Python 3.12). Sync code
  by tarball (not git):
  ```bash
  cd /e/SIH_FLOOG_GUARD && tar --exclude='__pycache__' --exclude='*.egg-info' \
    -czf /c/Users/RIDWAN~1/AppData/Local/Temp/fg_backend.tgz Flood-Guard/backend Flood-Guard/Makefile Flood-Guard/data/scenarios
  scp -i ~/.ssh/floodguard_server /c/Users/RIDWAN~1/AppData/Local/Temp/fg_backend.tgz user7@172.16.121.24:
  ssh ... 'tar -xzf ~/fg_backend.tgz -C ~'
  ```
  Start long jobs as `(PYTHONUNBUFFERED=1 nohup python -m floodguard.cli ... >> log 2>&1 < /dev/null &)`.
- **Tool gotchas seen this session**: GNU tar treats `C:/...` as a remote host
  (use `/c/...`); `pkill -f "<pattern>"` over ssh kills the ssh command itself
  (use `ps ... | grep "[p]ython -m floodguard"` and kill by pid); bash heredocs
  mangle backslashes in Python code (write patch scripts with the Write tool);
  the Bash tool times out at 10 min — detach long jobs (PowerShell
  `Start-Process` on the laptop, `nohup` on the server).

## 5. Where things are

| Topic | Path |
|---|---|
| Preset library, keys (`__r60` suffix for non-120 m), index | `backend/floodguard/library.py`, `data/library/index.json` |
| CLI (`precompute`, `pack`, `life-loss`, `validate`, `preprocess`, `simulate`) | `backend/floodguard/cli.py` |
| Presets / registry API | `backend/app/api/presets.py` |
| Results API (summary, gauges, provenance, sensitivity, life-loss, wave_kmz, pdf) | `backend/app/api/results.py` |
| Solver (outflow limiter, positivity counters) | `backend/floodguard/engines/swe_fv.py`, `_swe_kernels.py` |
| Breach: routing, parameters, natural dam, sensitivity | `backend/floodguard/breach/` |
| Gauges, provenance, exports | `backend/floodguard/postprocess/` |
| Loss of life (Graham 1999 Table 7) | `backend/floodguard/impact/life_loss.py` |
| Packs | `backend/floodguard/packs.py` |
| Processed-data lookup (per resolution, pack-safe) | `backend/floodguard/processed.py` |
| Frontend panels | `frontend/src/components/{PresetPicker,RunModeBadge,GaugesPanel,ProvenancePanel,SensitivityPanel,RegistryPanel,LifeLossPanel,PlaybackSpeed}.tsx` |
| Runs superseded by the solver fixes (evidence only, never serve) | `data/runs/.superseded/`, `data/quarantine/` |
| Detached worker (job folders `data/jobs/<id>/`) | `backend/app/core/worker.py`, `backend/app/core/jobs.py` |
| Barrier burn for natural blockages | `backend/floodguard/preprocess/blockage.py` |
| Earth Engine (in progress) | `backend/floodguard/data/gee.py`, `sar_geometry.py`, `blockage_lake.py`, `backend/app/api/monitoring.py` |
| Hypothetical blockage example (not a preset) | `data/scenarios/examples/hypothetical_blockage_bhagirathi.yaml` |
| Reference PDFs used for verification (Graham 1999, Costa 1985) | re-download from damfailures.org / pubs.usgs.gov if needed |

Before finishing any session: run the backend and frontend suites, `npm run build`,
`python scripts/check_citations.py`, and update HANDOFF / CLAUDE.md / this file
with **measured** numbers only.
