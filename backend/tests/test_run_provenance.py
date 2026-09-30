"""Provenance is read from the run's own files; labels are rules over them."""

from __future__ import annotations

import json

import numpy as np
import rasterio
from rasterio.transform import from_origin

from floodguard.postprocess.run_provenance import build_provenance


def _run(tmp_path, tags, result):
    run = tmp_path / "run"
    run.mkdir()
    with rasterio.open(run / "max_depth.tif", "w", driver="GTiff", height=2, width=2, count=1,
                       dtype="float32", crs="EPSG:32644",
                       transform=from_origin(0, 0, 1, 1)) as dst:
        dst.write(np.zeros((1, 2, 2), dtype="float32"))
        dst.update_tags(**tags)
    (run / "result.json").write_text(json.dumps(result))
    return run


def test_rows_name_their_source_and_labels_follow_the_fields(tmp_path):
    tags = {
        "FG_CFL": "0.45",
        "FG_RESERVOIR": json.dumps({"method": "conic", "is_reconstruction": True, "applied": True}),
        "FG_DAM": json.dumps({"name": "D", "sources": {"frl_m": "NOT in the NRLD tables", "lat": "NRLD p.1"}}),
        "FG_VOLUME_INTRODUCED_M3": "100", "FG_VOLUME_REMAINING_M3": "110",
        "FG_VOLUME_CREATED_BY_POSITIVITY_M3": "0",
    }
    run = _run(tmp_path, tags, {
        "run_id": "r", "run_mode": "quick_estimate", "completed_utc": "2026-09-30T00:00:00Z",
        "engines": [{"summary": {}, "display_name": "FloodGuard-SWE", "substituted": False}],
        "breach": {"used": {"model": "m", "applicable": False}}, "warnings": ["w"],
    })
    p = build_provenance(run)
    texts = " | ".join(l["text"] for l in p["labels"])
    assert "Quick estimate" in texts and "RECONSTRUCTED" in texts
    assert "Dam frl_m" in texts and "Dam lat" not in texts  # only flagged sources
    assert "mass gain of 10.0%" in texts and "do not apply" in texts
    rows = {r["label"]: r for s in p["sections"] for r in s["rows"]}
    assert rows["CFL"]["source"] == "max_depth.tif:FG_CFL" and rows["CFL"]["value"] == 0.45
    assert all(r["value"] not in (None, "") for r in rows.values())  # nothing blank is shown
