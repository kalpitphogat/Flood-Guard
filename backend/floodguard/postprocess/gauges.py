"""Virtual gauges at named towns, read from a finished run's stored frames.

A town row in result.json gives one number per quantity: the maximum. A gauge
gives the whole depth-time curve at the place: when the water arrives, how
fast it rises, when it peaks and whether it has receded by the end of the run.
That is what a district control room plans evacuation timing on.

Two gauges per town, because the town's own coordinate and the river are not
the same place. Rishikesh's point sits 2.3 km from the traced channel and may
never be wet while the valley floor floods:

    town     the cell at the town's published coordinate
    channel  the lowest bed point of the town's stored cross-section, i.e. the
             channel at the town's chainage (only when preprocess.json holds a
             section for the town)

Only depth is stored per frame, so the series are depth only; velocity and
hazard are the run's maxima at the gauge cell. Times are frame times (the
run's output interval), so the time of peak is resolved to one interval — the
arrival time comes from the solver's own per-step arrival raster instead.

Nothing is interpolated or smoothed. A gauge outside the compute window, or a
run with no stored frames, reports that, never zeros.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

#: A gauge this many cells or fewer from the compute-window edge, and wet, is
#: flagged: water there may be leaving through (or reflecting off) the edge.
EDGE_CELLS = 3


def _read(path: Path):
    import rasterio

    with rasterio.open(path) as src:
        return src.read(1, masked=True).filled(np.nan).astype(float), src.transform, src.crs.to_string()


def _cell(transform, crs: str, lon: float, lat: float) -> tuple[int, int]:
    from pyproj import Transformer
    from rasterio.transform import rowcol

    x, y = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform(lon, lat)
    r, c = rowcol(transform, x, y)
    return int(r), int(c)


def _xy_cell(transform, x: float, y: float) -> tuple[int, int]:
    from rasterio.transform import rowcol

    r, c = rowcol(transform, x, y)
    return int(r), int(c)


def _hazard_label(depth: float, velocity: float) -> tuple[int | None, str | None]:
    from floodguard.postprocess.hazard import HAZARD_CLASSES, classify

    if not (np.isfinite(depth) and np.isfinite(velocity)):
        return None, None
    code = int(classify(np.array([[depth]]), np.array([[velocity]]))[0, 0])
    if code == 0:
        return 0, "dry"
    label = next((h.label for h in HAZARD_CLASSES if h.code == code), None)
    return code, label


def _gauge(kind, r, c, rasters, frames, times, wet_threshold, shape) -> dict[str, Any]:
    rows, cols = shape
    inside = 0 <= r < rows and 0 <= c < cols
    out: dict[str, Any] = {"kind": kind, "row": r, "col": c, "in_domain": inside}
    if not inside:
        out.update({"series_m": None, "max_depth_m": None, "note": "outside the compute window"})
        return out
    depth = float(rasters["depth"][r, c])
    vel = float(rasters["velocity"][r, c])
    arr = float(rasters["arrival"][r, c])
    series = [float(f[r, c]) for f in frames] if frames else None
    peak_i = int(np.nanargmax(series)) if series and np.isfinite(series).any() else None
    code, label = _hazard_label(depth, vel)
    wet = np.isfinite(depth) and depth >= wet_threshold
    near_edge = wet and min(r, c, rows - 1 - r, cols - 1 - c) <= EDGE_CELLS
    out.update({
        "max_depth_m": depth if np.isfinite(depth) else None,
        "max_velocity_ms": vel if np.isfinite(vel) else None,
        "arrival_min": arr / 60.0 if np.isfinite(arr) and arr >= 0 else None,
        "peak_frame_min": times[peak_i] / 60.0 if peak_i is not None and series[peak_i] > 0 else None,
        "end_depth_m": series[-1] if series else None,
        # Peak in the last stored frame: the water may still be rising when the
        # run ends, so the maximum here is a lower bound.
        "rising_at_end": bool(peak_i is not None and peak_i == len(series) - 1 and series[peak_i] > 0),
        "hazard_code": code,
        "hazard_label": label,
        "near_domain_edge": bool(near_edge),
        "series_m": series,
    })
    return out


def compute_gauges(run_dir: Path, preprocess_json: Path | None = None) -> dict[str, Any]:
    """Town and channel gauges for every named town in the run."""
    run_dir = Path(run_dir)
    result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    depth, transform, crs = _read(run_dir / "max_depth.tif")
    rasters = {
        "depth": depth,
        "velocity": _read(run_dir / "max_velocity.tif")[0],
        "arrival": _read(run_dir / "arrival_time.tif")[0],
    }
    frames: list[np.ndarray] = []
    times: list[float] = []
    npz_files = sorted(run_dir.glob("frames_*.npz"))
    if npz_files:
        with np.load(npz_files[0]) as npz:
            times = [float(t) for t in npz["times_s"]]
            frames = [npz[f"f{i:04d}"] for i in range(len(times))]
            if frames and frames[0].shape != depth.shape:
                frames, times = [], []  # a grid mismatch must not be sampled

    sections = {}
    if preprocess_json and Path(preprocess_json).exists():
        pre = json.loads(Path(preprocess_json).read_text(encoding="utf-8"))
        sections = {s["name"]: s for s in pre.get("cross_sections", [])}

    wet_threshold = float(
        (result.get("hazard") or {}).get("wet_threshold_m") or 0.3
    )
    gauges = []
    for town in result.get("towns", []):
        r, c = _cell(transform, crs, town["lon"], town["lat"])
        entry: dict[str, Any] = {
            "name": town["name"],
            "population": town.get("population"),
            "town": _gauge("town", r, c, rasters, frames, times, wet_threshold, depth.shape),
            "channel": None,
            "chainage_km": None,
            "town_to_channel_km": None,
        }
        sec = sections.get(town["name"])
        if sec and sec.get("xs") and sec.get("bed_m"):
            i = int(np.nanargmin(np.asarray(sec["bed_m"], dtype=float)))
            cr, cc = _xy_cell(transform, sec["xs"][i], sec["ys"][i])
            entry["channel"] = _gauge("channel", cr, cc, rasters, frames, times, wet_threshold, depth.shape)
            entry["chainage_km"] = float(sec["chainage_m"]) / 1000.0 if sec.get("chainage_m") else None
            cell = abs(transform.a)
            entry["town_to_channel_km"] = float(np.hypot(cr - r, cc - c) * cell / 1000.0)
        gauges.append(entry)

    # Towns beyond the end of the traced reach all fall back to its last section.
    by_cell: dict[tuple[int, int], list[str]] = {}
    for g in gauges:
        if g["channel"] is not None:
            by_cell.setdefault((g["channel"]["row"], g["channel"]["col"]), []).append(g["name"])
    for g in gauges:
        if g["channel"] is None:
            continue
        others = [n for n in by_cell[(g["channel"]["row"], g["channel"]["col"])] if n != g["name"]]
        g["channel"]["shared_with"] = others
        if others:
            g["channel"]["note"] = (
                f"Same channel point as {', '.join(others)}: the town lies beyond the end of the "
                f"traced reach, so its section falls back to the last one. Not a gauge at the town."
            )

    return {
        "run_id": result.get("run_id", run_dir.name),
        "run_completed_utc": result.get("completed_utc"),
        "times_min": [t / 60.0 for t in times],
        "frame_interval_min": (times[1] - times[0]) / 60.0 if len(times) > 1 else None,
        "gauges": gauges,
        "notes": [
            "Depth series are sampled from the solver's stored frames at the gauge cell; "
            "velocity and hazard are the run's maxima there.",
            "The time of peak is resolved to one frame interval; arrival time comes from the "
            "solver's per-step arrival raster.",
            "A channel gauge sits at the lowest bed point of the town's cross-section, "
            "the river at the town's distance downstream, not in the town itself.",
        ] + ([] if frames else ["This run stored no frames, so there are no time series."]),
    }
