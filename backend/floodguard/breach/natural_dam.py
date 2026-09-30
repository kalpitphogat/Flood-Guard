"""Peak outflow from failed LANDSLIDE dams: Costa (1985), USGS OFR 85-560.

Costa, J.E. (1985). *Floods from Dam Failures.* U.S. Geological Survey
Open-File Report 85-560, Denver. Equations 20-22 (p.39), summarised in
Table 7 (p.47); fitted on the ten landslide-dam failures of Table 6 (p.38).

Transcribed from the report and checked against it:

    Q = 6.3  * H ** 1.59        r2 = 0.74, SE = 147 %   (eq. 20)
    Q = 672  * V ** 0.56        r2 = 0.73, SE = 142 %   (eq. 21)
    Q = 181  * (H*V) ** 0.43    r2 = 0.76, SE = 129 %   (eq. 22)

with Q in m3/s, H the dam height in metres and V the lake volume at failure in
10^6 m3. Costa recommends the dam-factor form (H x V) for landslide dams
(p.46), so it is the headline value here; the other two are reported beside it.

Why this exists separately from the embankment regressions: Costa (p.36)
notes that landslide dams are much wider and far more heterogeneous than
constructed dams, so "flood peaks from failed landslide dams appear to be
smaller than constructed dam failures with the same dam height and reservoir
volume". Froehlich, Von Thun & Gillette and MacDonald are fitted on
constructed embankments and do not apply to a natural blockage.

What it is used for: a CROSS-CHECK on the peak of the routed hydrograph for a
blockage scenario. It does not supply breach geometry, which for a landslide
dam must be given by the user. The standard errors above are large (129-147%)
and are always reported with the value.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

REFERENCE = (
    "Costa, J.E. (1985). Floods from Dam Failures. USGS Open-File Report 85-560, "
    "eqs. 20-22 (p.39), Table 7 (p.47)."
)

#: (coefficient, exponent, r2, standard error %) per independent variable.
COSTA_1985_LANDSLIDE = {
    "height": (6.3, 1.59, 0.74, 147.0),
    "volume": (672.0, 0.56, 0.73, 142.0),
    "dam_factor": (181.0, 0.43, 0.76, 129.0),
}

#: Number of landslide-dam failures the equations were fitted on (Table 6).
FITTED_CASES = 10


@dataclass
class NaturalDamPeak:
    height_m: float
    volume_mcm: float
    peak_m3s: float  # the recommended (dam-factor) value
    by_form: dict[str, dict[str, float]] = field(default_factory=dict)
    caveats: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": "Costa (1985) landslide-dam regression, dam factor H x V (eq. 22)",
            "reference": REFERENCE,
            "height_m": self.height_m,
            "volume_mcm": self.volume_mcm,
            "peak_m3s": self.peak_m3s,
            "by_form": self.by_form,
            "fitted_cases": FITTED_CASES,
            "caveats": self.caveats,
        }


def costa_1985_landslide_peak(height_m: float, volume_mcm: float) -> NaturalDamPeak:
    """Costa's three landslide-dam regressions; the dam-factor form is headline."""
    if height_m <= 0 or volume_mcm <= 0:
        raise ValueError("dam height and lake volume must both be positive")
    inputs = {
        "height": height_m,
        "volume": volume_mcm,
        "dam_factor": height_m * volume_mcm,
    }
    by_form = {}
    for form, (a, b, r2, se) in COSTA_1985_LANDSLIDE.items():
        by_form[form] = {
            "peak_m3s": a * inputs[form] ** b,
            "r2": r2,
            "standard_error_pct": se,
            "equation": f"Q = {a:g} * {'H' if form == 'height' else 'V' if form == 'volume' else '(H*V)'}^{b:g}",
        }
    caveats = [
        f"Fitted on only {FITTED_CASES} landslide-dam failures; standard errors of "
        f"{COSTA_1985_LANDSLIDE['dam_factor'][3]:.0f}-{COSTA_1985_LANDSLIDE['height'][3]:.0f}% "
        "(Costa 1985, Table 7). Treat the value as an order of magnitude.",
        "A regression on the dam's height and lake volume, with no breach geometry: "
        "it is a cross-check on the routed hydrograph, not a substitute for it.",
    ]
    return NaturalDamPeak(
        height_m=height_m,
        volume_mcm=volume_mcm,
        peak_m3s=by_form["dam_factor"]["peak_m3s"],
        by_form=by_form,
        caveats=caveats,
    )
