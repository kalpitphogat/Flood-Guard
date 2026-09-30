"""Loss-of-life estimate: Graham (1999), USBR DSO-99-06, flood-severity method.

Graham, W.J. (1999). *A Procedure for Estimating Loss of Life Caused by Dam
Failure.* DSO-99-06, U.S. Bureau of Reclamation Dam Safety Office, Denver.

Every rate below is Table 7 ("Recommended Fatality Rates for Estimating Loss
of Life Resulting from Dam Failure", report p.38), transcribed and checked
against the report itself. The categorisation rules are the report's own
(pp.26-27 and 35-36):

* **Flood severity** — LOW where most structures see depths under 10 ft
  (3.048 m), MEDIUM at 10 ft or more (guidance item 4, p.35). HIGH is only for
  the near-instantaneous failure of a concrete dam, or an embankment that
  "goes out in seconds rather than minutes or hours" and sweeps the area clean
  (item 3). FloodGuard's embankment breaches form over tens of minutes to
  hours (Froehlich 2008), so HIGH is never assigned automatically.
* **Warning time** — the time between a warning being issued in an area and
  the flood water arriving there (p.36): under 15 min is "no warning", 15-60
  min "some", over 60 min "adequate" (p.26).
* **Flood severity understanding** — vague or precise (p.27); it applies only
  when there is some warning.

Applied per grid cell: the population in each flooded cell is binned by the
cell's severity and warning category and multiplied by the Table 7 rate; the
suggested range gives the low and high bounds.

What this is not: a prediction. Graham's data are ~40 floods, mostly in the
USA and mostly small dams; he writes that "no currently available procedure is
capable of predicting the exact number of fatalities". The population used is
modelled residential population, not the number of people actually present at
the time of failure. Every output carries these caveats.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

METHOD = "Graham (1999) flood-severity method, USBR DSO-99-06, Table 7"
CITATION = (
    "Graham, W.J. (1999). A Procedure for Estimating Loss of Life Caused by Dam Failure. "
    "DSO-99-06, U.S. Bureau of Reclamation Dam Safety Office, Denver, Colorado."
)

#: 10 ft, Graham's low/medium depth boundary (p.35, item 4).
MEDIUM_SEVERITY_DEPTH_M = 3.048
#: Warning-time category bounds, minutes (p.26).
SOME_WARNING_MIN = 15.0
ADEQUATE_WARNING_MIN = 60.0

SEVERITIES = ("low", "medium", "high")
WARNINGS = ("none", "some", "adequate")
UNDERSTANDINGS = ("vague", "precise")

#: Table 7: (severity, warning, understanding) -> (suggested, range_low, range_high).
#: For "none" the understanding does not apply and both keys hold the same row.
#: HIGH severity with some/adequate warning has no rate: Graham says to apply the
#: no-warning rate to "the number of people who remain in the dam failure
#: floodplain after warnings are issued. No guidance is provided on how many
#: people will remain" — so FloodGuard reports it as not computed.
TABLE_7: dict[tuple[str, str, str], tuple[float, float, float] | None] = {
    ("high", "none", "vague"): (0.75, 0.30, 1.00),
    ("high", "none", "precise"): (0.75, 0.30, 1.00),
    ("high", "some", "vague"): None,
    ("high", "some", "precise"): None,
    ("high", "adequate", "vague"): None,
    ("high", "adequate", "precise"): None,
    ("medium", "none", "vague"): (0.15, 0.03, 0.35),
    ("medium", "none", "precise"): (0.15, 0.03, 0.35),
    ("medium", "some", "vague"): (0.04, 0.01, 0.08),
    ("medium", "some", "precise"): (0.02, 0.005, 0.04),
    ("medium", "adequate", "vague"): (0.03, 0.005, 0.06),
    ("medium", "adequate", "precise"): (0.01, 0.002, 0.02),
    ("low", "none", "vague"): (0.01, 0.0, 0.02),
    ("low", "none", "precise"): (0.01, 0.0, 0.02),
    ("low", "some", "vague"): (0.007, 0.0, 0.015),
    ("low", "some", "precise"): (0.002, 0.0, 0.004),
    ("low", "adequate", "vague"): (0.0003, 0.0, 0.0006),
    ("low", "adequate", "precise"): (0.0002, 0.0, 0.0004),
}

CAVEATS = [
    "An order-of-magnitude planning estimate, not a prediction. Graham (1999) derived "
    "these rates from about 40 floods, mostly in the United States and mostly below "
    "small dams; they have not been calibrated for Indian settlements, building types "
    "or warning systems.",
    "Population at risk is modelled residential population (WorldPop 2020) in the "
    "flooded cells. It ignores time of day, pilgrims, tourists, workers and travellers, "
    "any of whom can dominate the real number at risk.",
    "Warning time depends on WHEN a warning is issued, which is an assumption shown "
    "with the result. Graham calls this 'probably the most important part' of the "
    "estimate (p.14).",
    "HIGH severity (floodplain swept clean) is not assigned automatically: Graham "
    "reserves it for failures that release the reservoir in seconds. Near the dam the "
    "true severity may be higher than modelled here.",
    "Graham notes that fatality rates become very small beyond about 25 km (15 mi) "
    "from the dam; this estimate covers the whole modelled reach.",
]


def severity_of(depth_m: np.ndarray) -> np.ndarray:
    """0 = low, 1 = medium, by Graham's 10 ft rule."""
    return (np.nan_to_num(depth_m, nan=0.0) >= MEDIUM_SEVERITY_DEPTH_M).astype(np.int8)


