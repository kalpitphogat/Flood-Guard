"""Results: KPIs, comparison, impact, hydrographs, cross-sections, tiles, exports.

Everything served here is read from a completed run's on-disk artefacts. The
API computes nothing a `floodguard simulate` could not, which is what makes the
dashboard reproducible from the command line.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, Response

from app.core.config import get_settings
from app.schemas.models import (
    BreachComparison,
    BreachPrediction,
    Comparison,
    ComparisonRow,
    CrossSectionResponse,
    EngineSummary,
    ExportListing,
    HydrographResponse,
    HydrographSeries,
    ImpactMetric,
    ImpactResponse,
    ResultSummary,
    TownResult,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/results", tags=["results"])


def run_dir(run_id: str) -> Path:
    path = get_settings().floodguard_data_dir / "runs" / run_id
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"no run {run_id!r}")
    return path


def load_result(run_id: str) -> dict[str, Any]:
    path = run_dir(run_id) / "result.json"
    if not path.exists():
        raise HTTPException(
            status_code=409,
            detail=(
                f"run {run_id!r} exists but has no result.json yet. It is still running, "
                f"or it failed before producing output."
            ),
        )
    return json.loads(path.read_text(encoding="utf-8"))


@router.get("/{run_id}/summary", response_model=ResultSummary)
def summary(run_id: str) -> ResultSummary:
    """The four KPI cards per engine, plus the breach comparison."""
    data = load_result(run_id)

    engines = []
    for run in data["engines"]:
        s = run.get("summary") or {}
        engines.append(
            EngineSummary(
                engine_id=run["actual_engine"] or run["requested_engine"],
                engine_display_name=run["display_name"],
                is_real_solver=run["is_real_solver"],
                substituted=run["substituted"],
                honesty_note=run["honesty_note"],
                flooded_area_km2=s.get("flooded_area_km2"),
                max_depth_m=s.get("max_depth_m"),
                max_velocity_ms=s.get("max_velocity_ms"),
                earliest_arrival_min=s.get("earliest_arrival_min"),
                max_hazard_m2s=s.get("max_hazard_m2s"),
                runtime_s=s.get("runtime_s"),
                steps=s.get("steps"),
                mass_error=s.get("mass_error"),
                warnings=s.get("warnings", []),
            )
        )

    breach = data["breach"]
    hyd = data["hydrograph"]
    provenance = hyd.get("provenance", {})

    return ResultSummary(
        run_id=run_id,
        scenario_id=data["scenario_id"],
        engines=engines,
        hazard=data.get("hazard", {}),
        breach=BreachComparison(
            used=BreachPrediction(**breach["used"]),
            predictions=[BreachPrediction(**p) for p in breach["predictions"]],
            spread=breach["spread"],
        ),
        peak_discharge_m3s=hyd.get("peak_discharge_m3s"),
        time_to_peak_min=(
            hyd["time_to_peak_s"] / 60.0 if hyd.get("time_to_peak_s") is not None else None
        ),
        total_volume_mcm=(
            hyd["total_volume_m3"] / 1e6 if hyd.get("total_volume_m3") is not None else None
        ),
        # Read from the run itself. Older runs that did not record it report
        # null — never 0.0, which would be a fabricated resolution.
        resolution_m=data.get("resolution_m") or _resolution_from_raster(run_id),
        warnings=data.get("warnings", []),
        provenance=provenance,
    )


def _resolution_from_raster(run_id: str) -> float | None:
    path = run_dir(run_id) / "max_depth.tif"
    if not path.exists():
        return None
    import rasterio

    with rasterio.open(path) as src:
        return float(abs(src.transform.a))


@router.get("/{run_id}/towns", response_model=list[TownResult])
def towns(run_id: str) -> list[TownResult]:
    """Depth, velocity and arrival time per named town, sorted by lead time."""
    data = load_result(run_id)
    return [TownResult(**t) for t in data.get("towns", [])]


@router.get("/{run_id}/towns-by-engine")
def towns_by_engine(run_id: str) -> dict[str, list[dict[str, Any]]]:
    """Arrival, depth and velocity per town for every engine that produced a result.

    Lets the comparison say which engine warns earlier at a named place, which
    matters more to an evacuation plan than any domain-wide statistic.
    """
    data = load_result(run_id)
    return data.get("towns_by_engine") or {}


@router.get("/{run_id}/comparison", response_model=Comparison)
def comparison(run_id: str) -> Comparison:
    """The Model Comparison table. Every cell computed, including Difference."""
    from floodguard.compare.metrics import compare_engines

    data = load_result(run_id)
    runs = [r for r in data["engines"] if r.get("summary")]

    if len(runs) < 2:
        available = [r["display_name"] for r in runs]
        return Comparison(
            run_id=run_id,
            engines=[r["actual_engine"] for r in runs],
            engine_display_names={r["actual_engine"]: r["display_name"] for r in runs},
            rows=[],
            note=(
                f"Only {len(runs)} engine produced a result ({', '.join(available) or 'none'}), "
                f"so there is nothing to compare. Request two engines to populate this table. "
                f"No placeholder numbers are shown."
            ),
        )

    return compare_engines(run_id, runs, run_dir(run_id))


@router.get("/{run_id}/impact", response_model=ImpactResponse)
def impact(run_id: str) -> ImpactResponse:
    """HADR exposure. Absent layers report 'not computed', never zero."""
    path = run_dir(run_id) / "impact.json"
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                "No impact analysis for this run. It requires the OSM and population "
                "layers, which are fetched by `floodguard data` without --skip-osm / "
                "--skip-population. Nothing is estimated in their absence."
            ),
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    return ImpactResponse(
        run_id=run_id,
        metrics={k: ImpactMetric(**v) for k, v in data["metrics"].items()},
        facilities=data.get("facilities", []),
        evacuation_priority=data.get("evacuation_priority", []),
        warnings=data.get("warnings", []),
        provenance=data.get("provenance", {}),
    )


@router.get("/{run_id}/hydrographs", response_model=HydrographResponse)
def hydrographs(run_id: str) -> HydrographResponse:
    """Breach outflow and reservoir level versus time."""
    import csv

    path = run_dir(run_id) / "breach_hydrograph.csv"
    if not path.exists():
        raise HTTPException(status_code=404, detail="no hydrograph was written for this run")

    times: list[float] = []
    columns: dict[str, list[float]] = {}
    with path.open(encoding="utf-8") as fh:
        rows = [ln for ln in fh if not ln.startswith("#")]
    reader = csv.DictReader(rows)
    for row in reader:
        times.append(float(row["time_hours"]))
        for key, value in row.items():
            if key in ("time_s", "time_hours"):
                continue
            columns.setdefault(key, []).append(float(value))

    units = {
        "discharge_m3s": "m3/s",
        "reservoir_level_m": "m MSL",
        "breach_width_m": "m",
    }
    return HydrographResponse(
        run_id=run_id,
        series=[
            HydrographSeries(
                label=name, unit=units.get(name, ""), times_hours=times, values=values
            )
            for name, values in columns.items()
        ],
        note=(
            "Breach outflow at the dam. Routed hydrographs at downstream towns require "
            "gauge extraction from the solver's time series, which is recorded per frame."
        ),
    )


@router.get("/{run_id}/cross-section", response_model=CrossSectionResponse)
def cross_section(
    run_id: str,
    location: str = Query(description="Town name or chainage label, e.g. 'Rishikesh'."),
) -> CrossSectionResponse:
    """Terrain profile with the maximum water surface drawn over it."""
    settings = get_settings()
    data = load_result(run_id)
    scenario_id = data["scenario_id"]

    pre_path = settings.processed_dir / scenario_id / "preprocess.json"
    if not pre_path.exists():
        raise HTTPException(status_code=404, detail="no preprocessing output for this scenario")

    pre = json.loads(pre_path.read_text(encoding="utf-8"))
    section = next(
        (s for s in pre.get("cross_sections", []) if s["name"].lower() == location.lower()),
        None,
    )
    if section is None:
        names = [s["name"] for s in pre.get("cross_sections", [])]
        raise HTTPException(
            status_code=404,
            detail=f"no cross-section named {location!r}. Available: {names}",
        )

    bed = section["bed_m"]
    depth_path = run_dir(run_id) / "max_depth.tif"
    water: list[float | None] = [None] * len(bed)
    max_depth: float | None = None
    note_extra = ""

    xs, ys = section.get("xs"), section.get("ys")
    if depth_path.exists() and xs and ys:
        import rasterio
        from rasterio.transform import rowcol

        # Sample the maximum-depth raster at exactly the section's own sample
        # points. The water surface is bed + local depth where that cell
        # flooded, and null where it stayed dry — never a domain-wide value.
        with rasterio.open(depth_path) as src:
            depth = src.read(1)
            nodata = src.nodata
            transform = src.transform
        local: list[float] = []
        for i, (x, y, b) in enumerate(zip(xs, ys, bed)):
            r, c = rowcol(transform, x, y)
            if b is None or not (0 <= r < depth.shape[0] and 0 <= c < depth.shape[1]):
                continue
            d = float(depth[r, c])
            if nodata is not None and d == nodata:
                continue
            if d >= 0.3:
                water[i] = b + d
                local.append(d)
        max_depth = max(local) if local else None
        if not local:
            note_extra = " No sample on this section exceeded the 0.3 m wet threshold."
    elif depth_path.exists():
        note_extra = (
            " This scenario was preprocessed before section coordinates were stored, so "
            "the water surface cannot be sampled; re-run preprocessing to populate it."
        )

    return CrossSectionResponse(
        run_id=run_id,
        location=section["name"],
        chainage_m=section["chainage_m"],
        offset_from_path_m=section.get("offset_from_path_m"),
        offsets_m=section["offsets_m"],
        bed_m=bed,
        water_surface_m=water,
        max_depth_m=max_depth,
        note=(
            "Bed elevations are sampled from the conditioned DEM along a line "
            "perpendicular to the traced channel. The water surface is bed plus the "
            "local maximum depth at each sample; dry samples are null, never interpolated."
            + note_extra
        ),
    )


@router.get("/{run_id}/exports", response_model=ExportListing)
def list_exports(run_id: str) -> ExportListing:
    data = load_result(run_id)
    return ExportListing(run_id=run_id, exports=data.get("exports", []))


EXPORT_FILES = {
    "tif": ("max_depth.tif", "image/tiff"),
    "velocity_tif": ("max_velocity.tif", "image/tiff"),
    "arrival_tif": ("arrival_time.tif", "image/tiff"),
    "hazard_tif": ("max_hazard.tif", "image/tiff"),
    "difference_tif": ("depth_difference.tif", "image/tiff"),
    "geojson": ("inundation.geojson", "application/geo+json"),
    "shp": ("inundation_shp.zip", "application/zip"),
    "kml": ("inundation.kml", "application/vnd.google-earth.kml+xml"),
    "kmz": ("inundation.kmz", "application/vnd.google-earth.kmz"),
    "csv": ("breach_hydrograph.csv", "text/csv"),
    "pdf": ("report.pdf", "application/pdf"),
}


@router.get("/{run_id}/export")
def export(
    run_id: str,
    format: str = Query(description="One of tif, geojson, shp, kml, kmz, csv, pdf."),
) -> FileResponse:
    """Download one export. 404 with a reason rather than an empty file."""
    if format not in EXPORT_FILES:
        raise HTTPException(
            status_code=422,
            detail=f"unknown format {format!r}; available: {sorted(EXPORT_FILES)}",
        )
    filename, media_type = EXPORT_FILES[format]
    path = run_dir(run_id) / filename
    if format == "pdf" and not path.exists():
        # Generated on first request, from the same files as `floodguard report`.
        from floodguard.report import build_report, write_map_previews

        load_result(run_id)
        write_map_previews(run_dir(run_id))
        build_report(run_dir(run_id), path)
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                f"{filename} was not produced by this run. Vector exports are skipped when "
                f"nothing exceeded the wet threshold; the PDF report is generated on demand."
            ),
        )
    return FileResponse(path, media_type=media_type, filename=f"{run_id}_{filename}")


# --- tiles ------------------------------------------------------------------------

#: Colour ramps per layer: (lower, upper, label, hex). Defined here once and
#: served to the frontend by /legend so the map and its legend cannot drift.
VELOCITY_BANDS = (
    (0.0, 0.5, "< 0.5 m/s", "#d0e7f5"),
    (0.5, 1.0, "0.5 - 1 m/s", "#8cc2e4"),
    (1.0, 2.0, "1 - 2 m/s", "#f4d35e"),
    (2.0, 5.0, "2 - 5 m/s", "#ee964b"),
    (5.0, 10.0, "5 - 10 m/s", "#d1495b"),
    (10.0, float("inf"), "> 10 m/s", "#6a0f49"),
)
ARRIVAL_BANDS = (
    (0.0, 15.0, "< 15 min", "#8b0000"),
    (15.0, 30.0, "15 - 30 min", "#e34a33"),
    (30.0, 60.0, "30 - 60 min", "#fc8d59"),
    (60.0, 120.0, "1 - 2 h", "#fdcc8a"),
    (120.0, 240.0, "2 - 4 h", "#b3de69"),
    (240.0, float("inf"), "> 4 h", "#4daf4a"),
)
DIFFERENCE_BANDS = (
    (-float("inf"), -2.0, "second engine > 2 m shallower", "#2166ac"),
    (-2.0, -0.5, "0.5 - 2 m shallower", "#92c5de"),
    (-0.5, 0.5, "within 0.5 m", "#f7f7f7"),
    (0.5, 2.0, "0.5 - 2 m deeper", "#f4a582"),
    (2.0, float("inf"), "second engine > 2 m deeper", "#b2182b"),
)
LAYERS = ("depth", "velocity", "arrival", "hazard", "difference")


def _bands(layer: str):
    from floodguard.postprocess.hazard import DEPTH_BANDS, HAZARD_CLASSES

    if layer == "depth":
        return DEPTH_BANDS
    if layer == "velocity":
        return VELOCITY_BANDS
    if layer == "arrival":
        return ARRIVAL_BANDS
    if layer == "difference":
        return DIFFERENCE_BANDS
    return tuple(
        (h.code - 0.5, h.code + 0.5, f"{h.label}: {h.description}", h.colour)
        for h in HAZARD_CLASSES
    )


@router.get("/{run_id}/legend")
def legend(run_id: str, layer: str = "depth") -> dict[str, Any]:
    """The bins and colours a layer's tiles are drawn with."""
    if layer not in LAYERS:
        raise HTTPException(status_code=422, detail=f"layer must be one of {LAYERS}")
    run_dir(run_id)
    return {
        "layer": layer,
        "bins": [
            {"lower": lo if np.isfinite(lo) else None, "upper": hi if np.isfinite(hi) else None,
             "label": label, "colour": colour}
            for lo, hi, label, colour in _bands(layer)
        ],
    }


