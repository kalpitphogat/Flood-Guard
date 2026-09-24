"""ESA WorldCover 10 m land cover, read directly onto the DEM grid.

Land cover does two jobs downstream: it turns Manning's n from one hidden
constant into a mapped field (friction is the second most sensitive parameter
after resolution), and it measures the cropland inside the flood extent for
the HADR loss-and-damage table.

WorldCover is published as Cloud-Optimised GeoTIFFs on a keyless public S3
bucket, in 3 x 3 degree tiles of ~100-400 MB each. Rather than download whole
tiles for a corridor that covers a few percent of them, this reads only the
window it needs over HTTP range requests and resamples it straight onto the
compute grid with the MODE of the 10 m classes — a categorical raster must
never be averaged, because the mean of "forest" and "water" is not a class.

Zanaga, D. et al. (2022) ESA WorldCover 10 m 2021 v200.
https://doi.org/10.5281/zenodo.7254221 — licence CC-BY 4.0.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

WORLDCOVER_URL = (
    "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
    "ESA_WorldCover_10m_2021_v200_{tile}_Map.tif"
)
WORLDCOVER_LICENCE = (
    "ESA WorldCover 10 m 2021 v200, © ESA WorldCover project 2022, contains modified "
    "Copernicus Sentinel data (2021) processed by the ESA WorldCover consortium. CC-BY 4.0."
)
WORLDCOVER_CITATION = "Zanaga et al. (2022), https://doi.org/10.5281/zenodo.7254221"


def tile_name(lat: int, lon: int) -> str:
    """WorldCover tiles are named by their south-west corner on a 3-degree grid."""
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return f"{ns}{abs(lat):02d}{ew}{abs(lon):03d}"


def tiles_for_bbox(bbox: tuple[float, float, float, float]) -> list[str]:
    west, south, east, north = bbox
    lats = range(int(math.floor(south / 3) * 3), int(math.floor(north / 3) * 3) + 1, 3)
    lons = range(int(math.floor(west / 3) * 3), int(math.floor(east / 3) * 3) + 1, 3)
    return [tile_name(lat, lon) for lat in lats for lon in lons]


def fetch_onto_grid(
    dem_path: Path,
    out_path: Path,
    *,
    urls: list[str] | None = None,
) -> dict:
    """Resample WorldCover onto the DEM's grid (same CRS, transform and shape).

    Returns a summary with the tiles read and the class histogram. Raises if
    nothing could be read — the caller records that as a skipped layer rather
    than inventing land cover.
    """
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.warp import reproject, transform_bounds

    with rasterio.open(dem_path) as dem:
        profile = dem.profile
        dst_transform, dst_crs = dem.transform, dem.crs
        shape = (dem.height, dem.width)
        bbox = transform_bounds(dem.crs, "EPSG:4326", *dem.bounds, densify_pts=21)

    tiles = tiles_for_bbox(bbox)
    urls = urls or [WORLDCOVER_URL.format(tile=t) for t in tiles]

    out = np.zeros(shape, dtype=np.uint8)  # 0 = no data in WorldCover
    read: list[str] = []
    failures: list[str] = []
    env = {
        "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
        "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif",
        "GDAL_HTTP_MAX_RETRY": "3",
        "GDAL_HTTP_RETRY_DELAY": "2",
    }
    with rasterio.Env(**env):
        for url in urls:
            try:
                with rasterio.open(f"/vsicurl/{url}") as src:
                    part = np.zeros(shape, dtype=np.uint8)
                    reproject(
                        source=rasterio.band(src, 1),
                        destination=part,
                        dst_transform=dst_transform,
                        dst_crs=dst_crs,
                        resampling=Resampling.mode,
                        src_nodata=0,
                        dst_nodata=0,
                    )
                fill = (out == 0) & (part != 0)
                out[fill] = part[fill]
                read.append(url)
            except Exception as exc:  # noqa: BLE001 - one missing tile (e.g. ocean) is normal
                failures.append(f"{url}: {exc}")
                log.warning("WorldCover tile unreadable: %s (%s)", url, exc)

    if not read:
        raise RuntimeError(
            "no WorldCover tile could be read for this area: " + "; ".join(failures)
        )

    profile.update(dtype="uint8", nodata=0, count=1, compress="deflate", predictor=1)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(out, 1)
        dst.update_tags(
            source="ESA WorldCover 10 m 2021 v200",
            resampling="mode (categorical)",
            licence=WORLDCOVER_LICENCE,
            citation=WORLDCOVER_CITATION,
            tiles=",".join(read),
        )

    codes, counts = np.unique(out, return_counts=True)
    return {
        "path": str(out_path),
        "tiles": read,
        "failures": failures,
        "coverage_fraction": float((out != 0).mean()),
        "histogram": {int(c): int(n) for c, n in zip(codes, counts)},
    }
