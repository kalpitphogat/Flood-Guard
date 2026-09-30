"""One-at-a-time breach sensitivity: ranges from FloodGuard's own numbers."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from floodguard.breach import parameters as bp
from floodguard.breach.sensitivity import oat_sensitivity
from floodguard.preprocess.reservoir import ElevationAreaCapacity
from floodguard.scenario import Scenario

REPO = Path(__file__).resolve().parents[2]


def _curve(scenario):
    top = scenario.dam.frl_m
    bottom = scenario.dam.crest_elevation_m - scenario.dam.structural_height_m
    levels = np.linspace(bottom, top, 60)
    areas = 5.0e7 * ((levels - bottom) / (top - bottom)) ** 2
    volumes = np.concatenate([[0.0], np.cumsum(0.5 * (areas[1:] + areas[:-1]) * np.diff(levels))])
    return ElevationAreaCapacity(levels, areas, volumes, 14400.0, bottom)


def test_ranges_come_from_the_models_and_the_yaml_and_are_sorted():
    s = Scenario.from_yaml(REPO / "data/scenarios/tehri_bhagirathi.yaml")
    out = oat_sensitivity(s, _curve(s))
    _, predictions, _ = bp.resolve(s)
    by = {f["factor"]: f for f in out["factors"]}
    width = by["Breach width (m)"]
    assert width["low"]["value"] == min(p.width_m for p in predictions)
    assert width["high"]["value"] == max(p.width_m for p in predictions)
    level = by["Reservoir level (m MSL)"]
    assert (level["low"]["value"], level["high"]["value"]) == (740.0, 830.0)
    assert level["high"]["peak_m3s"] > level["low"]["peak_m3s"]  # more water, bigger peak
    swings = [f["swing_m3s"] for f in out["factors"]]
    assert swings == sorted(swings, reverse=True)
    assert any("one at a time" in n.lower() or "varied alone" in n for n in out["notes"])
