"""A natural blockage burned into the DEM: wall to wall, watertight, labelled."""

from __future__ import annotations

import numpy as np
import pytest
from scipy import ndimage

from floodguard.preprocess.blockage import MIN_THICKNESS_CELLS, burn_barrier


def _valley(rows=60, cols=80, bed=100.0, side_slope=2.0, fall=0.1):
    """A straight V valley running along +col, walls rising `side_slope` m per cell."""
    r = np.arange(rows)[:, None]
    c = np.arange(cols)[None, :]
    return bed + side_slope * np.abs(r - rows // 2) - fall * c


def _path(rows=60, start=20, cols=80):
    return np.array([(rows // 2, c) for c in range(start, cols)])


def test_the_wall_spans_the_valley_and_meets_ground_at_the_crest():
    dem = _valley()
    nod = np.zeros(dem.shape, bool)
    burned, b = burn_barrier(dem, nod, _path(), 30.0, crest_m=130.0)
    assert b.confined
    # Crest 30 m above a bed at ~98 m, walls rise 2 m per cell: ~16 cells each side.
    assert 25 * 30.0 <= b.crest_length_m <= 35 * 30.0
    assert np.all(burned[b.mask] == 130.0)
    assert np.all(burned[~b.mask] == dem[~b.mask])  # nothing else touched
    assert b.thickness_m == MIN_THICKNESS_CELLS * 30.0
    assert "numerical minimum" in b.thickness_source


def test_release_point_is_downstream_of_the_wall():
    dem = _valley()
    _, b = burn_barrier(dem, np.zeros(dem.shape, bool), _path(), 30.0, crest_m=130.0)
    assert not b.mask[b.release_rc]
    assert b.release_rc[1] > 20  # the path runs towards +col


def test_the_wall_is_watertight_below_its_crest():
    """Water released below it cannot reach the lake side through any face."""
    dem = _valley()
    burned, b = burn_barrier(dem, np.zeros(dem.shape, bool), _path(), 30.0, crest_m=130.0)
    wet = burned < 129.0
    labels, _ = ndimage.label(wet)  # 4-connected, like the solver's faces
    upstream = labels[30, 5]
    assert upstream != 0 and upstream != labels[b.release_rc]


def test_a_diagonal_valley_is_still_sealed():
    n = 80
    r = np.arange(n)[:, None]
    c = np.arange(n)[None, :]
    dem = 100.0 + 2.0 * np.abs(r - c) / np.sqrt(2) - 0.05 * (r + c)
    path = np.array([(i, i) for i in range(20, n)])
    burned, b = burn_barrier(dem, np.zeros(dem.shape, bool), path, 30.0, crest_m=125.0)
    labels, _ = ndimage.label(burned < 124.0)
    assert labels[5, 5] != labels[b.release_rc]


def test_a_crest_higher_than_the_valley_walls_is_flagged_unconfined():
    dem = np.full((40, 40), 100.0) - 0.01 * np.arange(40)[None, :]
    _, b = burn_barrier(dem, np.zeros(dem.shape, bool), _path(40, 10, 40), 30.0,
                        crest_m=150.0, max_half_width_m=300.0)
    assert not b.confined


def test_base_length_sets_the_thickness():
    dem = _valley()
    _, b = burn_barrier(dem, np.zeros(dem.shape, bool), _path(), 30.0, crest_m=130.0,
                        base_length_m=200.0)
    assert b.thickness_m == pytest.approx(7 * 30.0)
    assert "base_length_m" in b.thickness_source
    assert b.to_dict()["burned_into_dem"] is True
