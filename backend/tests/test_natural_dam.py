"""Costa (1985) landslide-dam regressions, checked against the report."""

from __future__ import annotations

import pytest

from floodguard.breach.natural_dam import COSTA_1985_LANDSLIDE, costa_1985_landslide_peak


def test_coefficients_match_table_7():
    assert COSTA_1985_LANDSLIDE["height"] == (6.3, 1.59, 0.74, 147.0)
    assert COSTA_1985_LANDSLIDE["volume"] == (672.0, 0.56, 0.73, 142.0)
    assert COSTA_1985_LANDSLIDE["dam_factor"] == (181.0, 0.43, 0.76, 129.0)


def test_gohna_1894_is_within_the_stated_scatter():
    """Gohna, Birahi Ganga, India (Costa 1985 Table 6): H 274 m, V 467e6 m3,
    measured peak 56,650 m3/s. The regression under-predicts by about a factor
    of two, inside its 129% standard error; the test pins both facts."""
    p = costa_1985_landslide_peak(274.0, 467.0)
    assert p.peak_m3s == pytest.approx(181.0 * (274.0 * 467.0) ** 0.43)
    assert 20_000 < p.peak_m3s < 40_000
    assert 56_650 / p.peak_m3s < 1.0 + 1.29  # observed/predicted inside the 129% SE


def test_invalid_inputs_are_refused():
    with pytest.raises(ValueError):
        costa_1985_landslide_peak(0.0, 10.0)


def _scenario(**over):
    from pathlib import Path

    from floodguard.scenario import Scenario

    raw = Scenario.from_yaml(Path(__file__).resolve().parents[2] / "data/scenarios/tehri_bhagirathi.yaml").model_dump(mode="json")
    for dotted, value in over.items():
        target = raw
        *path, last = dotted.split(".")
        for key in path:
            target = target[key]
        target[last] = value
    return Scenario.model_validate(raw)


def test_landslide_breach_on_a_constructed_dam_is_refused():
    from floodguard.breach import parameters as bp

    with pytest.raises(ValueError, match="natural_blockage"):
        bp.resolve(_scenario(scenario_type="landslide_dam_breach"))


def test_natural_blockage_needs_user_breach_geometry():
    from floodguard.breach import parameters as bp

    s = _scenario(**{"dam.dam_type": "natural_blockage", "scenario_type": "landslide_dam_breach"})
    with pytest.raises(ValueError, match="breach.width_m"):
        bp.resolve(s)
    ok = _scenario(**{
        "dam.dam_type": "natural_blockage", "scenario_type": "landslide_dam_breach",
        "breach.width_m": 150.0, "breach.formation_time_min": 60.0,
    })
    used, predictions, _ = bp.resolve(ok)
    assert used.width_m == 150.0 and used.formation_time_min == 60.0
    assert not any(p.applicable for p in predictions)
    assert "NATURAL blockage" in predictions[0].caveats[0]
