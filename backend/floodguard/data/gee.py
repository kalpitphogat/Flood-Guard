"""Near-real-time flood mapping from Sentinel-1 via Google Earth Engine.

What this does
--------------
Detects open water from Sentinel-1 SAR backscatter, which works through cloud
and at night — the conditions a flood actually happens in, and the reason
optical imagery is useless for the first 48 hours of most events.

The method is the standard one, with the corrections that matter:

1. **Pre/post change detection.** Water is a specular reflector: it scatters
   radar energy away from the sensor, so flooded ground appears very dark.
   Comparing against a pre-event baseline separates new water from ground that
   is simply smooth.
2. **Refined Lee speckle filtering.** SAR speckle is multiplicative noise; an
   unfiltered threshold produces salt-and-pepper "flooding" everywhere.
3. **Otsu thresholding**, computed per scene rather than fixed. The land/water
   backscatter split moves with incidence angle, season and land cover, so a
   hardcoded dB threshold is wrong somewhere.
4. **Permanent water excluded** using the JRC Global Surface Water occurrence
   layer. Without this, every river and reservoir in the scene is reported as
   flooding, which inflates the detected area enormously.
5. **Layover and shadow masked per scene** (floodguard/data/sar_geometry.py,
   Vollrath et al. 2020 geometric masks), from each scene's own incidence-angle
   band and look direction, BEFORE the threshold. Radar shadow on a steep slope
   is as dark as water and is the dominant false positive in Himalayan terrain.
   The fraction of the area the radar could actually image is reported.

Honest status
-------------
This module is inert without credentials. `GOOGLE_APPLICATION_CREDENTIALS` must
point at a service-account key with Earth Engine access. When it is absent,
`initialise()` raises `GEEUnavailable` and the Real-time Monitoring page shows
a clearly-labelled "not configured" state. It never shows a cached result
dressed up as a live feed.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

#: Earth Engine collection ids, pinned so a silent upstream rename is visible.
S1_GRD = "COPERNICUS/S1_GRD"
S2_SR = "COPERNICUS/S2_SR_HARMONIZED"
JRC_GSW = "JRC/GSW1_4/GlobalSurfaceWater"
#: GLO30 was superseded in Earth Engine by the 2024_1 release (same DEM band);
#: the old id raises a deprecation warning.
COP_DEM = "COPERNICUS/DEM/GLO30_2024_1"
CHIRPS = "UCSB-CHG/CHIRPS/DAILY"

#: JRC occurrence above this percentage counts as permanent water.
PERMANENT_WATER_OCCURRENCE = 50



class GEEUnavailable(RuntimeError):
    """Earth Engine is not usable here. Carries the reason, for the UI."""


@dataclass
class FloodDetection:
    """A detected flood extent and everything needed to judge it."""

    aoi: tuple[float, float, float, float]
    pre_window: tuple[str, str]
    post_window: tuple[str, str]
    polarisation: str
    threshold_db: float
    threshold_method: str
    flooded_area_km2: float | None
    permanent_water_area_km2: float | None
    scene_counts: dict[str, int]
    geojson: dict[str, Any] | None = None
    rainfall_mm: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "aoi": list(self.aoi),
            "pre_window": list(self.pre_window),
            "post_window": list(self.post_window),
            "polarisation": self.polarisation,
            "threshold_db": self.threshold_db,
            "threshold_method": self.threshold_method,
            "flooded_area_km2": self.flooded_area_km2,
            "permanent_water_area_km2": self.permanent_water_area_km2,
            "scene_counts": self.scene_counts,
            "rainfall_mm": self.rainfall_mm,
            "warnings": self.warnings,
            "provenance": self.provenance,
        }


#: The repository's .env (git-ignored). Read as a fallback so the CLI and the
#: API see the same Earth Engine settings without exporting variables by hand.
_DOTENV = Path(__file__).resolve().parents[3] / ".env"


def _setting(name: str) -> str:
    """An environment variable, else the same key in the repository's .env."""
    value = os.environ.get(name, "").strip()
    if value or not _DOTENV.is_file():
        return value
    try:
        for line in _DOTENV.read_text(encoding="utf-8").splitlines():
            key, sep, raw = line.partition("=")
            if sep and key.strip() == name and not key.strip().startswith("#"):
                return raw.strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def credentials_path() -> str | None:
    path = _setting("GOOGLE_APPLICATION_CREDENTIALS")
    return path if path and Path(path).exists() else None


