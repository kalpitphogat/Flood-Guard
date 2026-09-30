"""Partial breach: a user-set breach-depth fraction, labelled as an assumption."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from floodguard import library as lib
from floodguard.breach import parameters as bp
from floodguard.breach import routing
from floodguard.preprocess.reservoir import ElevationAreaCapacity
from floodguard.scenario import Scenario, ScenarioType

TEHRI = Path(__file__).resolve().parents[2] / "data" / "scenarios" / "tehri_bhagirathi.yaml"


def _tehri(**breach) -> dict:
    raw = Scenario.from_yaml(TEHRI).model_dump(mode="json")
    raw["scenario_type"] = "partial_breach"
    raw["breach"].update(breach)
    return raw


def test_partial_breach_without_a_fraction_is_refused():
    with pytest.raises(ValueError, match="partial breach needs"):
        Scenario.model_validate(_tehri())


def test_a_fraction_of_one_is_a_complete_break_and_is_refused():
    with pytest.raises(ValueError, match="partial breach needs"):
        Scenario.model_validate(_tehri(depth_fraction=1.0))


def test_depth_and_fraction_together_are_refused():
    with pytest.raises(ValueError, match="not both"):
        Scenario.model_validate(_tehri(depth_fraction=0.5, depth_m=50.0))


def test_fraction_sets_the_breach_depth_and_lowers_the_head():
    s = Scenario.model_validate(_tehri(depth_fraction=0.4))
    full = Scenario.from_yaml(TEHRI)
    assert s.breach_depth_m == pytest.approx(0.4 * s.dam.structural_height_m)
    assert s.water_head_m < full.water_head_m
    assert s.provenance_inputs()["breach_depth_fraction"] == 0.4


def test_resolved_geometry_carries_the_assumption_first():
    s = Scenario.model_validate(_tehri(depth_fraction=0.4))
    used, _, _ = bp.resolve(s)
    assert used.depth_m == pytest.approx(0.4 * s.dam.structural_height_m)
    assert used.caveats[0].startswith("PARTIAL BREACH — ASSUMPTION")
    assert "40%" in used.caveats[0]


def _conic(crest=100.0, storage_m3=1.0e9, n=80):
    levels = np.linspace(0.0, crest, n)
    areas = 3.0 * storage_m3 / crest * (levels / crest) ** 2
    return ElevationAreaCapacity(levels, areas, areas * levels / 3.0, 900.0, 0.0)


def test_a_partial_breach_leaves_the_pool_below_its_invert_behind():
    curve = _conic()
    kw = dict(initial_level_m=100.0, crest_elevation_m=100.0,
              scenario_type=ScenarioType.PARTIAL_BREACH, duration_s=24 * 3600.0)
    full = routing.route(curve, bp.BreachGeometry("f", 200.0, 100.0, 1.0, 15.0, "t"), **kw)
    half = routing.route(curve, bp.BreachGeometry("h", 200.0, 50.0, 1.0, 15.0, "t"), **kw)
    # Drains to the invert at 50 m, and no lower.
    assert half.final_level_m == pytest.approx(50.0, abs=1.0)
    # A cone holds (50/100)^3 = 1/8 of its volume below half height.
    assert half.total_volume_m3 == pytest.approx(1.0e9 * (1 - 0.125), rel=0.05)
    assert half.total_volume_m3 < full.total_volume_m3
    assert half.peak_discharge_m3s < full.peak_discharge_m3s
    assert half.mass_error < 1e-3


def test_partial_breach_is_listed_but_never_precomputed():
    s = Scenario.from_yaml(TEHRI)
    partial = [p for p in lib.iter_presets(s, include_unmodelled=True)
               if p.scenario_type == "partial_breach"]
    assert partial and not any(p.modelled for p in partial)
    assert "Runs live only" in lib.not_precomputed_reason("partial_breach")
    assert lib.not_precomputed_reason("overtopping") == lib.UNMODELLED_REASON
    with pytest.raises(ValueError, match="Runs live only"):
        lib.build_preset_scenario(s, "partial_breach", "frl")
