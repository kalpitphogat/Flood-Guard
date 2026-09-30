"""Layover/shadow geometry (Vollrath et al. 2020, geometric part): definitions, not tuning."""

from __future__ import annotations

import numpy as np
import pytest

from floodguard.data import sar_geometry as g

SENSOR = 100.0  # azimuth from the ground towards the sensor, degrees (east-ish)


def test_flat_ground_sees_the_ellipsoid_incidence_angle():
    assert g.local_incidence_deg(39.0, 0.0, 0.0, SENSOR) == pytest.approx(39.0)


def test_a_slope_facing_the_sensor_lowers_the_local_angle_and_one_facing_away_raises_it():
    towards = g.local_incidence_deg(39.0, 20.0, SENSOR, SENSOR)          # aspect = towards sensor
    away = g.local_incidence_deg(39.0, 20.0, SENSOR + 180.0, SENSOR)
    assert towards == pytest.approx(19.0) and away == pytest.approx(59.0)


def test_a_slope_along_the_orbit_has_no_range_component():
    assert g.range_slope_deg(35.0, SENSOR + 90.0, SENSOR) == pytest.approx(0.0, abs=1e-9)


def test_layover_is_a_sensor_facing_slope_steeper_than_the_incidence_angle():
    valid, lay, sh = g.classify(np.array([39.0, 39.0]), np.array([38.0, 41.0]),
                                np.array([SENSOR, SENSOR]), SENSOR)
    assert list(lay) == [False, True] and not sh.any()
    assert list(valid) == [True, False]


def test_shadow_is_an_away_facing_slope_steeper_than_the_grazing_complement():
    # 90 - 39 = 51 degrees is the boundary.
    valid, lay, sh = g.classify(np.array([39.0, 39.0]), np.array([50.0, 52.0]),
                                np.array([SENSOR + 180.0] * 2), SENSOR)
    assert list(sh) == [False, True] and not lay.any()


def test_the_geometry_works_the_same_for_an_ascending_pass():
    """An ascending pass looks the other way: the same slope swaps shadow for layover."""
    east_facing_steep = dict(slope_deg=60.0, aspect_deg=90.0)
    _, lay_d, sh_d = g.classify(39.0, towards_sensor_az_deg=100.0, **east_facing_steep)
    _, lay_a, sh_a = g.classify(39.0, towards_sensor_az_deg=280.0, **east_facing_steep)
    assert bool(lay_d) and not bool(sh_d)
    assert bool(sh_a) and not bool(lay_a)


def test_reference_is_recorded():
    assert "10.3390/rs12111867" in g.REFERENCE and "49(8)" in g.REFERENCE