def project_id() -> str | None:
    """The Google Cloud project registered for Earth Engine (EE_PROJECT)."""
    return _setting("EE_PROJECT") or None


def is_configured() -> bool:
    """Whether a GEE run could even be attempted here."""
    import importlib.util

    return importlib.util.find_spec("ee") is not None and credentials_path() is not None


def status() -> dict[str, Any]:
    """What the Real-time Monitoring page shows before anything is run."""
    import importlib.util

    has_package = importlib.util.find_spec("ee") is not None
    has_credentials = credentials_path() is not None

    if has_package and has_credentials:
        detail = "Earth Engine is configured; live Sentinel-1 detection is available."
    elif not has_package:
        detail = (
            "The earthengine-api package is not installed. "
            "Install it with `pip install earthengine-api`."
        )
    else:
        detail = (
            "GOOGLE_APPLICATION_CREDENTIALS is not set, or points at a file that does "
            "not exist. Supply a service-account key with Earth Engine access. Until "
            "then no live detection runs, and nothing on this page is a live feed."
        )

    return {
        "configured": has_package and has_credentials,
        "package_installed": has_package,
        "credentials_present": has_credentials,
        "project": project_id(),
        "detail": detail,
        "collections": {
            "sentinel1": S1_GRD,
            "permanent_water": JRC_GSW,
            "dem": COP_DEM,
            "rainfall": CHIRPS,
        },
    }


def initialise(project: str | None = None):
    """Authenticate and initialise Earth Engine, or say exactly why not."""
    try:
        import ee
    except ImportError as exc:
        raise GEEUnavailable(
            "the earthengine-api package is not installed (pip install earthengine-api)"
        ) from exc

    key = credentials_path()
    if key is None:
        raise GEEUnavailable(
            "GOOGLE_APPLICATION_CREDENTIALS is not set or does not point at an existing "
            "file. A service-account key with Earth Engine access is required."
        )

    try:
        import json

        with open(key, encoding="utf-8") as fh:
            service_account = json.load(fh).get("client_email")
        credentials = ee.ServiceAccountCredentials(service_account, key)
        ee.Initialize(credentials, project=project or project_id())
    except Exception as exc:  # noqa: BLE001
        raise GEEUnavailable(f"Earth Engine initialisation failed: {exc}") from exc

    return ee


# --- image processing --------------------------------------------------------------


def refined_lee(image, kernel_size: int = 5):
    """Refined Lee speckle filter.

    SAR speckle is multiplicative. Thresholding an unfiltered image produces
    isolated dark pixels scattered across dry land, which then appear as
    speckled "flooding". The refined Lee filter smooths homogeneous regions
    while preserving edges, which is what keeps a flood boundary sharp.

    Implemented as the standard local-statistics form; for a production system
    the full directional-window variant is worth the extra complexity.
    """
    import ee

    band = image.bandNames().get(0)
    # Speckle is MULTIPLICATIVE in linear power, so the local statistics must be
    # taken there; the collection is in dB (10*log10), so convert, filter, convert
    # back. Filtering dB values directly biases the result.
    img = ee.Image(10.0).pow(image.select([band]).divide(10.0))
    kernel = ee.Kernel.square(kernel_size, "pixels")

    mean = img.reduceNeighborhood(ee.Reducer.mean(), kernel)
    variance = img.reduceNeighborhood(ee.Reducer.variance(), kernel)

    # Equivalent number of looks for Sentinel-1 IW GRD.
    enl = 4.4
    ci2 = variance.divide(mean.multiply(mean))
    cu2 = ee.Image(1.0 / enl)
    weight = ci2.subtract(cu2).divide(ci2).max(0)

    filtered = mean.add(weight.multiply(img.subtract(mean)))
    return filtered.log10().multiply(10.0).rename([band])