def _read_raster(path: Path):
    import rasterio

    with rasterio.open(path) as src:
        arr = src.read(1).astype(np.float32)
        if src.nodata is not None:
            arr[arr == src.nodata] = np.nan
        return arr, src.transform, src.crs.to_string()


def _raster_name(base: str, engine: str | None) -> str:
    return f"{base}_{engine}.tif" if engine else f"{base}.tif"


@lru_cache(maxsize=24)
def _layer(run_id: str, layer: str, engine: str | None, frame: int | None):
    """Load one displayable layer as (values, transform, crs).

    Cached because tiles are requested dozens at a time as the user pans, and
    re-reading a raster per tile dominates the response time.
    """
    folder = run_dir(run_id)

    if frame is not None:
        # Time-indexed depth. The .npz holds one array per frame, so this
        # decompresses only the requested one.
        eid = engine or _primary_engine(run_id)
        path = folder / f"frames_{eid}.npz"
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"no stored frames for engine {eid!r}")
        with np.load(path) as npz:
            key = f"f{frame:04d}"
            if key not in npz.files:
                raise HTTPException(status_code=404, detail=f"frame {frame} does not exist")
            values = npz[key].astype(np.float32)
        # All engines share the compute grid, so any of the run's depth
        # rasters carries the right georeferencing.
        grid = folder / _raster_name("max_depth", eid)
        if not grid.exists():
            grid = folder / "max_depth.tif"
        _, transform, crs = _read_raster(grid)
        return values, transform, crs

    if layer == "difference":
        path = folder / "depth_difference.tif"
        if not path.exists():
            # Produced by the comparison; build it on first request.
            comparison(run_id)
        if not path.exists():
            raise HTTPException(status_code=404, detail="no depth difference: fewer than two engines ran")
        return _read_raster(path)

    if layer == "hazard":
        from floodguard.postprocess.hazard import classify

        d, transform, crs = _read_raster(_existing(folder, "max_depth", engine))
        v, _, _ = _read_raster(_existing(folder, "max_velocity", engine))
        codes = classify(np.nan_to_num(d), np.nan_to_num(v)).astype(np.float32)
        codes[codes == 0] = np.nan
        return codes, transform, crs

    base = {"depth": "max_depth", "velocity": "max_velocity", "arrival": "arrival_time"}[layer]
    values, transform, crs = _read_raster(_existing(folder, base, engine))
    if layer == "arrival":
        values = np.where(values >= 0, values / 60.0, np.nan).astype(np.float32)
    if layer == "velocity":
        depth, _, _ = _read_raster(_existing(folder, "max_depth", engine))
        values = np.where(depth >= 0.3, values, np.nan).astype(np.float32)
    return values, transform, crs


