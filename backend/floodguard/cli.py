"""FloodGuard command line interface.

    floodguard engines
    floodguard data      --scenario data/scenarios/tehri_bhagirathi.yaml
    floodguard preprocess --scenario ...
    floodguard breach    --scenario ...
    floodguard validate  --out docs/validation
    floodguard simulate  --scenario ...
    floodguard precompute --scenario tehri_bhagirathi --scenario hirakud_mahanadi
    floodguard pack export --runs "lib_*" --out demo.fgpack
    floodguard pack import demo.fgpack

Every subcommand that is not yet implemented says so explicitly and exits
non-zero. It never prints a plausible-looking fake result.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = REPO_ROOT / "data"

_PHASE_OF: dict[str, tuple[str, str]] = {}


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _load_scenario(
    path: str | None,
    resolution_m: float | None = None,
    duration_hours: float | None = None,
):
    """Load a scenario, optionally overriding the compute resolution.

    Resolution is the single biggest lever on runtime AND on the answer. Cost
    scales roughly as 1/res^3 — 1/res^2 in cells and another 1/res in timesteps,
    since the CFL limit shrinks with the cell size. Going from 90 m to 30 m is
    about 27x the work. It is also not merely a quality knob: dam-break peak
    depths are genuinely resolution-sensitive, because a coarse cell averages
    the channel together with its banks and under-predicts the peak. That is
    why the spec insists it be exposed rather than hidden, and why every output
    records the resolution it was computed at.
    """
    from floodguard.scenario import Scenario

    if not path:
        raise CliError("--scenario is required for this command")
    scenario = _read_scenario(Scenario, _resolve_scenario_path(path))
    if resolution_m or duration_hours:
        scenario = scenario.model_copy(deep=True)
    if resolution_m:
        scenario.domain.resolution_m = resolution_m
    if duration_hours:
        scenario.solver.duration_hours = duration_hours
    return scenario


# --- commands ---------------------------------------------------------------------


def cmd_engines(_args) -> int:
    """Print the truthful engine availability table for this machine."""
    from floodguard.engines.availability import probe_all

    rows = probe_all()
    width = max(len(r.id) for r in rows)
    print(f"{'ENGINE'.ljust(width)}  {'AVAILABLE':<10} DISPLAY NAME / DETAIL")
    print("-" * 100)
    for r in rows:
        mark = "yes" if r.available else "NO"
        version = f" v{r.version}" if r.version else ""
        print(f"{r.id.ljust(width)}  {mark:<10} {r.display_name}{version}")
        print(f"{' ' * width}  {'':<10} {r.detail}")
        if r.substitute_id:
            print(f"{' ' * width}  {'':<10} -> would substitute: {r.substitute_id}")
        print()
    return 0


def cmd_data(args) -> int:
    """Phase 1: fetch and cache every input layer for a scenario."""
    from floodguard.data.acquire import acquire, derive_aoi, layer_table

    scenario = _load_scenario(args.scenario, args.resolution)
    data_dir = Path(args.data_dir or DEFAULT_DATA_DIR)

    aoi = derive_aoi(scenario)
    print(f"Scenario : {scenario.id} — {scenario.name}")
    print(f"Dam      : {scenario.dam.name} ({scenario.dam.lat:.4f}N, {scenario.dam.lon:.4f}E)")
    print(f"River    : {scenario.dam.river}")
    print(f"AOI      : W{aoi[0]:.3f} S{aoi[1]:.3f} E{aoi[2]:.3f} N{aoi[3]:.3f}")
    print(f"Target   : {scenario.utm_crs} @ {scenario.domain.resolution_m:.0f} m")
    print()

    result = acquire(
        scenario,
        data_dir,
        skip_population=args.skip_population,
        skip_osm=args.skip_osm,
        skip_landcover=getattr(args, "skip_landcover", False),
        mosaic=not args.no_mosaic,
    )

    print()
    print(layer_table(data_dir))

    if result.skipped:
        print("\nNOT FETCHED — these will be reported as 'not computed', never as zero:")
        for name, why in result.skipped.items():
            print(f"  {name}: {why}")

    if result.dem:
        print(f"\nDEM source used: {result.dem.source}")
        for failure in result.dem.failures:
            print(f"  tried first, failed: {failure}")
    if result.dem_mosaic:
        print(f"DEM mosaic     : {result.dem_mosaic}")
    if result.population:
        print(f"\nPopulation assumption carried into every report:\n  {result.population.assumption_note()}")

    return 0


def cmd_verify(args) -> int:
    """Re-hash every cached input and report any that drifted."""
    from floodguard.data.acquire import verify

    data_dir = Path(args.data_dir or DEFAULT_DATA_DIR)
    problems = verify(data_dir)
    if not problems:
        print("MANIFEST verified: every recorded file is present and hashes match.")
        return 0
    print("MANIFEST verification FAILED:", file=sys.stderr)
    for p in problems:
        print(f"  {p}", file=sys.stderr)
    return 1


def cmd_preprocess(args) -> int:
    """Phase 2: condition the DEM, trace the corridor, derive the reservoir curve."""
    from floodguard.preprocess.pipeline import run_preprocess

    scenario = _load_scenario(args.scenario, args.resolution)
    data_dir = Path(args.data_dir or DEFAULT_DATA_DIR)
    result = run_preprocess(scenario, data_dir)
    print(result.summary())
    return 0


def cmd_breach(args) -> int:
    """Phase 3: breach parameters, outflow hydrograph, or historical validation."""
    import json

    from floodguard.breach import parameters as bp
    from floodguard.breach import routing
    from floodguard.breach import validation as bv

    if args.validate:
        print(bv.report())
        return 0

    scenario = _load_scenario(args.scenario)
    data_dir = Path(args.data_dir or DEFAULT_DATA_DIR)

    used, predictions, stats = bp.resolve(scenario)

    print(f"Breach parameter predictions for {scenario.dam.name}")
    print(f"  head over invert {scenario.water_head_m:.1f} m, "
          f"storage {scenario.dam.gross_storage_mcm:,.0f} MCM, "
          f"type {scenario.dam.dam_type.value}\n")
    print(f"  {'MODEL':<38} {'WIDTH m':>10} {'t_f min':>10} {'SLOPE':>7}  APPLIES")
    print("  " + "-" * 78)
    for p in predictions:
        print(f"  {p.model:<38} {p.width_m:>10.0f} {p.formation_time_min:>10.1f} "
              f"{p.side_slope:>7.1f}  {'yes' if p.applicable else 'NO'}")
    print()
    print(f"  Spread: width x{stats['width_m']['spread_ratio']}, "
          f"formation time x{stats['formation_time_min']['spread_ratio']}")
    print(f"  {stats['interpretation']}")
    print()
    print(f"  USING: {used.model} — width {used.width_m:.0f} m, "
          f"depth {used.depth_m:.0f} m, t_f {used.formation_time_min:.1f} min")
    for c in used.caveats:
        print(f"    - {c}")

    # Routing needs the reservoir curve from Phase 2.
    from floodguard import processed

    pre_path = (
        processed.find_preprocess_json(data_dir, scenario.id, scenario.domain.resolution_m)
        or processed.inputs_dir(data_dir, scenario.id, scenario.domain.resolution_m)
        / processed.PREPROCESS_NAME
    )
    if not pre_path.exists():
        print(f"\nNo preprocess.json at {pre_path}; run `floodguard preprocess` to route "
              f"the hydrograph.", file=sys.stderr)
        return 0

    from floodguard.preprocess.reservoir import ElevationAreaCapacity
    import numpy as np

    pre = json.loads(pre_path.read_text(encoding="utf-8"))
    cd = pre["reservoir"]["curve"]
    curve = ElevationAreaCapacity(
        levels_m=np.array(cd["levels_m"]),
        areas_m2=np.array(cd["areas_km2"]) * 1e6,
        volumes_m3=np.array(cd["volumes_mcm"]) * 1e6,
        cell_area_m2=cd["cell_area_m2"],
        dam_elevation_m=cd["dam_elevation_m"],
        method=cd["method"],
    )

    crest = scenario.dam.crest_elevation_m or scenario.initial_level_m
    hydrograph = routing.route(
        curve,
        used,
        initial_level_m=scenario.initial_level_m,
        crest_elevation_m=crest,
        scenario_type=scenario.scenario_type,
        shape=scenario.breach.shape,
        growth=scenario.breach.growth,
        duration_s=scenario.solver.duration_hours * 3600.0,
        inflow_m3s=scenario.reservoir.inflow_m3s,
    )

    print()
    print(hydrograph.summary())

    out = pre_path.parent / "hydrograph.json"
    out.write_text(json.dumps(hydrograph.to_dict(), indent=2), encoding="utf-8")
    print(f"\nWritten: {out}")
    return 0


def cmd_simulate(args) -> int:
    """Phases 2-5: the full headless pipeline for one scenario."""
    from floodguard.pipeline import simulate

    scenario = _load_scenario(args.scenario, args.resolution, args.duration)
    data_dir = Path(args.data_dir or DEFAULT_DATA_DIR)

    print(f"Resolution: {scenario.domain.resolution_m:.0f} m "
          f"(cost scales as ~1/res^3; every output records this value)")

    last = {"phase": None}

    def progress(*, fraction, phase, message, **extra):
        # flush: when stdout is redirected to a log file on a server, block
        # buffering would hide a long run's progress until it finished.
        if phase != last["phase"]:
            print(f"[{fraction * 100:5.1f}%] {phase}", flush=True)
            last["phase"] = phase
        if extra.get("step") or phase == "done":
            print(f"          {message}", flush=True)

    result = simulate(
        scenario,
        data_dir,
        progress=progress,
        engines=_check_engines([e.strip() for e in args.engines.split(",") if e.strip()])
        if args.engines else None,
        export=not args.no_export,
    )
    print()
    print(result.summary())
    return 0


def _resolve_scenario_path(ref: str) -> Path:
    """`tehri_bhagirathi` or a path to a YAML."""
    path = Path(ref)
    if path.suffix in (".yaml", ".yml") and path.exists():
        return path
    if path.suffix in (".yaml", ".yml"):
        raise CliError(f"scenario file not found: {path}")
    candidate = DEFAULT_DATA_DIR / "scenarios" / f"{ref}.yaml"
    if candidate.exists():
        return candidate
    raise CliError(f"scenario {ref!r} not found (looked for {path} and {candidate})")


def _read_scenario(scenario_cls, path: Path):
    """Validate a scenario file, turning a schema error into one readable message."""
    import yaml
    from pydantic import ValidationError

    try:
        return scenario_cls.from_yaml(path)
    except yaml.YAMLError as exc:
        raise CliError(f"{path} is not valid YAML: {exc}") from None
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(x) for x in e['loc']) or '(file)'}: {e['msg']}" for e in exc.errors()
        )
        raise CliError(f"{path} is not a valid scenario — {problems}") from None


def _fmt_dur(seconds: float) -> str:
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h{m:02d}m{s:02d}s" if h else f"{m}m{s:02d}s"


def cmd_precompute(args) -> int:
    """Compute the preset library that the dashboard serves instantly.

    Resumable: a preset whose run folder already holds result.json is skipped
    (unless --force). One failed preset is recorded as failed and the batch
    moves on. Every wall time printed here is measured, not estimated; the ETA
    uses only presets measured in THIS batch for the same dam.
    """
    import time

    from floodguard import library as lib
    from floodguard.scenario import Scenario

    data_dir = Path(args.data_dir or DEFAULT_DATA_DIR)
    types = set(args.type) if args.type else set(lib.MODELLED_TYPES)
    for t in sorted(types - set(lib.MODELLED_TYPES)):
        print(f"SKIPPING failure type {t!r}: {lib.not_precomputed_reason(t)}", flush=True)
    types &= set(lib.MODELLED_TYPES)

    bases = [_read_scenario(Scenario, _resolve_scenario_path(r)) for r in args.scenario]
    resolution = float(args.resolution or lib.LIBRARY_RESOLUTION_M)
    if resolution not in lib.LIBRARY_RESOLUTIONS:
        raise CliError(
            f"--resolution {resolution:g}: the preset library holds "
            f"{', '.join(f'{r:g} m' for r in lib.LIBRARY_RESOLUTIONS)} only, so a preset at any "
            f"other resolution would never be offered. Use `simulate --resolution` for a one-off."
        )
    plan = [
        (base, preset)
        for base in bases
        for preset in lib.iter_presets(base, resolution_m=resolution)
        if preset.scenario_type in types
    ]
    if args.limit:
        plan = plan[: args.limit]

    pending = [(b, p) for b, p in plan if args.force or not lib.is_done(data_dir, p.key)]
    pending_keys = {p.key for _b, p in pending}
    print(f"Preset library -> {data_dir / 'runs'} (index {lib.index_path(data_dir)})", flush=True)
    print(f"{len(plan)} preset(s) planned, {len(plan) - len(pending)} already done, "
          f"{len(pending)} to run at {resolution:g} m with "
          f"{', '.join(lib.LIBRARY_ENGINES)}", flush=True)
    for base, p in plan:
        state = "run " if p.key in pending_keys else "done"
        print(f"  [{state}] {p.key:<52} level {p.level_m:8.2f} m  "
              f"duration {base.solver.duration_hours:g} h", flush=True)

    if args.dry_run:
        print("\nDry run: nothing computed. No time estimate is printed: the only measured "
              "figure (Tehri at 90 m) does not transfer reliably to 120 m or to Hirakud. "
              "The batch prints measured times and an ETA as it goes.", flush=True)
        return 0

    from floodguard.pipeline import ensure_inputs, simulate

    measured: dict[str, list[float]] = {}
    acquired: set[str] = set()
    failures = 0
    batch_start = time.perf_counter()

    for n, (base, preset) in enumerate(pending, start=1):
        scenario = lib.build_preset_scenario(
            base, preset.scenario_type, preset.level, preset.resolution_m
        )
        if base.id not in acquired:
            t0 = time.perf_counter()
            print(f"\n[inputs] {base.id}: checking the {resolution:g} m inputs",
                  flush=True)
            for note in ensure_inputs(scenario, data_dir):
                print(f"[inputs] {note}", flush=True)
            print(f"[inputs] {base.id}: ready in {_fmt_dur(time.perf_counter() - t0)} "
                  f"(not counted in run times)", flush=True)
            acquired.add(base.id)

        print(f"\n=== [{n}/{len(pending)}] {preset.key} (level {preset.level_m:.2f} m) ===",
              flush=True)
        last = {"phase": None}

        def progress(*, fraction, phase, message, **extra):
            if phase != last["phase"]:
                print(f"  [{fraction * 100:5.1f}%] {phase}", flush=True)
                last["phase"] = phase
            step = extra.get("step")
            if step and step % 500 == 0:
                print(f"            {message}", flush=True)

        old = data_dir / "runs" / preset.run_id
        if args.force and old.exists():
            # Moved aside, not deleted, so no derived file from the old run can
            # sit next to the new result.json.
            superseded = data_dir / "runs" / ".superseded" / (
                f"{preset.run_id}__{time.strftime('%Y%m%dT%H%M%S')}"
            )
            superseded.parent.mkdir(parents=True, exist_ok=True)
            old.rename(superseded)
            print(f"  previous run moved to {superseded}", flush=True)

        t0 = time.perf_counter()
        status, error, completed = "failed", None, None
        try:
            result = simulate(
                scenario, data_dir, progress=progress, run_id=preset.run_id,
                engines=list(lib.LIBRARY_ENGINES), run_meta=lib.run_meta_for(preset),
            )
            if lib.is_done(data_dir, preset.key):
                status = "succeeded"
                completed = json.loads(
                    lib.result_path(data_dir, preset.key).read_text(encoding="utf-8")
                ).get("completed_utc")
            else:
                error = "no engine produced a result: " + "; ".join(result.warnings[-3:])
        except Exception as exc:  # noqa: BLE001 - one preset must not kill the batch
            logging.getLogger(__name__).exception("preset %s failed", preset.key)
            error = f"{type(exc).__name__}: {exc}"
        wall = time.perf_counter() - t0

        lib.record(data_dir, preset.key, lib.entry_for(
            preset, duration_hours=scenario.solver.duration_hours,
            completed_utc=completed, wall_seconds=round(wall, 1),
            status=status, error=error,
        ))
        if status == "succeeded":
            measured.setdefault(base.id, []).append(wall)
            print(f"  DONE {preset.key}: measured wall time {_fmt_dur(wall)} ({wall:.0f} s)",
                  flush=True)
        else:
            failures += 1
            print(f"  FAILED {preset.key} after {_fmt_dur(wall)}: {error}", flush=True)

        # ETA from measurements only; a dam with no measured run yet is "unmeasured".
        rest = pending[n:]
        known, unknown = 0.0, set()
        for b, _p in rest:
            if measured.get(b.id):
                known += sum(measured[b.id]) / len(measured[b.id])
            else:
                unknown.add(b.id)
        eta = _fmt_dur(known) if not unknown else (
            f">= {_fmt_dur(known)} + unmeasured ({', '.join(sorted(unknown))})"
        )
        print(f"  elapsed {_fmt_dur(time.perf_counter() - batch_start)}, "
              f"{len(rest)} left, ETA {eta}", flush=True)

    print(f"\nBatch finished in {_fmt_dur(time.perf_counter() - batch_start)}: "
          f"{len(pending) - failures} succeeded, {failures} failed.", flush=True)
    return 1 if failures else 0


def cmd_pack(args) -> int:
    """Move finished runs between machines as one checksummed file."""
    from floodguard import packs

    data_dir = Path(args.data_dir or DEFAULT_DATA_DIR)
    try:
        if args.pack_command == "export":
            run_ids = packs.select_runs(data_dir, args.runs)
            print(f"Packing {len(run_ids)} run(s) from {data_dir}:", flush=True)
            for r in run_ids:
                print(f"  {r}", flush=True)
            summary = packs.export_pack(
                data_dir, run_ids, Path(args.out), name=args.name,
                include_processed=not args.no_processed,
            )
            print(f"Wrote {summary.path} — {summary.files} files, "
                  f"{summary.bytes / 1e6:.1f} MB")
            print(f"On the other machine: python -m floodguard.cli pack import {summary.path.name}")
        else:
            summary = packs.import_pack(data_dir, Path(args.pack))
            print(f"Imported {summary.path.name} ({summary.name}) into {data_dir}")
            print(f"  runs            : {', '.join(summary.run_ids) or '—'}")
            print(f"  files copied    : {summary.copied}")
            print(f"  already present : {summary.already_present} (identical, skipped)")
            print(f"  presets added   : {len(summary.index_added)}")
            if summary.index_kept:
                print(f"  presets kept as they were on this machine: {', '.join(summary.index_kept)}")
    except packs.PackError as exc:
        print(f"pack {args.pack_command} failed: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_life_loss(args) -> int:
    """Graham (1999) loss-of-life estimate for finished runs, cached beside each run.

    The API serves the cached file; computing it needs the population raster,
    which a demo laptop may not have, so this is run where the data is.
    """
    from floodguard import packs
    from floodguard.impact import life_loss as ll

    data_dir = Path(args.data_dir or DEFAULT_DATA_DIR)
    raw = data_dir / "raw" / "population" / "worldpop"
    population = next(iter(sorted(raw.glob("*.tif"))), None) if raw.exists() else None
    run_ids = packs.select_runs(data_dir, args.runs)
    if not run_ids:
        print("no finished runs matched", file=sys.stderr)
        return 1
    for run_id in run_ids:
        for w in args.warning_min or [0.0]:
            result = ll.estimate_for_run(
                data_dir / "runs" / run_id, population,
                warning_issued_min=w, understanding=args.understanding,
            )
            result["run_id"] = run_id
            if not result.get("computed"):
                print(f"{run_id}: not computed — {result.get('reason') or result.get('notes')}")
                continue
            out = data_dir / "runs" / run_id / f"life_loss_w{w:g}_{args.understanding}.json"
            out.write_text(json.dumps(result, indent=2), encoding="utf-8")
            lo, hi = result["range"]
            print(f"{run_id}: warning at {w:g} min, {args.understanding}: PAR "
                  f"{result['population_at_risk']:,}, estimate {result['estimate']:,} "
                  f"(range {lo:,}-{hi:,}) -> {out.name}")
    return 0


def cmd_report(args) -> int:
    """Phase 10: render the PDF report for a completed run."""
    from floodguard.report import build_report, write_map_previews

    data_dir = Path(args.data_dir or DEFAULT_DATA_DIR)
    runs = data_dir / "runs"
    run_dir = Path(args.run) if args.run else None

    if run_dir is None:
        candidates = sorted(
            (d for d in runs.glob("*") if (d / "result.json").exists()),
            key=lambda d: d.stat().st_mtime,
        )
        if not candidates:
            print(
                f"No completed run found under {runs}. Run `floodguard simulate` first.",
                file=sys.stderr,
            )
            return 2
        run_dir = candidates[-1]
    elif not run_dir.is_absolute():
        run_dir = runs / run_dir

    previews = write_map_previews(run_dir)
    for p in previews:
        print(f"  rendered {p.name}")

    out = build_report(run_dir)
    print(f"Report: {out} ({out.stat().st_size / 1024:.0f} KB)")
    return 0


def cmd_impact(args) -> int:
    """Phase 6: print the exposure analysis for a completed run."""
    import json

    data_dir = Path(args.data_dir or DEFAULT_DATA_DIR)
    runs = data_dir / "runs"
    run_dir = Path(args.run) if args.run else None
    if run_dir is None:
        candidates = sorted(
            (d for d in runs.glob("*") if (d / "impact.json").exists()),
            key=lambda d: d.stat().st_mtime,
        )
        if not candidates:
            print(f"No run with impact.json under {runs}.", file=sys.stderr)
            return 2
        run_dir = candidates[-1]
    elif not run_dir.is_absolute():
        run_dir = runs / run_dir

    path = run_dir / "impact.json"
    if not path.exists():
        print(f"{path} does not exist.", file=sys.stderr)
        return 2

    data = json.loads(path.read_text(encoding="utf-8"))
    print(f"Exposure within the inundated area ({run_dir.name})")
    for m in data["metrics"].values():
        unit = f" {m['unit']}" if m["computed"] and m["unit"] else ""
        print(f"  {m['label']:<26} {m['display']}{unit}")
        if not m["computed"]:
            print(f"  {'':<26} (not computed: {m['reason']})")
    for w in data.get("warnings", []):
        print(f"\n  WARNING: {w}")
    return 0


def cmd_demo(args) -> int:
    """Phase 10: preflight and start the full stack on precomputed results."""
    from floodguard.demo import run_demo

    return run_demo(
        Path(args.data_dir or DEFAULT_DATA_DIR),
        api_port=args.api_port,
        web_port=args.web_port,
        open_browser=not args.no_browser,
        check_only=args.check,
    )


def cmd_validate(args) -> int:
    """Phase 4.5: analytical and benchmark verification of the solver."""
    from floodguard.validation.run import run_validation

    out = Path(args.out or (REPO_ROOT / "docs" / "validation"))
    return run_validation(out, quick=args.quick)


def _not_yet(name: str) -> int:
    phase, module = _PHASE_OF[name]
    print(
        f"`floodguard {name}` is not implemented yet.\n"
        f"It arrives in {phase} ({module}). See SPEC.md section 15 for the execution order.",
        file=sys.stderr,
    )
    return 2


# --- argument validation -----------------------------------------------------------
#
# Bad input fails at the command line with one sentence naming the flag, never
# as a traceback from deep inside the solver half an hour later.


class CliError(Exception):
    """A user-input error: printed as one line, exit code 2, no traceback."""


def _positive_float(text: str) -> float:
    import math

    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number") from None
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError(f"must be a positive number, got {text!r}")
    return value


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number") from None
    if value <= 0:
        raise argparse.ArgumentTypeError(f"must be at least 1, got {text!r}")
    return value


def _port(text: str) -> int:
    value = _positive_int(text)
    if value > 65535:
        raise argparse.ArgumentTypeError(f"a TCP port is 1-65535, got {text!r}")
    return value


def _warning_minutes(text: str) -> float:
    import math

    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number of minutes") from None
    if not math.isfinite(value) or abs(value) > 24 * 60:
        raise argparse.ArgumentTypeError(
            f"warning time must be within +/-1440 minutes of the breach start, got {text!r}"
        )
    return value


def _data_dir_arg(text: str) -> str:
    if Path(text).exists() and not Path(text).is_dir():
        raise argparse.ArgumentTypeError(f"--data-dir {text} exists and is not a directory")
    return text


def _check_engines(ids: list[str]) -> list[str]:
    from floodguard.engines.availability import probe_all

    known = [st.id for st in probe_all()]
    bad = [e for e in ids if e not in known]
    if bad:
        raise CliError(f"unknown engine id(s) {', '.join(bad)}; known: {', '.join(known)}")
    return ids


# --- parser -----------------------------------------------------------------------


#: Failure types `precompute --type` accepts (listed ones; unmodelled are skipped with a reason).
_PRESET_TYPE_CHOICES = (
    "complete_dam_break", "partial_breach", "overtopping",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="floodguard", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("engines", help="show which hydrodynamic engines are runnable here")

    p_data = sub.add_parser("data", help="[Phase 1] fetch and cache all input layers")
    p_data.add_argument("--scenario", required=True)
    p_data.add_argument("--data-dir", type=_data_dir_arg)
    p_data.add_argument(
        "--resolution", type=_positive_float,
        help="compute grid resolution in metres, overriding the scenario",
    )
    p_data.add_argument("--skip-population", action="store_true")
    p_data.add_argument("--skip-osm", action="store_true")
    p_data.add_argument(
        "--skip-landcover", action="store_true",
        help="do not fetch ESA WorldCover; Manning's n will be uniform and labelled so",
    )
    p_data.add_argument("--no-mosaic", action="store_true")

    p_verify = sub.add_parser("verify", help="re-hash every cached input file")
    p_verify.add_argument("--data-dir", type=_data_dir_arg)

    p_pre = sub.add_parser("preprocess", help="[Phase 2] DEM conditioning, corridor, reservoir")
    p_pre.add_argument("--scenario", required=True)
    p_pre.add_argument("--data-dir", type=_data_dir_arg)
    p_pre.add_argument(
        "--resolution", type=_positive_float,
        help="compute grid resolution in metres, overriding the scenario",
    )

    p_breach = sub.add_parser("breach", help="[Phase 3] breach parameters + outflow hydrograph")
    p_breach.add_argument("--scenario")
    p_breach.add_argument("--data-dir", type=_data_dir_arg)
    p_breach.add_argument(
        "--validate", action="store_true",
        help="score the breach models against Teton 1976 and Banqiao 1975",
    )

    p_sim = sub.add_parser("simulate", help="[Phase 2-5] full headless pipeline")
    p_sim.add_argument("--scenario", required=True)
    p_sim.add_argument("--data-dir", type=_data_dir_arg)
    p_sim.add_argument(
        "--resolution", type=_positive_float,
        help="compute grid resolution in metres, overriding the scenario",
    )
    p_sim.add_argument(
        "--duration", type=_positive_float,
        help="simulated duration in hours, overriding the scenario"
    )
    p_sim.add_argument("--engines", help="comma-separated engine ids, e.g. swe_fv,delft3d")
    p_sim.add_argument("--no-export", action="store_true")

    p_lib = sub.add_parser(
        "precompute", help="compute the preset library the dashboard serves instantly"
    )
    p_lib.add_argument(
        "--scenario", action="append", required=True,
        help="scenario id (data/scenarios/<id>.yaml) or YAML path; repeatable",
    )
    p_lib.add_argument("--data-dir", type=_data_dir_arg)
    p_lib.add_argument(
        "--type", action="append", choices=list(_PRESET_TYPE_CHOICES),
        help="restrict to these failure types (repeatable); default: every modelled type",
    )
    p_lib.add_argument(
        "--resolution", type=_positive_float,
        help="preset grid resolution in metres (default 120; keys at other resolutions get a suffix)",
    )
    p_lib.add_argument("--limit", type=_positive_int, help="run at most N presets")
    p_lib.add_argument("--dry-run", action="store_true", help="print the plan only")
    p_lib.add_argument("--force", action="store_true", help="recompute finished presets")

    p_pack = sub.add_parser("pack", help="export / import finished runs as a .fgpack file")
    pack_sub = p_pack.add_subparsers(dest="pack_command", required=True)
    p_pexp = pack_sub.add_parser("export", help="write a .fgpack from finished runs")
    p_pexp.add_argument(
        "--runs", action="append", required=True,
        help='run id or glob, e.g. "lib_*"; repeatable',
    )
    p_pexp.add_argument("--out", required=True)
    p_pexp.add_argument("--name")
    p_pexp.add_argument("--data-dir", type=_data_dir_arg)
    p_pexp.add_argument(
        "--no-processed", action="store_true",
        help="leave out processed/<scenario>/preprocess.json (reservoir curve, cross-sections)",
    )
    p_pimp = pack_sub.add_parser("import", help="verify a .fgpack, then copy it in")
    p_pimp.add_argument("pack")
    p_pimp.add_argument("--data-dir", type=_data_dir_arg)

    p_ll = sub.add_parser(
        "life-loss", help="Graham (1999) loss-of-life estimate for finished runs"
    )
    p_ll.add_argument("--runs", action="append", required=True, help='run id or glob; repeatable')
    p_ll.add_argument(
        "--warning-min", action="append", type=_warning_minutes,
        help="minutes after breach start when a warning is issued (repeatable; default 0)",
    )
    p_ll.add_argument("--understanding", choices=["vague", "precise"], default="vague")
    p_ll.add_argument("--data-dir", type=_data_dir_arg)

    p_report = sub.add_parser("report", help="[Phase 10] render the PDF report for a run")
    p_report.add_argument("--run", help="run id or directory; defaults to the most recent")
    p_report.add_argument("--data-dir", type=_data_dir_arg)

    p_impact = sub.add_parser("impact", help="[Phase 6] print the exposure analysis")
    p_impact.add_argument("--run")
    p_impact.add_argument("--data-dir", type=_data_dir_arg)

    p_demo = sub.add_parser("demo", help="[Phase 10] preflight and start the full stack")
    p_demo.add_argument("--data-dir", type=_data_dir_arg)
    p_demo.add_argument("--api-port", type=_port, default=8000)
    p_demo.add_argument("--web-port", type=_port, default=5173)
    p_demo.add_argument("--no-browser", action="store_true")
    p_demo.add_argument(
        "--check", action="store_true", help="run the preflight only and exit"
    )

    p_val = sub.add_parser("validate", help="[Phase 4.5] Ritter/Stoker/lake-at-rest/mass balance")
    p_val.add_argument("--out")
    p_val.add_argument("--quick", action="store_true", help="coarser grids, for a fast check")

    for name, (phase, _module) in _PHASE_OF.items():
        p = sub.add_parser(name, help=f"[{phase}] not implemented yet")
        p.add_argument("--scenario")
        p.add_argument("--out")
        p.add_argument("--data-dir", type=_data_dir_arg)

    return parser


DISPATCH = {
    "engines": cmd_engines,
    "data": cmd_data,
    "verify": cmd_verify,
    "preprocess": cmd_preprocess,
    "validate": cmd_validate,
    "breach": cmd_breach,
    "simulate": cmd_simulate,
    "precompute": cmd_precompute,
    "pack": cmd_pack,
    "life-loss": cmd_life_loss,
    "report": cmd_report,
    "impact": cmd_impact,
    "demo": cmd_demo,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _setup_logging(args.verbose)
    handler = DISPATCH.get(args.command)
    if not handler:
        return _not_yet(args.command)
    try:
        return handler(args)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except CliError as exc:
        print(f"floodguard {args.command}: error: {exc}", file=sys.stderr)
        return 2
    except (FileNotFoundError, ValueError) as exc:
        # Raised by the pipeline for bad inputs (missing DEM, a physically
        # impossible scenario). With --verbose the traceback is kept.
        if args.verbose:
            raise
        print(f"floodguard {args.command}: error: {exc}", file=sys.stderr)
        print("  (run with -v for the full traceback)", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