def permanent_water_mask():
    """JRC Global Surface Water: occurrence above 50% is permanent water.

    Without this every river, canal and reservoir in the scene is reported as
    flooding. On the Ganga corridor that is a very large number.
    """
    import ee

    # `occurrence` is MASKED wherever water was never observed. Without unmask(0)
    # "not permanent water" is masked on all dry land, and any And() with it
    # silently limited detection to ground that had been water before (found on
    # the South Lhonak test: new-water area collapsed to the old lake footprint).
    return (
        ee.Image(JRC_GSW).select("occurrence").unmask(0)
        .gt(PERMANENT_WATER_OCCURRENCE).rename("occurrence")
    )


def otsu_threshold(histogram):
    """Otsu's method: the backscatter value that best splits land from water.

    Computed per scene rather than fixed, because the split moves with
    incidence angle, season, land cover and sensor calibration. A hardcoded
    -15 dB is right somewhere and wrong everywhere else.
    """
    import ee

    counts = ee.Array(ee.Dictionary(histogram).get("histogram"))
    means = ee.Array(ee.Dictionary(histogram).get("bucketMeans"))
    size = means.length().get([0])
    total = counts.reduce(ee.Reducer.sum(), [0]).get([0])
    sums = means.multiply(counts).reduce(ee.Reducer.sum(), [0]).get([0])
    mean = sums.divide(total)

    indices = ee.List.sequence(1, size)

    def between_class_variance(i):
        a_counts = counts.slice(0, 0, i)
        a_count = a_counts.reduce(ee.Reducer.sum(), [0]).get([0])
        a_means = means.slice(0, 0, i)
        a_mean = (
            a_means.multiply(a_counts).reduce(ee.Reducer.sum(), [0]).get([0]).divide(a_count)
        )
        b_count = total.subtract(a_count)
        b_mean = sums.subtract(a_count.multiply(a_mean)).divide(b_count)
        return a_count.multiply(a_mean.subtract(mean).pow(2)).add(
            b_count.multiply(b_mean.subtract(mean).pow(2))
        )

    variances = indices.map(between_class_variance)
    best = ee.List(variances).indexOf(ee.List(variances).reduce(ee.Reducer.max()))
    return means.sort().get([best])


def copernicus_dem():
    """Copernicus GLO-30 as one image, keeping its native 30 m projection.

    A mosaic otherwise falls back to a default 1-degree projection, and slope
    and aspect computed from it would be computed on the wrong grid.
    """
    import ee

    col = ee.ImageCollection(COP_DEM).select("DEM")
    return col.mosaic().setDefaultProjection(col.first().projection())


#: Half-width of the band around the historical water edge (JRC max_extent) in
#: which the Otsu histogram is taken, m. A FloodGuard choice, not a published
#: value; on the South Lhonak test the threshold moved only 0.4 dB between 100,
#: 200 and 400 m (-13.1 / -13.5 / -13.1 dB), so the result is not tuned by it.
EDGE_BUFFER_M = 200.0
#: Fewest edge-band pixels for a usable histogram (a numerical minimum).
MIN_EDGE_PIXELS = 100
EDGE_OTSU_REFERENCE = (
    "Otsu (1979) on a band around the known water edge, after Donchyts et al. "
    "(2016), Remote Sensing 8(5):386 — a whole-scene histogram fails when water "
    "is a small fraction of the scene"
)