def warning_category(warning_minutes: np.ndarray) -> np.ndarray:
    """0 = none (<15 min), 1 = some (15-60), 2 = adequate (>60)."""
    w = np.asarray(warning_minutes, dtype=float)
    cat = np.zeros(w.shape, dtype=np.int8)
    cat[w >= SOME_WARNING_MIN] = 1
    cat[w > ADEQUATE_WARNING_MIN] = 2
    return cat


@dataclass
class LifeLossEstimate:
    population_at_risk: float
    estimate: float | None
    low: float | None
    high: float | None
    warning_issued_min: float
    understanding: str
    by_category: list[dict[str, Any]] = field(default_factory=list)
    not_computed_par: float = 0.0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        def rnd(v):
            return None if v is None else int(round(v))

        return {
            "method": METHOD,
            "citation": CITATION,
            "computed": self.estimate is not None,
            "population_at_risk": rnd(self.population_at_risk),
            "estimate": rnd(self.estimate),
            "range": [rnd(self.low), rnd(self.high)],
            "assumptions": {
                "warning_issued_min_after_breach_start": self.warning_issued_min,
                "flood_severity_understanding": self.understanding,
                "severity_rule": "low below 3.048 m (10 ft) maximum depth, medium at or above; "
                                 "high never assigned automatically",
                "warning_categories_min": {"none": "<15", "some": "15-60", "adequate": ">60"},
            },
            "by_category": self.by_category,
            "par_without_a_rate": rnd(self.not_computed_par),
            "notes": self.notes,
            "caveats": CAVEATS,
        }


def estimate(
    population: np.ndarray,
    max_depth_m: np.ndarray,
    arrival_s: np.ndarray,
    *,
    warning_issued_min: float = 0.0,
    understanding: str = "vague",
    wet_threshold_m: float = 0.3,
) -> LifeLossEstimate:
    """Apply Table 7 cell by cell. All arrays share one grid.

    `population` is persons per cell; `arrival_s` is the first time the cell
    exceeded the wet threshold (negative or NaN = never). A flooded cell with no
    recorded arrival is treated as having had no warning (the conservative
    choice) and counted in the notes.
    """
    if understanding not in UNDERSTANDINGS:
        raise ValueError(f"understanding must be one of {UNDERSTANDINGS}")
    pop = np.nan_to_num(np.asarray(population, dtype=float), nan=0.0)
    pop[pop < 0] = 0.0
    depth = np.nan_to_num(np.asarray(max_depth_m, dtype=float), nan=0.0)
    arrival = np.asarray(arrival_s, dtype=float)
    flooded = depth >= wet_threshold_m

    par_total = float(pop[flooded].sum())
    notes: list[str] = []
    no_arrival = flooded & ~(np.isfinite(arrival) & (arrival >= 0))
    if pop[no_arrival].sum() > 0:
        notes.append(
            f"{pop[no_arrival].sum():,.0f} people are in flooded cells with no recorded "
            f"arrival time; they were treated as receiving no warning."
        )
    arrival_min = np.where(no_arrival, warning_issued_min, arrival / 60.0)
    warning_min = arrival_min - warning_issued_min

    sev = severity_of(depth)
    warn = warning_category(warning_min)
    rows = []
    est = lo = hi = 0.0
    unrated = 0.0
    for s_i, s_name in enumerate(("low", "medium")):
        for w_i, w_name in enumerate(WARNINGS):
            mask = flooded & (sev == s_i) & (warn == w_i)
            par = float(pop[mask].sum())
            if par <= 0:
                continue
            rate = TABLE_7[(s_name, w_name, understanding)]
            if rate is None:
                unrated += par
                continue
            est += par * rate[0]
            lo += par * rate[1]
            hi += par * rate[2]
            rows.append({
                "severity": s_name, "warning": w_name,
                "understanding": understanding if w_name != "none" else "not applicable",
                "population_at_risk": int(round(par)),
                "fatality_rate": rate[0], "rate_range": [rate[1], rate[2]],
                "estimate": int(round(par * rate[0])),
            })

    if par_total <= 0:
        return LifeLossEstimate(
            population_at_risk=0.0, estimate=None, low=None, high=None,
            warning_issued_min=warning_issued_min, understanding=understanding,
            notes=["No modelled population lies in the flooded area, so no estimate is made."],
        )
    return LifeLossEstimate(
        population_at_risk=par_total, estimate=est, low=lo, high=hi,
        warning_issued_min=warning_issued_min, understanding=understanding,
        by_category=rows, not_computed_par=unrated, notes=notes,
    )


