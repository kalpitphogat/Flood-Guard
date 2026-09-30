"""Resolution-scoped processed folders, with the legacy flat layout as fallback."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from floodguard import processed


def _dem(path: Path, cell_m: float) -> Path:
    import rasterio
    from rasterio.transform import from_origin

    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path, "w", driver="GTiff", height=4, width=4, count=1, dtype="float32",
        crs="EPSG:32644", transform=from_origin(300000, 3300000, cell_m, cell_m),
    ) as dst:
        dst.write(np.zeros((1, 4, 4), dtype="float32"))
    return path


@pytest.mark.parametrize("res,tag", [(120, "r120"), (200.0, "r200"), (92.5, "r92p5")])
def test_res_tag(res, tag):
    assert processed.res_tag(res) == tag


def test_new_data_goes_to_the_resolution_folder(tmp_path):
    assert processed.inputs_dir(tmp_path, "s", 200) == tmp_path / "processed" / "s" / "r200"


def test_legacy_flat_folder_is_used_when_its_resolution_matches(tmp_path):
    _dem(tmp_path / "processed" / "s" / "dem_utm.tif", 120.0)
    assert processed.inputs_dir(tmp_path, "s", 120) == tmp_path / "processed" / "s"
    # a different resolution never reuses it: that was the thrashing bug
    assert processed.inputs_dir(tmp_path, "s", 200) == tmp_path / "processed" / "s" / "r200"


def test_resolution_folder_wins_over_legacy(tmp_path):
    _dem(tmp_path / "processed" / "s" / "dem_utm.tif", 120.0)
    _dem(tmp_path / "processed" / "s" / "r120" / "dem_utm.tif", 120.0)
    assert processed.inputs_dir(tmp_path, "s", 120) == tmp_path / "processed" / "s" / "r120"


def test_preprocess_json_lookup_in_both_layouts(tmp_path):
    flat = tmp_path / "processed" / "a" / "preprocess.json"
    flat.parent.mkdir(parents=True)
    flat.write_text("{}")
    scoped = tmp_path / "processed" / "b" / "r200" / "preprocess.json"
    _dem(scoped.parent / "dem_utm.tif", 200.0)
    scoped.write_text("{}")
    assert processed.find_preprocess_json(tmp_path, "a") == flat
    assert processed.find_preprocess_json(tmp_path, "b", 200) == scoped
    assert processed.find_preprocess_json(tmp_path, "b", 120) is None
    assert set(processed.all_preprocess_json(tmp_path)) == {flat, scoped}


def test_preprocess_json_found_without_a_dem_when_its_grid_matches(tmp_path):
    """A demo laptop gets preprocess.json from a pack but no DEM."""
    import json

    flat = tmp_path / "processed" / "s" / "preprocess.json"
    flat.parent.mkdir(parents=True)
    flat.write_text(json.dumps({"grid": {"cell_size_m": 120.0}}))
    assert processed.find_preprocess_json(tmp_path, "s", 120) == flat
    assert processed.find_preprocess_json(tmp_path, "s", 60) is None  # never the wrong grid