def water_threshold(image, band: str, aoi, scale_m: float):
    """Otsu threshold taken near the historical water edge; whole AOI as fallback.

    Returns (threshold ee.Number, method ee.String). Otsu assumes two classes of
    comparable size; over a whole valley water is a few percent of the pixels
    and the split lands inside the land distribution (South Lhonak: -10.7 dB
    over the box vs -13.5 dB near the shore; lake mean -17.8, land -9.4 dB).
    """
    import ee

    ever = ee.Image(JRC_GSW).select("max_extent").unmask(0).clip(aoi)
    edge = ever.focalMax(1).subtract(ever.focalMin(1)).gt(0)
    band_mask = edge.focalMax(EDGE_BUFFER_M, "circle", "meters")
    near = image.select([band]).updateMask(band_mask)
    count = ee.Number(
        near.reduceRegion(ee.Reducer.count(), aoi, scale_m, maxPixels=1e9).get(band)
    )

    def otsu(img):
        hist = img.reduceRegion(ee.Reducer.histogram(255, 0.1), aoi, scale_m,
                                maxPixels=1e9).get(band)
        return ee.Number(otsu_threshold(hist))

    use_edge = count.gte(MIN_EDGE_PIXELS)
    threshold = ee.Number(ee.Algorithms.If(use_edge, otsu(near), otsu(image.select([band]))))
    method = ee.String(ee.Algorithms.If(
        use_edge,
        f"Otsu within {EDGE_BUFFER_M:.0f} m of the historical water edge",
        "Otsu over the whole area (no historical water edge nearby) — may split land "
        "from land where water is a small fraction",
    ))
    return threshold, method


def sentinel1_collection(aoi, start: str, end: str, polarisation: str = "VV"):
    """Sentinel-1 GRD IW scenes over an AOI: speckle-filtered, layover/shadow masked.

    Each scene is masked with its OWN geometry before any mosaic, because an
    ascending and a descending scene see opposite slopes in shadow.
    """
    import ee

    from floodguard.data import sar_geometry

    dem = copernicus_dem()

    def prepare(image):
        filtered = refined_lee(image.select([polarisation]))
        geom = sar_geometry.geometry_bands(image, dem, aoi)
        return (
            filtered.updateMask(geom.select("valid"))
            .addBands(geom.select("valid").unmask(0).rename("imaged"))
            .copyProperties(image, ["system:time_start", "system:index", "orbitProperties_pass"])
        )

    collection = (
        ee.ImageCollection(S1_GRD)
        .filterBounds(aoi)
        .filterDate(start, end)
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", polarisation))
        .filter(ee.Filter.eq("instrumentMode", "IW"))
    )
    return collection.map(prepare)


