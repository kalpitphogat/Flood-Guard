"""Validation of user-supplied data: DEM, outflow hydrograph, area of interest.

The problem statement asks for a framework that runs on *swappable* input
datasets. That is only useful if a bad file is refused at the door with a
reason, rather than accepted and turned into a confident wrong answer three
stages later. Each validator here returns `issues` (fatal — the file is
refused) and `warnings` (accepted, but the user must read them), and never
repairs a file silently: no CRS is assumed for a raster, no unit is guessed
for a discharge column.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from pathlib import Path
from typing import Any

import numpy as np

#: Loose bounding box of India plus neighbouring basins (Brahmaputra, Indus,
#: Ganga headwaters in Nepal/Tibet). Outside it is allowed, but flagged.
INDIA_REGION = (60.0, 5.0, 100.0, 38.0)

#: Plausible terrain elevation, m. Everest is 8,849 m; the Dead Sea shore is
#: -430 m. A DEM outside this range is almost certainly in the wrong unit
#: (centimetres, feet x 10) or has an undeclared nodata value.
ELEVATION_RANGE_M = (-500.0, 9000.0)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _in_region(bounds: tuple[float, float, float, float]) -> bool:
    w, s, e, n = bounds
    rw, rs, re_, rn = INDIA_REGION
    return not (e < rw or w > re_ or n < rs or s > rn)


# --- DEM --------------------------------------------------------------------------


def validate_dem(path: Path) -> dict[str, Any]:
    """Check a GeoTIFF is a usable elevation model. Never modifies the file."""
    import rasterio
    from rasterio.warp import transform_bounds

    issues: list[str] = []
    warnings: list[str] = []
    meta: dict[str, Any] = {"kind": "dem", "filename": path.name}

    try:
        src = rasterio.open(path)
    except Exception as exc:  # noqa: BLE001
        return {**meta, "ok": False, "issues": [f"not a readable raster: {exc}"], "warnings": []}

    with src:
        meta.update(
            driver=src.driver,
            width=src.width,
            height=src.height,
            bands=src.count,
            dtype=src.dtypes[0],
            nodata=src.nodata,
        )
        if src.count < 1:
            issues.append("the file has no raster band")
        if not np.issubdtype(np.dtype(src.dtypes[0]), np.number):
            issues.append(f"band type {src.dtypes[0]} is not numeric")

        if src.crs is None:
            issues.append(
                "the raster has no coordinate reference system. FloodGuard will not "
                "assume one: a guessed CRS puts the flood in the wrong valley. Re-export "
                "it with its CRS (e.g. EPSG:4326 or the UTM zone) embedded."
            )
        if src.transform.is_identity:
            issues.append("the raster has no geotransform, so it cannot be located on Earth")

        if issues:
            return {**meta, "ok": False, "issues": issues, "warnings": warnings}

        meta["crs"] = src.crs.to_string()
        bounds = transform_bounds(src.crs, "EPSG:4326", *src.bounds, densify_pts=21)
        meta["bounds_wgs84"] = [float(b) for b in bounds]

        if src.crs.is_geographic:
            # Degrees to metres at the raster's mid-latitude.
            lat = 0.5 * (bounds[1] + bounds[3])
            res_x = abs(src.transform.a) * 111_320.0 * np.cos(np.radians(lat))
            res_y = abs(src.transform.e) * 110_574.0
        else:
            unit = (src.crs.linear_units or "").lower()
            if unit and unit not in ("metre", "meter", "m"):
                issues.append(
                    f"the CRS's linear unit is {unit!r}, not metres. Reproject to a metric "
                    f"CRS before upload."
                )
            res_x, res_y = abs(src.transform.a), abs(src.transform.e)
        meta["resolution_m"] = float(0.5 * (res_x + res_y))

        # Statistics on a decimated read, so a 1 GB DEM does not load whole.
        step = max(1, int(np.ceil(max(src.width, src.height) / 2048)))
        data = src.read(
            1,
            out_shape=(max(src.height // step, 1), max(src.width // step, 1)),
            masked=True,
        )
        values = np.asarray(data.filled(np.nan), dtype=np.float64)
        values[values < -1e4] = np.nan  # undeclared fill values such as -32768
        finite = np.isfinite(values)
        meta["nodata_fraction"] = float(1.0 - finite.mean())
        if not finite.any():
            issues.append("every sampled cell is nodata")
            return {**meta, "ok": False, "issues": issues, "warnings": warnings}

        lo, hi = float(np.nanmin(values)), float(np.nanmax(values))
        meta["elevation_min_m"] = lo
        meta["elevation_max_m"] = hi
        if lo < ELEVATION_RANGE_M[0] or hi > ELEVATION_RANGE_M[1]:
            issues.append(
                f"elevations run from {lo:,.1f} to {hi:,.1f}, outside the physically "
                f"plausible {ELEVATION_RANGE_M[0]:,.0f} to {ELEVATION_RANGE_M[1]:,.0f} m. "
                f"The file is probably in centimetres or feet, or has an undeclared "
                f"nodata value."
            )

    if meta["resolution_m"] > 250:
        issues.append(
            f"resolution is {meta['resolution_m']:.0f} m. A dam-break wave in a valley "
            f"a few hundred metres wide cannot be resolved coarser than ~250 m."
        )
    elif meta["resolution_m"] < 2:
        warnings.append(
            f"resolution is {meta['resolution_m']:.2f} m; it will be resampled to the "
            f"scenario's compute resolution, so the extra detail is not used by the solver."
        )
    if meta["nodata_fraction"] > 0.2:
        warnings.append(
            f"{meta['nodata_fraction']:.0%} of the raster is nodata. Voids inside the "
            f"flood corridor are treated as inactive cells, i.e. as walls."
        )
    if not _in_region(tuple(meta["bounds_wgs84"])):
        warnings.append("the DEM lies outside the Indian subcontinent region")

    meta["sha256"] = sha256_of(path)
    return {**meta, "ok": not issues, "issues": issues, "warnings": warnings}


def dem_covers(meta: dict[str, Any], lon: float, lat: float) -> bool:
    """Whether a validated DEM contains a point (e.g. the dam)."""
    w, s, e, n = meta.get("bounds_wgs84") or (0, 0, 0, 0)
    return w <= lon <= e and s <= lat <= n


# --- hydrograph ------------------------------------------------------------------

_TIME_UNITS = {
    "s": 1.0, "sec": 1.0, "secs": 1.0, "second": 1.0, "seconds": 1.0,
    "min": 60.0, "mins": 60.0, "minute": 60.0, "minutes": 60.0,
    "h": 3600.0, "hr": 3600.0, "hrs": 3600.0, "hour": 3600.0, "hours": 3600.0,
}
_IMPERIAL = re.compile(r"cfs|ft|feet|cusec", re.IGNORECASE)


def _time_unit(header: str) -> tuple[str, float] | None:
    tokens = re.split(r"[\s_\-\(\)\[\]/,]+", header.lower())
    for token in tokens:
        if token in _TIME_UNITS:
            return token, _TIME_UNITS[token]
    return None


def read_hydrograph_csv(path: Path) -> dict[str, Any]:
    """Parse and validate a two-column outflow hydrograph.

    The time column must declare its unit in the header (`time_s`,
    `time_min`, `time (hours)`...). The discharge column must be in m3/s; a
    header mentioning cfs, cusecs or feet is refused rather than converted,
    because a silent 35x unit error in a flood hydrograph is exactly the kind
    of mistake this tool exists to prevent. Lines starting with `#` are
    comments, so FloodGuard's own exported CSVs round-trip.

    Raises ValueError with every problem found.
    """
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig", errors="replace")
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    if len(lines) < 3:
        raise ValueError("a hydrograph needs a header row and at least two data rows")

    reader = csv.reader(io.StringIO("\n".join(lines)))
    header = [h.strip() for h in next(reader)]
    rows = list(reader)

    problems: list[str] = []
    t_col = next((i for i, h in enumerate(header) if "time" in h.lower()), None)
    q_col = next(
        (
            i for i, h in enumerate(header)
            if re.search(r"discharge|flow|^q\b|q_|outflow", h.lower())
        ),
        None,
    )
    if t_col is None:
        problems.append(f"no time column found in header {header}")
    if q_col is None:
        problems.append(
            f"no discharge column found in header {header} (name it e.g. 'discharge_m3s')"
        )
    if problems:
        raise ValueError("; ".join(problems))

    unit = _time_unit(header[t_col])
    if unit is None:
        # FloodGuard's own export writes both time_s and time_hours.
        if header[t_col].lower() == "time":
            problems.append(
                "the time column does not declare its unit. Name it time_s, time_min or "
                "time_hours; FloodGuard will not guess."
            )
        else:
            problems.append(f"cannot read a time unit from column name {header[t_col]!r}")
    if _IMPERIAL.search(header[q_col]):
        problems.append(
            f"discharge column {header[q_col]!r} looks imperial. Convert to m3/s before "
            f"upload; FloodGuard will not convert units silently."
        )
    if problems:
        raise ValueError("; ".join(problems))

    t_vals: list[float] = []
    q_vals: list[float] = []
    for n, row in enumerate(rows, start=2):
        try:
            t_vals.append(float(row[t_col]))
            q_vals.append(float(row[q_col]))
        except (ValueError, IndexError):
            problems.append(f"row {n}: not numeric ({row})")
            if len(problems) > 5:
                break
    if problems:
        raise ValueError("; ".join(problems))

    t = np.asarray(t_vals, dtype=np.float64) * unit[1]
    q = np.asarray(q_vals, dtype=np.float64)
    if not np.all(np.isfinite(t)) or not np.all(np.isfinite(q)):
        problems.append("time and discharge must be finite numbers")
    if np.any(np.diff(t) <= 0):
        problems.append("time must be strictly increasing")
    if t[0] < 0:
        problems.append("time must start at or after zero")
    if np.any(q < 0):
        problems.append("discharge must be non-negative (m3/s out of the dam)")
    if q.max() <= 0:
        problems.append("the hydrograph releases no water")
    if problems:
        raise ValueError("; ".join(problems))

    return {
        "time_s": t,
        "discharge_m3s": q,
        "time_unit": unit[0],
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def validate_hydrograph(path: Path) -> dict[str, Any]:
    meta: dict[str, Any] = {"kind": "hydrograph", "filename": path.name}
    try:
        parsed = read_hydrograph_csv(path)
    except ValueError as exc:
        return {**meta, "ok": False, "issues": [str(exc)], "warnings": []}

    t, q = parsed["time_s"], parsed["discharge_m3s"]
    warnings: list[str] = []
    if q[0] > 0.05 * q.max():
        warnings.append(
            "the hydrograph starts at a large discharge; the valley is dry at t = 0, so "
            "the first minutes will behave like an instantaneous release"
        )
    if t[-1] < 1800:
        warnings.append("the hydrograph is shorter than 30 minutes")
    volume = float(np.trapezoid(q, t))
    return {
        **meta,
        "ok": True,
        "issues": [],
        "warnings": warnings,
        "rows": int(t.size),
        "duration_hours": float(t[-1] / 3600.0),
        "peak_discharge_m3s": float(q.max()),
        "time_to_peak_min": float(t[int(np.argmax(q))] / 60.0),
        "volume_mcm": volume / 1e6,
        "time_unit": parsed["time_unit"],
        "sha256": parsed["sha256"],
    }


# --- area of interest ------------------------------------------------------------


def validate_aoi(path: Path) -> dict[str, Any]:
    """Read a polygon AOI from GeoJSON, KML or a zipped shapefile.

    A shapefile without its .prj has no CRS and is refused. GeoJSON is
    EPSG:4326 by specification (RFC 7946) and KML by the OGC standard, so
    those are the only formats where a CRS is not required in the file.
    """
    import geopandas as gpd

    meta: dict[str, Any] = {"kind": "aoi", "filename": path.name}
    suffix = path.suffix.lower()
    try:
        if suffix == ".zip":
            gdf = gpd.read_file(f"zip://{path.as_posix()}")
        else:
            gdf = gpd.read_file(path)
    except Exception as exc:  # noqa: BLE001
        return {**meta, "ok": False, "issues": [f"could not read the file: {exc}"], "warnings": []}

    issues: list[str] = []
    warnings: list[str] = []
    if gdf.empty:
        issues.append("the file contains no features")
    if gdf.crs is None:
        if suffix in (".geojson", ".json", ".kml"):
            gdf = gdf.set_crs("EPSG:4326")
            warnings.append(f"{suffix} carries no CRS; EPSG:4326 applied as its standard requires")
        else:
            issues.append(
                "the file has no CRS (a shapefile needs its .prj inside the zip). "
                "FloodGuard will not assume one."
            )
    if issues:
        return {**meta, "ok": False, "issues": issues, "warnings": warnings}

    polys = gdf[gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])]
    if polys.empty:
        return {
            **meta,
            "ok": False,
            "issues": ["no Polygon or MultiPolygon features; an AOI must enclose an area"],
            "warnings": warnings,
        }
    if len(polys) < len(gdf):
        warnings.append(f"{len(gdf) - len(polys)} non-polygon feature(s) ignored")

    polys = polys.to_crs("EPSG:4326")
    polys = polys[polys.geometry.is_valid | polys.geometry.buffer(0).is_valid]
    polys["geometry"] = polys.geometry.buffer(0)
    area_km2 = float(polys.to_crs(polys.estimate_utm_crs()).area.sum() / 1e6)
    bounds = [float(b) for b in polys.total_bounds]
    if not _in_region(tuple(bounds)):
        warnings.append("the AOI lies outside the Indian subcontinent region")

    return {
        **meta,
        "ok": True,
        "issues": [],
        "warnings": warnings,
        "features": int(len(polys)),
        "area_km2": area_km2,
        "bounds_wgs84": bounds,
        "source_crs": str(gdf.crs),
        "geojson": polys[["geometry"]].to_json(),
        "sha256": sha256_of(path),
    }
