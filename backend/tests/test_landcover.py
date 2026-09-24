"""Land cover: WorldCover tiling, mapped Manning's n, and cropland exposure."""

from __future__ import annotations

import numpy as np

from floodguard.data.landcover import tile_name, tiles_for_bbox
from floodguard.impact.exposure import WORLDCOVER_CROPLAND, _agriculture
from floodguard.preprocess.roughness import ESA_WORLDCOVER_MAP, from_landcover


def test_worldcover_tiles_are_named_by_their_3_degree_south_west_corner():
    assert tile_name(30, 78) == "N30E078"
    # Tehri's AOI straddles 30 N, so it needs the tile below as well.
    assert tiles_for_bbox((78.06, 29.90, 78.90, 30.74)) == ["N27E078", "N30E078"]
    # A box crossing the 84 E tile edge needs both neighbours.
    assert tiles_for_bbox((83.5, 21.2, 84.2, 21.8)) == ["N21E081", "N21E084"]
    # Inside one tile, one tile.
    assert tiles_for_bbox((78.1, 30.1, 78.9, 30.9)) == ["N30E078"]


def test_mapped_roughness_follows_the_classes():
    lc = np.array([[10, 40], [50, 80]], dtype=np.uint8)  # forest, crop, urban, water
    field = from_landcover(lc, ESA_WORLDCOVER_MAP, 0.035)
    assert field.n[0, 0] == np.float32(0.100)
    assert field.n[0, 1] == np.float32(0.050)
    assert field.n[1, 0] == np.float32(0.080)
    assert field.n[1, 1] == np.float32(0.030)
    assert field.coverage_fraction == 1.0
    assert "WorldCover" in field.source


def test_cropland_inside_the_flood_is_measured():
    lc = np.full((10, 10), 10, dtype=np.uint8)
    lc[:, :5] = WORLDCOVER_CROPLAND
    flooded = np.zeros((10, 10), dtype=bool)
    flooded[:4, :] = True  # 4 rows x 5 crop cells = 20 flooded crop cells
    metric = _agriculture(lc, flooded, cell_area=100.0 * 100.0)
    assert metric.computed
    assert metric.value == 20 * 1e4 / 1e6
    assert metric.detail["cropland_in_domain_km2"] == 50 * 1e4 / 1e6


def test_no_land_cover_is_not_computed_never_zero():
    metric = _agriculture(None, np.ones((3, 3), bool), 1.0)
    assert metric.value is None and not metric.computed
    assert metric.display() == "—"


def test_a_mismatched_grid_is_not_computed():
    metric = _agriculture(np.zeros((4, 4), np.uint8), np.ones((3, 3), bool), 1.0)
    assert metric.value is None
    assert "does not match" in metric.reason