def detect_flood(
    aoi_bbox: tuple[float, float, float, float],
    post_start: str,
    post_end: str,
    *,
    pre_start: str | None = None,
    pre_end: str | None = None,
    polarisation: str = "VV",
    threshold_db: float | None = None,
    scale_m: int = 30,
    project: str | None = None,
) -> FloodDetection:
    """Detect flood extent over an AOI from Sentinel-1.

    Returns the extent as GeoJSON plus the numbers needed to judge it. Raises
    `GEEUnavailable` when Earth Engine is not configured — it never returns a
    cached or synthetic extent in its place.
    """
    ee = initialise(project)

    west, south, east, north = aoi_bbox
    aoi = ee.Geometry.Rectangle([west, south, east, north])

    # Default pre-event baseline: the 45 days before the post window.
    if pre_start is None or pre_end is None:
        post_start_date = date.fromisoformat(post_start)
        pre_end = (post_start_date - timedelta(days=1)).isoformat()
        pre_start = (post_start_date - timedelta(days=46)).isoformat()

    pre = sentinel1_collection(aoi, pre_start, pre_end, polarisation)
    post = sentinel1_collection(aoi, post_start, post_end, polarisation)

    pre_count = int(pre.size().getInfo())
    post_count = int(post.size().getInfo())

    warnings: list[str] = []
    if post_count == 0:
        raise GEEUnavailable(
            f"No Sentinel-1 {polarisation} IW scenes intersect this AOI between "
            f"{post_start} and {post_end}. Widen the date range: the revisit interval "
            f"is 6-12 days depending on how many satellites cover the area."
        )
    if pre_count == 0:
        warnings.append(
            f"No pre-event scenes between {pre_start} and {pre_end}, so change detection "
            f"is unavailable and the result is a single-date threshold. That cannot "
            f"distinguish new flooding from ground that is simply smooth, so treat the "
            f"extent as an upper bound."
        )

    post_image = post.select(polarisation).mosaic().clip(aoi)
    imaged_fraction = _imaged_fraction(post, aoi, scale_m)

    # Otsu on the post-event image unless the caller pinned a threshold.
    if threshold_db is None:
        threshold, method = water_threshold(post_image, polarisation, aoi, scale_m)
        threshold_method = method.getInfo()
    else:
        threshold = ee.Number(threshold_db)
        threshold_method = f"fixed at {threshold_db} dB by request"

    water = post_image.lt(threshold)

    if pre_count > 0:
        # Change detection: water now that was not water before.
        pre_image = pre.select(polarisation).mosaic().clip(aoi)
        was_water = pre_image.lt(threshold)
        water = water.And(was_water.Not())

    water = water.And(permanent_water_mask().Not())
    # Layover/shadow are already masked per scene (sentinel1_collection): a
    # pixel no scene could image stays masked, never "dry".
    water = water.selfMask().rename("flooded")

    pixel_area = ee.Image.pixelArea()
    flooded_area = (
        water.multiply(pixel_area)
        .reduceRegion(ee.Reducer.sum(), aoi, scale_m, maxPixels=1e10, bestEffort=True)
        .get("flooded")
    )
    permanent_area = (
        permanent_water_mask().selfMask().multiply(pixel_area)
        .reduceRegion(ee.Reducer.sum(), aoi, scale_m, maxPixels=1e10, bestEffort=True)
        .get("occurrence")
    )

    vectors = water.reduceToVectors(
        geometry=aoi,
        scale=scale_m,
        geometryType="polygon",
        maxPixels=1e9,
        bestEffort=True,
    )

    try:
        geojson = vectors.getInfo()
    except Exception as exc:  # noqa: BLE001
        geojson = None
        warnings.append(f"the flood extent could not be vectorised: {exc}")

    rainfall = _rainfall_series(ee, aoi, pre_start, post_end)
    if imaged_fraction is not None and imaged_fraction < 1.0:
        warnings.append(
            f"The radar could image {imaged_fraction:.0%} of this area in the post-event "
            f"scenes; the rest was in layover or radar shadow in every scene. Water there "
            f"is UNOBSERVED, not absent."
        )

    from floodguard.data import sar_geometry

    return FloodDetection(
        aoi=aoi_bbox,
        pre_window=(pre_start, pre_end),
        post_window=(post_start, post_end),
        polarisation=polarisation,
        threshold_db=float(threshold.getInfo()),
        threshold_method=threshold_method,
        flooded_area_km2=(float(flooded_area.getInfo()) / 1e6) if flooded_area else None,
        permanent_water_area_km2=(
            (float(permanent_area.getInfo()) / 1e6) if permanent_area else None
        ),
        scene_counts={"pre": pre_count, "post": post_count},
        geojson=geojson,
        rainfall_mm=rainfall,
        warnings=warnings,
        provenance={
            "sentinel1_collection": S1_GRD,
            "permanent_water": f"{JRC_GSW} occurrence > {PERMANENT_WATER_OCCURRENCE}%",
            "dem": COP_DEM,
            "speckle_filter": "refined Lee, 5x5",
            "terrain_mask": "per-scene layover/shadow masks: " + sar_geometry.REFERENCE,
            "imaged_fraction_post": imaged_fraction,
            "scale_m": scale_m,
            "method": (
                "pre/post change detection on speckle-filtered Sentinel-1 backscatter, "
                "Otsu threshold, permanent water excluded, layover/shadow masked per scene"
            ),
        },
    )


def _imaged_fraction(collection, aoi, scale_m: float) -> float | None:
    """Share of the AOI that at least one scene imaged (not layover/shadow)."""
    import ee

    try:
        value = (
            collection.select("imaged").max().unmask(0).clip(aoi)
            .reduceRegion(ee.Reducer.mean(), aoi, max(scale_m, 30) * 3, maxPixels=1e9,
                          bestEffort=True)
            .get("imaged").getInfo()
        )
    except Exception:  # noqa: BLE001
        return None
    return float(value) if value is not None else None