def _existing(folder: Path, base: str, engine: str | None) -> Path:
    path = folder / _raster_name(base, engine)
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"{path.name} was not produced by this run"
            + (f" (engine {engine!r} did not run)" if engine else ""),
        )
    return path


def _primary_engine(run_id: str) -> str:
    data = load_result(run_id)
    for run in data["engines"]:
        if run.get("summary"):
            return run["actual_engine"]
    raise HTTPException(status_code=404, detail="no engine produced a result in this run")


@router.get("/{run_id}/frames")
def frames(run_id: str) -> dict[str, Any]:
    """Times of the stored depth frames, per engine, for the time slider."""
    folder = run_dir(run_id)
    out: dict[str, list[float]] = {}
    for path in sorted(folder.glob("frames_*.npz")):
        with np.load(path) as npz:
            out[path.stem.removeprefix("frames_")] = [float(t) for t in npz["times_s"]]
    return {
        "run_id": run_id,
        "engines": out,
        "note": (
            "Each frame is the instantaneous depth field the solver stored at that time. "
            "Request a frame's tiles with ?frame=<index>&engine=<id>."
            if out else
            "This run stored no time frames, so the map cannot animate. Runs from this "
            "version onwards store them."
        ),
    }


@router.get("/{run_id}/tiles/{z}/{x}/{y}.png")
def tile(
    run_id: str,
    z: int,
    x: int,
    y: int,
    layer: str = Query("depth", description=f"One of {LAYERS}."),
    engine: str | None = Query(None, description="Engine id; default is the primary engine."),
    frame: int | None = Query(None, ge=0, description="Time frame index (depth only)."),
) -> Response:
    """XYZ tile of any result layer, coloured with the legend bins.

    A deliberately small, dependency-free tiler: it reprojects the Web Mercator
    tile into the raster's CRS and samples nearest-neighbour. It exists so the
    browser never downloads the full raster, which is the spec's large-data
    requirement. For production, titiler is in docker-compose.
    """
    import io
    import math

    from PIL import Image
    from pyproj import Transformer

    if layer not in LAYERS:
        raise HTTPException(status_code=422, detail=f"layer must be one of {LAYERS}")
    if engine is not None and not engine.replace("_", "").isalnum():
        raise HTTPException(status_code=422, detail="malformed engine id")

    values_grid, transform, crs = _layer(run_id, layer, engine, frame)

    n = 2.0**z
    west = x / n * 360.0 - 180.0
    east = (x + 1) / n * 360.0 - 180.0
    north = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    south = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))

    size = 256
    # Sample at pixel centres, evenly spaced in Web Mercator y so the tile is
    # not distorted at high latitudes.
    fx = (np.arange(size) + 0.5) / size
    lons = west + fx * (east - west)
    merc = lambda lat: math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))  # noqa: E731
    my = merc(north) + fx * (merc(south) - merc(north))
    lats = np.degrees(2 * np.arctan(np.exp(my)) - math.pi / 2)
    lon_grid, lat_grid = np.meshgrid(lons, lats)

    to_raster = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    xs, ys = to_raster.transform(lon_grid.ravel(), lat_grid.ravel())
    inv = ~transform
    cols, rows = inv @ (np.asarray(xs), np.asarray(ys))
    cols = np.floor(cols).astype(int)
    rows = np.floor(rows).astype(int)

    valid = (rows >= 0) & (rows < values_grid.shape[0]) & (cols >= 0) & (cols < values_grid.shape[1])
    values = np.full(rows.shape, np.nan, dtype=np.float32)
    values[valid] = values_grid[rows[valid], cols[valid]]

    rgba = np.zeros((size * size, 4), dtype=np.uint8)
    for lo, hi, _label, colour in _bands(layer):
        h = colour.lstrip("#")
        rgb = (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
        with np.errstate(invalid="ignore"):
            sel = (values >= lo) & (values < hi)
        if layer == "depth":
            sel &= values >= 0.1
        rgba[sel] = (*rgb, 205)
    if layer == "difference":
        # The neutral band is drawn faintly so agreement reads as "quiet".
        with np.errstate(invalid="ignore"):
            quiet = (values > -0.5) & (values < 0.5) & (values != 0)
        rgba[quiet, 3] = 60
        rgba[values == 0] = 0

    img = Image.fromarray(rgba.reshape(size, size, 4), mode="RGBA")
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False)
    return Response(
        content=buf.getvalue(),
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )
