"""Graham (1999) loss-of-life estimate: the table, the categorisation, honesty."""

from __future__ import annotations

import numpy as np
import pytest

from floodguard.impact import life_loss as ll


def test_table_7_values_match_the_report():
    """Spot values from DSO-99-06 Table 7, p.38."""
    assert ll.TABLE_7[("high", "none", "vague")] == (0.75, 0.30, 1.00)
    assert ll.TABLE_7[("medium", "none", "vague")] == (0.15, 0.03, 0.35)
    assert ll.TABLE_7[("medium", "some", "precise")] == (0.02, 0.005, 0.04)
    assert ll.TABLE_7[("medium", "adequate", "vague")] == (0.03, 0.005, 0.06)
    assert ll.TABLE_7[("low", "adequate", "precise")] == (0.0002, 0.0, 0.0004)
    assert len(ll.TABLE_7) == 18  # 3 severities x 3 warnings x 2 understandings


def test_high_severity_with_warning_has_no_rate():
    """Graham gives no guidance on how many people remain after a warning."""
    for w in ("some", "adequate"):
        for u in ("vague", "precise"):
            assert ll.TABLE_7[("high", w, u)] is None


def test_every_rate_sits_inside_its_range():
    for key, row in ll.TABLE_7.items():
        if row is not None:
            rate, lo, hi = row
            assert lo <= rate <= hi, key


def test_severity_uses_the_10_ft_rule():
    assert ll.severity_of(np.array([3.0, 3.048, 10.0])).tolist() == [0, 1, 1]


def test_warning_categories():
    assert ll.warning_category(np.array([0, 14.9, 15, 60, 60.1, 300])).tolist() == [0, 0, 1, 1, 2, 2]


def _grid(depth, arrival_min, pop):
    return (np.array([pop], float), np.array([depth], float), np.array([arrival_min], float) * 60.0)


def test_estimate_applies_the_rate_per_category():
    pop, depth, arr = _grid([5.0, 1.0, 5.0], [5.0, 30.0, 120.0], [1000.0, 1000.0, 1000.0])
    r = ll.estimate(pop, depth, arr, warning_issued_min=0.0, understanding="vague")
    # medium/none 0.15*1000 + low/some 0.007*1000 + medium/adequate 0.03*1000
    assert r.estimate == pytest.approx(150 + 7 + 30)
    assert r.low == pytest.approx(30 + 0 + 5)
    assert r.high == pytest.approx(350 + 15 + 60)
    assert r.population_at_risk == 3000


def test_later_warning_raises_the_estimate():
    pop, depth, arr = _grid([5.0], [90.0], [1000.0])
    early = ll.estimate(pop, depth, arr, warning_issued_min=0.0).estimate
    late = ll.estimate(pop, depth, arr, warning_issued_min=80.0).estimate
    assert late > early


def test_dry_cells_and_people_outside_the_flood_are_not_counted():
    pop, depth, arr = _grid([0.1, 5.0], [-1.0, 5.0], [5000.0, 10.0])
    r = ll.estimate(pop, depth, arr)
    assert r.population_at_risk == 10


def test_no_population_is_not_computed_never_zero():
    pop, depth, arr = _grid([5.0], [5.0], [0.0])
    r = ll.estimate(pop, depth, arr).to_dict()
    assert r["computed"] is False and r["estimate"] is None


def test_missing_arrival_is_treated_as_no_warning_and_noted():
    pop, depth, arr = _grid([5.0], [np.nan], [100.0])
    r = ll.estimate(pop, depth, arr, warning_issued_min=-120.0)
    assert r.estimate == pytest.approx(15.0)
    assert any("no recorded arrival" in n for n in r.notes)


def test_output_carries_method_citation_assumptions_and_caveats():
    pop, depth, arr = _grid([5.0], [30.0], [100.0])
    d = ll.estimate(pop, depth, arr, warning_issued_min=10.0, understanding="precise").to_dict()
    assert "DSO-99-06" in d["citation"] and "Graham" in d["method"]
    assert d["assumptions"]["warning_issued_min_after_breach_start"] == 10.0
    assert d["assumptions"]["flood_severity_understanding"] == "precise"
    assert any("not a prediction" in c for c in d["caveats"])


def test_no_population_raster_is_reported_not_guessed(tmp_path):
    d = ll.estimate_for_run(tmp_path, None)
    assert d["computed"] is False and "population" in d["reason"]