def _rainfall_series(ee, aoi, start: str, end: str) -> list[dict[str, Any]]:
    """Daily CHIRPS rainfall over the AOI, for the cause alongside the effect."""
    try:
        collection = ee.ImageCollection(CHIRPS).filterBounds(aoi).filterDate(start, end)

        def reduce_day(image):
            value = image.reduceRegion(
                ee.Reducer.mean(), aoi, 5000, maxPixels=1e9, bestEffort=True
            ).get("precipitation")
            return ee.Feature(None, {"date": image.date().format("YYYY-MM-dd"), "mm": value})

        rows = collection.map(reduce_day).getInfo()["features"]
        return [
            {"date": f["properties"]["date"], "mm": f["properties"].get("mm")}
            for f in rows
        ]
    except Exception as exc:  # noqa: BLE001 - rainfall is a nice-to-have
        log.warning("CHIRPS rainfall unavailable: %s", exc)
        return []


def agreement_with_simulation(
    detection: FloodDetection,
    simulated_depth_path: Path,
    wet_threshold_m: float = 0.3,
) -> dict[str, Any]:
    """Compare a detected extent against a simulated one.

    This is the strongest validation the project can offer: the model against
    what a satellite actually saw. The metrics are the same contingency
    statistics used for engine-vs-engine comparison, and POD and FAR are
    reported alongside CSI because CSI alone misleads when the two extents
    differ mostly in size.

    Whatever it comes out as is reported. A poor score with an explanation is
    worth more than a good score nobody can reproduce.
    """
    import geopandas as gpd
    import numpy as np
    import rasterio
    from rasterio.features import rasterize

    if detection.geojson is None:
        return {
            "computed": False,
            "reason": "the detected extent was not vectorised, so no overlap can be computed",
        }

    with rasterio.open(simulated_depth_path) as src:
        simulated = src.read(1) >= wet_threshold_m
        transform = src.transform
        crs = src.crs
        shape = simulated.shape
        cell_area = abs(src.transform.a * src.transform.e)

    observed_gdf = gpd.GeoDataFrame.from_features(
        detection.geojson["features"], crs="EPSG:4326"
    ).to_crs(crs)

    if observed_gdf.empty:
        return {
            "computed": False,
            "reason": "the detection returned no polygons inside the simulated domain",
        }

    observed = rasterize(
        [(geom, 1) for geom in observed_gdf.geometry],
        out_shape=shape,
        transform=transform,
        dtype="uint8",
    ).astype(bool)

    tp = int(np.sum(observed & simulated))
    fp = int(np.sum(~observed & simulated))
    fn = int(np.sum(observed & ~simulated))
    denom = tp + fp + fn

    return {
        "computed": True,
        "true_positive_km2": tp * cell_area / 1e6,
        "false_positive_km2": fp * cell_area / 1e6,
        "false_negative_km2": fn * cell_area / 1e6,
        "critical_success_index": tp / denom if denom else None,
        "probability_of_detection": tp / (tp + fn) if (tp + fn) else None,
        "false_alarm_ratio": fp / (tp + fp) if (tp + fp) else None,
        "bias": (tp + fp) / (tp + fn) if (tp + fn) else None,
        "interpretation": (
            "Read POD and FAR before CSI. A low CSI with a high POD means the model "
            "flooded everything the satellite saw plus more, so the two extents differ "
            "in size rather than in location. A low POD means the model missed real "
            "flooding, which is the serious failure."
        ),
        "caveats": [
            "Sentinel-1 sees open water. Flooding under a forest canopy or inside a "
            "built-up area is systematically under-detected, so the observed extent is "
            "a lower bound.",
            "The satellite pass is a single instant; the simulated extent is a maximum "
            "over the whole run. Unless the pass caught the peak, the model should "
            "legitimately exceed the observation.",
        ],
    }
