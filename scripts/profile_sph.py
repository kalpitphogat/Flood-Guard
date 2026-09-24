"""Profile FloodGuard-SPH on a real scenario and print particle diagnostics.

    python scripts/profile_sph.py --scenario tehri_bhagirathi --seconds 400
    python scripts/profile_sph.py --scenario tehri_bhagirathi --seconds 400 --h-max-cells 1.0

Runs ONLY the SPH engine (no FV run, no exports) for a short simulated window
and reports what drives its cost: ms per step, the particle count, how many
particles sit at the smoothing-length clamp (the "spray" that makes neighbour
searches expensive), and how crowded the busiest grid cell is.

Needs `floodguard data --scenario ...` to have been run for the scenario.
Progress is printed unbuffered, so it is safe to redirect to a log file.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scenario", default="tehri_bhagirathi")
    ap.add_argument("--resolution", type=float, default=90.0)
    ap.add_argument("--seconds", type=float, default=400.0, help="simulated seconds")
    ap.add_argument("--target-particles", type=int)
    ap.add_argument("--h-max-cells", type=float)
    ap.add_argument("--max-runtime-minutes", type=float, default=30.0)
    args = ap.parse_args()

    from floodguard.breach import parameters as bp
    from floodguard.breach import routing
    from floodguard.engines import sph_swe
    from floodguard.pipeline import _build_engine_input
    from floodguard.preprocess.pipeline import run_preprocess
    from floodguard.scenario import Scenario

    data = REPO / "data"
    sc = Scenario.from_yaml(data / "scenarios" / f"{args.scenario}.yaml")
    sc.domain.resolution_m = args.resolution
    pre = run_preprocess(sc, data, write_rasters=False)
    used, _, _ = bp.resolve(sc)
    hyd = routing.route(
        pre.reservoir.curve, used,
        initial_level_m=sc.initial_level_m,
        crest_elevation_m=sc.dam.crest_elevation_m or sc.initial_level_m,
        scenario_type=sc.scenario_type, shape=sc.breach.shape, growth=sc.breach.growth,
        duration_s=sc.solver.duration_hours * 3600.0, inflow_m3s=sc.reservoir.inflow_m3s,
    )
    spec, _ = _build_engine_input(sc, pre, hyd, breach_width_m=used.width_m)
    spec.duration_s = args.seconds
    spec.output_interval_s = max(args.seconds / 20.0, 10.0)

    cfg = sph_swe.SPHSettings.from_scenario(sc.solver.sph)
    if args.target_particles:
        cfg.target_particles = args.target_particles
    if args.h_max_cells:
        cfg.h_max_cells = args.h_max_cells
    cfg.max_runtime_s = args.max_runtime_minutes * 60.0
    print(f"settings: {cfg.to_dict()}", flush=True)
    print(f"source {spec.source_rc}, direction {spec.source_direction}, "
          f"{len(spec.source_cells)} face cells, grid {spec.shape}", flush=True)

    captured: dict = {}
    original = sph_swe.SPHSolver.advance

    def advance(self, dt):
        captured["solver"] = self
        return original(self, dt)

    sph_swe.SPHSolver.advance = advance
    t0 = time.perf_counter()
    res = sph_swe.SmoothedParticleSWE(cfg).run(
        spec, lambda **k: print(f"{time.perf_counter() - t0:8.1f}s  {k['message']}", flush=True)
    )

    solver = captured.get("solver")
    if solver is None:
        print("no particles were ever advanced", flush=True)
        return 1
    s, d, n = solver.s, solver.domain, solver.s.n
    speed = np.hypot(s.vx[:n], s.vy[:n])
    print("\n--- particle diagnostics at the end ---")
    print(f"particles {n:,}, steps {res.steps:,}, runtime {res.runtime_s:.1f}s")
    for name, arr in (("depth m", s.depth[:n]), ("hs m", s.hs[:n]), ("speed m/s", speed)):
        q = np.percentile(arr, [0, 10, 50, 90, 99, 100])
        print(f"{name:10s} p0/10/50/90/99/100: {np.round(q, 2)}")
    print(f"at hs clamp (spray): {np.mean(s.hs[:n] >= solver.h_max * 0.999):.1%}")
    print(f"depth < wet threshold: {np.mean(s.depth[:n] < spec.wet_threshold_m):.1%}")
    cells = (s.py[:n] / d.dx).astype(int) * d.cols + (s.px[:n] / d.dx).astype(int)
    _, counts = np.unique(cells, return_counts=True)
    print(f"occupied cells {counts.size:,}; particles per cell median {np.median(counts):.0f}, "
          f"max {counts.max()}")
    print(f"wet cells in max-depth raster: {(res.max_depth >= spec.wet_threshold_m).sum():,}")
    print(f"warnings: {res.warnings}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
