"""One-at-a-time sensitivity of the breach outflow: which input matters most.

Each factor is moved alone from the run's value to the low and high end of a
range, the reservoir is re-routed through the run's own elevation-storage
curve, and the change in peak outflow and time to peak is reported. Sorted by
the size of the swing, that is a tornado chart.

The ranges are FloodGuard's own numbers, not coefficients typed in here:

    breach width        min..max across the three published breach models
                        FloodGuard computes for this dam (Froehlich 2008,
                        Von Thun & Gillette 1990, MacDonald & Langridge-
                        Monopolis 1984)
    formation time      the same span for formation time
    reservoir level     MDDL..FRL from the scenario file

What it is not: a global or probabilistic analysis (factors interact; this
moves one at a time), and it stops at the breach outflow. Downstream arrival
times would need a 2D run per variation.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from floodguard.breach import parameters as bp
from floodguard.breach import routing


def _route(scenario, curve, geometry, level: float) -> dict[str, float]:
    crest = scenario.dam.crest_elevation_m or level
    h = routing.route(
        curve, geometry,
        initial_level_m=level, crest_elevation_m=crest,
        scenario_type=scenario.scenario_type,
        shape=scenario.breach.shape, growth=scenario.breach.growth,
        duration_s=scenario.solver.duration_hours * 3600.0,
        inflow_m3s=scenario.reservoir.inflow_m3s,
    )
    return {
        "peak_m3s": float(h.peak_discharge_m3s),
        "time_to_peak_min": float(h.time_to_peak_s) / 60.0,
        "volume_mcm": float(h.total_volume_m3) / 1e6,
    }


def oat_sensitivity(scenario, curve) -> dict[str, Any]:
    used, predictions, _ = bp.resolve(scenario)
    level = scenario.initial_level_m
    base = _route(scenario, curve, used, level)

    factors = []
    widths = [p.width_m for p in predictions]
    times = [p.formation_time_min for p in predictions]
    ranges = [
        ("Breach width (m)", "width_m", min(widths), max(widths),
         "span of the three published breach models for this dam"),
        ("Breach formation time (min)", "formation_time_min", min(times), max(times),
         "span of the three published breach models for this dam"),
    ]
    for label, field, lo, hi, basis in ranges:
        results = {}
        for end, value in (("low", lo), ("high", hi)):
            results[end] = {"value": value, **_route(scenario, curve, replace(used, **{field: value}), level)}
        factors.append({"factor": label, "basis": basis, "base_value": getattr(used, field), **results})

    if scenario.dam.frl_m is not None and scenario.dam.mddl_m is not None:
        results = {}
        for end, value in (("low", scenario.dam.mddl_m), ("high", scenario.dam.frl_m)):
            results[end] = {"value": value, **_route(scenario, curve, used, value)}
        factors.append({
            "factor": "Reservoir level (m MSL)", "basis": "MDDL to FRL from the scenario file",
            "base_value": level, **results,
        })

    for f in factors:
        f["swing_m3s"] = abs(f["high"]["peak_m3s"] - f["low"]["peak_m3s"])
    factors.sort(key=lambda f: f["swing_m3s"], reverse=True)

    return {
        "method": "one-at-a-time, re-routed through the run's elevation-storage curve",
        "base": {"width_m": used.width_m, "formation_time_min": used.formation_time_min,
                 "level_m": level, **base},
        "factors": factors,
        "notes": [
            "Each factor is varied alone; interactions between factors are not captured.",
            "Ranges are FloodGuard's own: the spread of the three published breach models it "
            "computes for this dam, and the dam's MDDL-FRL range. No coefficient is assumed.",
            "Effects stop at the breach outflow; arrival times downstream would need a 2D run "
            "per variation.",
        ] + ([] if all(p.applicable for p in predictions) else [
            "The breach models are marked inapplicable for this dam, so the width and time "
            "ranges are only indicative.",
        ]),
    }
