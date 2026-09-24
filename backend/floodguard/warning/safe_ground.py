"""Nearest safe ground: where to go, from each town, when the wave comes.

"Safe" is defined from the run itself, not assumed: a cell is safe when it
never flooded AND its ground stands at least `freeboard_m` above the highest
water surface computed at the nearest flooded cell. Staying dry in the model
is not enough on its own — a dry cell one metre above a 40 m flood surface
is on the edge of the modelled extent, not out of danger.

What this is NOT: a route. The distance is a straight line across the grid;
it knows nothing about roads, bridges, slope or whether the path itself
floods first. It is also bounded by the compute domain — high ground outside
the modelled corridor is unknown here, and the answer says so rather than
reporting "none".
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

COMPASS_8 = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def compass(bearing_deg: float) -> str:
    return COMPASS_8[int(((bearing_deg % 360) + 22.5) // 45) % 8]


@dataclass
class SafeGround:
    distance_km: float
    bearing_deg: float
    direction: str
    lon: float
    lat: float
    ground_elevation_m: float
    height_above_flood_m: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "distance_km": round(self.distance_km, 2),
            "bearing_deg": round(self.bearing_deg, 0),
            "direction": self.direction,
            "lon": self.lon,
            "lat": self.lat,
            "ground_elevation_m": round(self.ground_elevation_m, 1),
            "height_above_flood_m": round(self.height_above_flood_m, 1),
        }


def safe_mask(
    depth: np.ndarray,
    bed: np.ndarray,
    wet_threshold_m: float = 0.3,
    freeboard_m: float = 2.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Safe cells, and the flood surface each dry cell was compared against.

    Returns (safe, nearest_surface). Cells with no bed (outside the DEM) are
    never safe: nothing is known about them.
    """
    from scipy.ndimage import distance_transform_edt

    depth = np.nan_to_num(depth, nan=0.0)
    known = np.isfinite(bed)
    wet = (depth >= wet_threshold_m) & known
    surface = np.where(wet, bed + depth, np.nan)
    if not wet.any():
        return np.zeros_like(wet), surface

    # For every cell, the index of the nearest wet cell -> its water surface.
    _, (ri, ci) = distance_transform_edt(~wet, return_indices=True)
    nearest_surface = surface[ri, ci]
    safe = ~wet & known & (bed >= nearest_surface + freeboard_m)
    return safe, nearest_surface


def nearest_safe_ground(
    depth: np.ndarray,
    bed: np.ndarray,
    transform,
    crs: str,
    points: list[tuple[float, float]],
    *,
    wet_threshold_m: float = 0.3,
    freeboard_m: float = 2.0,
) -> list[tuple[SafeGround | None, str]]:
    """For each (lon, lat), the nearest safe cell, or None with the reason."""
    from pyproj import Transformer
    from rasterio.transform import rowcol, xy
    from scipy.ndimage import distance_transform_edt

    safe, nearest_surface = safe_mask(depth, bed, wet_threshold_m, freeboard_m)
    to_grid = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    to_geo = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    cell_x, cell_y = abs(transform.a), abs(transform.e)

    if not safe.any():
        reason = (
            "nothing flooded, so no evacuation target is needed"
            if not np.any(np.nan_to_num(depth) >= wet_threshold_m)
            else "no cell inside the modelled corridor stands clear of the flood by the "
                 "freeboard; high ground outside the corridor is not modelled"
        )
        return [(None, reason) for _ in points]

    dist, (sr, sc) = distance_transform_edt(
        ~safe, sampling=(cell_y, cell_x), return_indices=True
    )
    out: list[tuple[SafeGround | None, str]] = []
    rows, cols = depth.shape
    for lon, lat in points:
        x, y = to_grid.transform(lon, lat)
        r, c = rowcol(transform, x, y)
        if not (0 <= r < rows and 0 <= c < cols):
            out.append((None, "this location lies outside the simulation domain"))
            continue
        tr, tc = int(sr[r, c]), int(sc[r, c])
        tx, ty = xy(transform, tr, tc)
        bearing = math.degrees(math.atan2(tx - x, ty - y)) % 360.0
        slon, slat = to_geo.transform(tx, ty)
        surface = nearest_surface[tr, tc]
        out.append(
            (
                SafeGround(
                    distance_km=float(dist[r, c]) / 1000.0,
                    bearing_deg=bearing,
                    direction=compass(bearing),
                    lon=float(slon),
                    lat=float(slat),
                    ground_elevation_m=float(bed[tr, tc]),
                    height_above_flood_m=float(bed[tr, tc] - surface),
                ),
                "",
            )
        )
    return out
