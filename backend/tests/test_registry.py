"""Site readiness is computed from files, and a DEM must COVER the AOI."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

from floodguard import library as lib
from floodguard.data.acquire import derive_aoi
from floodguard.registry import site_row
from floodguard.scenario import Scenario

REPO = Path(__file__).resolve().parents[2]


def _dem(path: Path, west, south, east, north):
    path.parent.mkdir(parents=True, exist_ok=True)
    w, h = 50, 50
    with rasterio.open(path, "w", driver="GTiff", height=h, width=w, count=1, dtype="float32",
                       crs="EPSG:4326",
                       transform=from_origin(west, north, (east - west) / w, (north - south) / h)) as dst:
        dst.write(np.zeros((1, h, w), dtype="float32"))


def test_tiers(tmp_path):
    s = Scenario.from_yaml(REPO / "data/scenarios/tehri_bhagirathi.yaml")
    assert site_row(s, tmp_path)["tier"] == "not ready"

    aoi = derive_aoi(s)
    dem = tmp_path / "processed" / s.id / "r120" / "dem_utm.tif"
    _dem(dem, aoi[0] + 0.3, aoi[1], aoi[2], aoi[3])  # misses the western part
    row = site_row(s, tmp_path)
    assert row["tier"] == "not ready" and "does not cover" in row["tier_reason"]

    _dem(dem, aoi[0] - 0.05, aoi[1] - 0.05, aoi[2] + 0.05, aoi[3] + 0.05)
    assert site_row(s, tmp_path)["tier"] == "inputs ready"

    for i, preset in enumerate(lib.iter_presets(s)):
        res = lib.result_path(tmp_path, preset.key)
        res.parent.mkdir(parents=True)
        res.write_text("{}")
        lib.record(tmp_path, preset.key, {"status": "succeeded", "run_id": preset.run_id})
        tier = site_row(s, tmp_path)["tier"]
        assert tier == ("presets ready" if i == 2 else "partly ready")
