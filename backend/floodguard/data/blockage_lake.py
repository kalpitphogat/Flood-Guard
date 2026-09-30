"""Blockage-lake check: open water that appeared or vanished around a river point.

A landslide or debris flow that blocks a river ponds a lake behind it; a lake
that bursts leaves ground where water was. Both show up in Sentinel-1 radar,
through cloud and at night, as a change in open water between a window before
an event date and a window after it.

What this does, per window (before / after the event date):

1. every Sentinel-1 IW scene is speckle-filtered in linear power and masked for
   layover and radar shadow with ITS OWN geometry (sar_geometry.py);
2. the scenes are mosaicked and water is split from land by Otsu's method
   (Otsu 1979), computed separately for each window — the two windows can
   differ in orbit, incidence angle and season, so one threshold for both is
   wrong somewhere;
3. new water   = water after, not water before, not JRC permanent water;
   lost water  = water before, not water after (permanent water is NOT
                 excluded here: a lake that drains is usually "permanent");
   a pixel not imaged in BOTH windows is unobserved and never counted.

What this deliberately does NOT do: filter candidates by area, distance to a
drainage line, elevation spread or slope. Every such cut-off found in the
reference implementation was an unpublished working value, so here each
candidate is REPORTED with those measurements instead, ranked by area, and
labelled a candidate change in open water, not a confirmed lake.

Raises gee.GEEUnavailable when Earth Engine is not configured, and ValueError
when a window has no scenes — never a cached or synthetic result.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, timedelta
from typing import Any

#: Sentinel-1 revisit over India is 12 days since Sentinel-1B failed (Dec 2021),
#: so the default windows hold at least two passes of each geometry.
DEFAULT_WINDOW_DAYS = 24

OTSU_REFERENCE = (
    "Otsu, N. (1979). A threshold selection method from gray-level histograms. "
    "IEEE Trans. Systems, Man, and Cybernetics 9(1), 62-66."
)
CANDIDATE_LABEL = "candidate change in open water — not a confirmed lake"


def windows(event_date: str, pre_days: int, post_days: int) -> tuple[tuple[str, str], tuple[str, str]]:
    """(pre_start, pre_end_exclusive), (post_start, post_end_exclusive) as ISO dates."""
    if pre_days <= 0 or post_days <= 0:
        raise ValueError("pre_days and post_days must be positive")
    d = date.fromisoformat(event_date)
    return (
        ((d - timedelta(days=pre_days)).isoformat(), d.isoformat()),
        (d.isoformat(), (d + timedelta(days=post_days + 1)).isoformat()),
    )


@dataclass
class LakeCandidate:
    kind: str  # "new_water" | "lost_water"
    area_m2: float
    centroid_lon: float
    centroid_lat: float
    distance_to_point_m: float
    elevation_p10_m: float | None
    elevation_p50_m: float | None
    elevation_p90_m: float | None
    mean_slope_deg: float | None
    geometry: dict[str, Any] | None = None
    label: str = CANDIDATE_LABEL

    @property
    def elevation_spread_m(self) -> float | None:
        if self.elevation_p10_m is None or self.elevation_p90_m is None:
            return None
        return self.elevation_p90_m - self.elevation_p10_m

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["elevation_spread_m"] = self.elevation_spread_m
        return out


def candidate_from_feature(feature: dict[str, Any]) -> LakeCandidate:
    """Turn one Earth Engine feature (as getInfo() returns it) into a candidate."""
    p = feature.get("properties", {})

    def num(key):
        v = p.get(key)
        return float(v) if v is not None and math.isfinite(float(v)) else None

    return LakeCandidate(
        kind="new_water" if int(p.get("label", 0)) == 1 else "lost_water",
        area_m2=float(p["area_m2"]),
        centroid_lon=float(p["cx"]),
        centroid_lat=float(p["cy"]),
        distance_to_point_m=float(p["dist_m"]),
        elevation_p10_m=num("DEM_p10"),
        elevation_p50_m=num("DEM_p50"),
        elevation_p90_m=num("DEM_p90"),
        mean_slope_deg=num("slope_mean"),
        geometry=feature.get("geometry"),
    )


@dataclass
class LakeCheck:
    point: tuple[float, float]
    event_date: str
    radius_km: float
    pre_window: tuple[str, str]
    post_window: tuple[str, str]
    scenes: dict[str, list[dict[str, Any]]]
    thresholds_db: dict[str, float | None]
    imaged_fraction: dict[str, float | None]
    new_water_km2: float | None
    lost_water_km2: float | None
    #: Open water in each window, over the area imaged in BOTH windows.
    water_before_km2: float | None
    water_after_km2: float | None
    candidates: list[LakeCandidate]
    candidates_total: int
    warnings: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["candidates"] = [c.to_dict() for c in self.candidates]
        return out


def check_blockage_lake(
    lon: float,
    lat: float,
    event_date: str,
    *,
    radius_km: float = 3.0,
    pre_days: int = DEFAULT_WINDOW_DAYS,
    post_days: int = DEFAULT_WINDOW_DAYS,
    polarisation: str = "VV",
    scale_m: float = 20.0,
    max_candidates: int = 25,
    project: str | None = None,
) -> LakeCheck:
    from floodguard.data import gee, sar_geometry

    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        raise ValueError(f"({lon}, {lat}) is not a longitude/latitude")
    if not 0 < radius_km <= 25:
        raise ValueError("radius_km must be between 0 and 25 km")
    (pre_s, pre_e), (post_s, post_e) = windows(event_date, pre_days, post_days)

    ee = gee.initialise(project)
    point = ee.Geometry.Point([lon, lat])
    aoi = point.buffer(radius_km * 1000.0).bounds()

    pre = gee.sentinel1_collection(aoi, pre_s, pre_e, polarisation)
    post = gee.sentinel1_collection(aoi, post_s, post_e, polarisation)
    scenes = {"pre": _scene_list(pre), "post": _scene_list(post)}
    for name, lst, (s, e) in (("before", scenes["pre"], (pre_s, pre_e)),
                              ("after", scenes["post"], (post_s, post_e))):
        if not lst:
            raise ValueError(
                f"no Sentinel-1 {polarisation} IW scene covers this point {name} the event "
                f"({s} to {e}); widen the window"
            )

    def water(col):
        img = col.select(polarisation).mosaic().clip(aoi)
        t, method = gee.water_threshold(img, polarisation, aoi, scale_m)
        return img.lt(t), t, method, col.select("imaged").max().unmask(0).clip(aoi)

    w_pre, t_pre, m_pre, im_pre = water(pre)
    w_post, t_post, m_post, im_post = water(post)
    both = im_pre.And(im_post)
    permanent = gee.permanent_water_mask()

    new = w_post.And(w_pre.Not()).And(permanent.Not()).And(both)
    lost = w_pre.And(w_post.Not()).And(both)
    cls = new.multiply(1).add(lost.multiply(2)).selfMask().rename("label").toInt()

    area_img = ee.Image.pixelArea()
    # No bestEffort anywhere below: it silently coarsens the scale, which on the
    # South Lhonak test dropped the vectorised area from 92.8 to 9.7 ha.
    sums = ee.Image.cat(
        new.selfMask().multiply(area_img).rename("new"),
        lost.selfMask().multiply(area_img).rename("lost"),
        w_pre.And(both).selfMask().multiply(area_img).rename("water_before"),
        w_post.And(both).selfMask().multiply(area_img).rename("water_after"),
    ).reduceRegion(ee.Reducer.sum(), aoi, scale_m, maxPixels=1e10)
    fractions = ee.Image.cat(im_pre.rename("pre"), im_post.rename("post"), both.rename("both")) \
        .reduceRegion(ee.Reducer.mean(), aoi, scale_m * 3, maxPixels=1e9, bestEffort=True)

    vectors = cls.reduceToVectors(
        geometry=aoi, scale=scale_m, geometryType="polygon", eightConnected=True,
        labelProperty="label", maxPixels=1e10,
    )
    total = vectors.size()

    def with_area(f):
        g = f.geometry()
        c = g.centroid(1)
        xy = c.coordinates()
        return f.set({"area_m2": g.area(1), "cx": xy.get(0), "cy": xy.get(1),
                      "dist_m": c.distance(point, 1)})

    top = vectors.map(with_area).sort("area_m2", False).limit(max_candidates)
    dem = gee.copernicus_dem()
    stats_img = dem.rename("DEM").addBands(ee.Terrain.slope(dem).rename("slope"))
    dem_stats = stats_img.select("DEM").reduceRegions(
        collection=top, reducer=ee.Reducer.percentile([10, 50, 90]), scale=30)
    full = stats_img.select("slope").reduceRegions(
        collection=dem_stats, reducer=ee.Reducer.mean().setOutputs(["slope_mean"]), scale=30)

    info = ee.Dictionary({
        "sums": sums, "fractions": fractions, "total": total,
        "t_pre": t_pre, "t_post": t_post, "m_pre": m_pre, "m_post": m_post,
    }).getInfo()
    # A FeatureCollection nested in a Dictionary comes back without its
    # features, so it is fetched on its own.
    features = full.getInfo().get("features", [])

    candidates = [candidate_from_feature(_rename_percentiles(f)) for f in features]
    s = info["sums"] or {}
    fr = info["fractions"] or {}
    warnings: list[str] = []
    for which in ("m_pre", "m_post"):
        if "whole area" in info[which]:
            warnings.append(f"{'Before' if which == 'm_pre' else 'After'} the event: "
                            + info[which] + ".")
    warnings.append(
        "Radar-dark ground that is not open water — wet snow, a freshly drained and "
        "still-wet lake bed, smooth sediment — can be classed as water. On the South "
        "Lhonak 2023 test the drained bed kept most of the post-event 'water' area, "
        "so LOST water there is an underestimate."
    )
    if fr.get("both") is not None and fr["both"] < 1.0:
        warnings.append(
            f"Only {fr['both']:.0%} of the area was imaged in both windows; the rest was in "
            f"layover or radar shadow in every scene of a window and is UNOBSERVED, not dry."
        )
    if int(info["total"]) > len(candidates):
        warnings.append(
            f"{int(info['total'])} separate changed patches were found; the "
            f"{len(candidates)} largest are listed. The totals above count every patch. A "
            f"changed area that breaks into many patches (e.g. a drained lake bed left "
            f"partly wet) is common; small isolated patches can also be residual speckle."
        )

    return LakeCheck(
        point=(lon, lat),
        event_date=event_date,
        radius_km=radius_km,
        pre_window=(pre_s, pre_e),
        post_window=(post_s, post_e),
        scenes=scenes,
        thresholds_db={"pre": _f(info["t_pre"]), "post": _f(info["t_post"])},
        imaged_fraction={k: _f(fr.get(k)) for k in ("pre", "post", "both")},
        new_water_km2=_km2(s.get("new")),
        lost_water_km2=_km2(s.get("lost")),
        water_before_km2=_km2(s.get("water_before")),
        water_after_km2=_km2(s.get("water_after")),
        candidates=candidates,
        candidates_total=int(info["total"]),
        warnings=warnings,
        provenance={
            "sentinel1_collection": gee.S1_GRD,
            "polarisation": polarisation,
            "speckle_filter": "local-statistics Lee, 5x5, in linear power",
            "geometry_masks": sar_geometry.REFERENCE,
            "threshold": "per window: " + gee.EDGE_OTSU_REFERENCE + "; " + OTSU_REFERENCE,
            "threshold_method": {"pre": info["m_pre"], "post": info["m_post"]},
            "permanent_water": f"{gee.JRC_GSW} occurrence > {gee.PERMANENT_WATER_OCCURRENCE}% "
                               "(excluded from new water only)",
            "dem": gee.COP_DEM,
            "scale_m": scale_m,
            "windows_note": "window end dates are exclusive",
        },
    )


def _rename_percentiles(feature: dict[str, Any]) -> dict[str, Any]:
    p = feature.get("properties", {})
    for k in ("p10", "p50", "p90"):
        if k in p:
            p[f"DEM_{k}"] = p.pop(k)
    return feature


def _scene_list(col) -> list[dict[str, Any]]:
    import ee

    info = ee.Dictionary({
        "id": col.aggregate_array("system:index"),
        "t": col.aggregate_array("system:time_start"),
        "pass": col.aggregate_array("orbitProperties_pass"),
    }).getInfo()
    from datetime import datetime

    return [
        {"id": i, "utc": datetime.fromtimestamp(t / 1000, tz=UTC).isoformat(timespec="minutes"),
         "pass": ps}
        for i, t, ps in zip(info["id"], info["t"], info["pass"], strict=True)
    ]


def _f(v) -> float | None:
    return float(v) if v is not None else None


def _km2(v) -> float | None:
    return float(v) / 1e6 if v is not None else None
