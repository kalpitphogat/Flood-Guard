"""Virtual gauges: series from stored frames, honest flags, no invented zeros."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.transform import from_origin

from floodguard.postprocess.gauges import compute_gauges

CRS = "EPSG:32644"
T = from_origin(300000.0, 3330000.0, 100.0, 100.0)
SHAPE = (20, 20)


def _tif(path: Path, arr) -> None:
    with rasterio.open(path, "w", driver="GTiff", height=SHAPE[0], width=SHAPE[1], count=1,
                       dtype="float32", crs=CRS, transform=T) as dst:
        dst.write(np.asarray(arr, dtype="float32")[None])


def _lonlat(row: int, col: int) -> tuple[float, float]:
    x, y = T * (col + 0.5, row + 0.5)
    return Transformer.from_crs(CRS, "EPSG:4326", always_xy=True).transform(x, y)


def _run(tmp_path: Path, frames: list[np.ndarray], towns) -> Path:
    run = tmp_path / "run"
    run.mkdir()
    depth = np.max(frames, axis=0)
    _tif(run / "max_depth.tif", depth)
    _tif(run / "max_velocity.tif", np.where(depth > 0, 2.0, 0.0))
    arrival = np.full(SHAPE, -1.0)
    arrival[depth > 0.3] = 600.0
    _tif(run / "arrival_time.tif", arrival)
    np.savez(run / "frames_swe_fv.npz", times_s=np.arange(len(frames)) * 300.0,
             **{f"f{i:04d}": f for i, f in enumerate(frames)})
    (run / "result.json").write_text(json.dumps({
        "run_id": "r", "completed_utc": "2026-09-30T00:00:00Z",
        "hazard": {"wet_threshold_m": 0.3}, "towns": towns,
    }))
    return run


def test_series_peak_and_flags(tmp_path):
    frames = []
    for d in (0.0, 1.0, 3.0, 2.0):
        f = np.zeros(SHAPE)
        f[10, 10] = d
        f[1, 5] = d  # a wet cell next to the edge
        frames.append(f)
    lon, lat = _lonlat(10, 10)
    elon, elat = _lonlat(1, 5)
    far_lon, far_lat = _lonlat(10, 10)
    run = _run(tmp_path, frames, [
        {"name": "Mid", "lon": lon, "lat": lat, "population": 10},
        {"name": "Edge", "lon": elon, "lat": elat},
        {"name": "Away", "lon": far_lon + 1.0, "lat": far_lat},
    ])
    g = {x["name"]: x for x in compute_gauges(run)["gauges"]}
    mid = g["Mid"]["town"]
    assert mid["series_m"] == [0.0, 1.0, 3.0, 2.0]
    assert mid["peak_frame_min"] == 10.0 and mid["end_depth_m"] == 2.0
    assert mid["arrival_min"] == 10.0 and mid["rising_at_end"] is False
    assert mid["near_domain_edge"] is False and mid["hazard_label"] not in (None, "dry")
    assert g["Edge"]["town"]["near_domain_edge"] is True
    away = g["Away"]["town"]
    assert away["in_domain"] is False and away["max_depth_m"] is None  # never 0
    assert g["Mid"]["channel"] is None  # no preprocess.json given


def test_rising_at_end_and_shared_channel_section(tmp_path):
    frames = []
    for d in (0.0, 1.0, 2.0):
        f = np.zeros(SHAPE)
        f[8, 8] = d
        frames.append(f)
    a_lon, a_lat = _lonlat(3, 3)
    b_lon, b_lat = _lonlat(15, 15)
    run = _run(tmp_path, frames, [
        {"name": "A", "lon": a_lon, "lat": a_lat}, {"name": "B", "lon": b_lon, "lat": b_lat},
    ])
    x, y = T * (8 + 0.5, 8 + 0.5)
    section = {"xs": [x - 100, x, x + 100], "ys": [y, y, y], "bed_m": [5.0, 1.0, 5.0],
               "chainage_m": 150000.0}
    pre = tmp_path / "preprocess.json"
    pre.write_text(json.dumps({"cross_sections": [{"name": "A", **section}, {"name": "B", **section}]}))
    g = {x["name"]: x for x in compute_gauges(run, pre)["gauges"]}
    ch = g["A"]["channel"]
    assert ch["series_m"] == [0.0, 1.0, 2.0] and ch["rising_at_end"] is True
    assert g["A"]["chainage_km"] == 150.0
    assert ch["shared_with"] == ["B"] and "beyond the end of the traced reach" in ch["note"]


def test_no_frames_means_no_series(tmp_path):
    f = np.zeros(SHAPE)
    f[5, 5] = 1.0
    run = _run(tmp_path, [f], [{"name": "T", "lon": _lonlat(5, 5)[0], "lat": _lonlat(5, 5)[1]}])
    (run / "frames_swe_fv.npz").unlink()
    out = compute_gauges(run)
    assert out["gauges"][0]["town"]["series_m"] is None
    assert any("no frames" in n for n in out["notes"])