def population_on_grid(population_raster: Path, like_raster: Path) -> np.ndarray:
    """Persons per cell of `like_raster`'s grid, summed (counts are preserved)."""
    import rasterio
    from rasterio.warp import Resampling, reproject

    with rasterio.open(like_raster) as ref:
        shape, transform, crs = (ref.height, ref.width), ref.transform, ref.crs
    out = np.zeros(shape, dtype="float64")
    with rasterio.open(population_raster) as src:
        from rasterio.windows import from_bounds
        from rasterio.warp import transform_bounds

        left, bottom, right, top = transform_bounds(crs, src.crs, *_bounds(shape, transform))
        window = from_bounds(left, bottom, right, top, src.transform).round_offsets().round_lengths()
        data = src.read(1, window=window, boundless=True, fill_value=0).astype("float64")
        nodata = src.nodata
        if nodata is not None:
            data[data == nodata] = 0.0
        data[~np.isfinite(data)] = 0.0
        data[data < 0] = 0.0
        reproject(
            data, out,
            src_transform=src.window_transform(window), src_crs=src.crs,
            dst_transform=transform, dst_crs=crs,
            resampling=Resampling.sum, src_nodata=None, dst_nodata=None,
        )
    return out


def _bounds(shape, transform) -> tuple[float, float, float, float]:
    rows, cols = shape
    left, top = transform.c, transform.f
    right = left + cols * transform.a
    bottom = top + rows * transform.e
    return left, min(bottom, top), right, max(bottom, top)


def estimate_for_run(
    run_dir: Path,
    population_raster: Path | None,
    *,
    warning_issued_min: float = 0.0,
    understanding: str = "vague",
    wet_threshold_m: float = 0.3,
) -> dict[str, Any]:
    """Estimate from a finished run's rasters. Returns a JSON-ready dict."""
    import json

    import rasterio

    run_dir = Path(run_dir)
    completed = None
    if (run_dir / "result.json").exists():
        completed = json.loads((run_dir / "result.json").read_text(encoding="utf-8")).get(
            "completed_utc"
        )
    if population_raster is None or not Path(population_raster).exists():
        return {
            "method": METHOD, "citation": CITATION, "computed": False,
            "reason": "No population raster is available on this machine, so the "
                      "population at risk is unknown and no estimate is made.",
            "caveats": CAVEATS,
        }
    with rasterio.open(run_dir / "max_depth.tif") as src:
        depth = src.read(1, masked=True).filled(np.nan).astype(float)
    with rasterio.open(run_dir / "arrival_time.tif") as src:
        arrival = src.read(1, masked=True).filled(np.nan).astype(float)
    pop = population_on_grid(Path(population_raster), run_dir / "max_depth.tif")
    result = estimate(
        pop, depth, arrival, warning_issued_min=warning_issued_min,
        understanding=understanding, wet_threshold_m=wet_threshold_m,
    ).to_dict()
    result["population_source"] = str(Path(population_raster).name)
    # Ties the cached estimate to the exact run it was computed from, so a copy
    # (a data pack) or a recomputed run can be told apart by content, not by
    # file timestamps.
    result["run_completed_utc"] = completed
    return result
