"""Run listing, share links, 3D scene assets and area-of-interest statistics.

    GET  /api/runs                                 completed runs (Demo Mode)
    POST /api/results/{run_id}/share               create a short link
    GET  /api/share/{code}                         resolve a short link
    GET  /api/results/{run_id}/3d/meta             bounds + ranges for the 3D view
    GET  /api/results/{run_id}/3d/terrain.png      Terrarium-encoded bed
    GET  /api/results/{run_id}/3d/terrain-texture.png  hillshade
    GET  /api/results/{run_id}/3d/water.png        Terrarium-encoded water surface
    GET  /api/results/{run_id}/3d/water-texture.png    depth colours, dry transparent
    GET  /api/results/{run_id}/aoi-stats?upload_id=    flood statistics inside an AOI

Like every other results endpoint, these read a completed run's files and
compute nothing a `floodguard simulate` could not reproduce.
"""

from __future__ import annotations

import io
import json
import secrets
import string
import threading
import time
from functools import lru_cache
from typing import Any

import numpy as np
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.api.results import load_result, run_dir
from app.core.config import get_settings

router = APIRouter(tags=["views"])

WET_THRESHOLD_M = 0.3


# --- runs -------------------------------------------------------------------------


@router.get("/api/runs")
def list_runs(limit: int = 50) -> list[dict[str, Any]]:
    """Completed runs, newest first. Demo Mode loads one of these instantly.

    Only runs with a result.json are listed: a run that is still going, or
    that failed, has nothing to show and is not offered.
    """
    runs_root = get_settings().floodguard_data_dir / "runs"
    if not runs_root.exists():
        return []
    items = []
    for path in runs_root.glob("*/result.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        engines = [
            {
                "id": e.get("actual_engine") or e.get("requested_engine"),
                "display_name": e.get("display_name"),
                "ok": bool(e.get("summary")),
            }
            for e in data.get("engines", [])
        ]
        primary = next((e for e in data.get("engines", []) if e.get("summary")), None)
        summary = (primary or {}).get("summary") or {}
        items.append(
            {
                "run_id": data.get("run_id", path.parent.name),
                "scenario_id": data.get("scenario_id"),
                "completed_utc": data.get("completed_utc")
                or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(path.stat().st_mtime)),
                "resolution_m": data.get("resolution_m"),
                "engines": engines,
                "engine_count": sum(e["ok"] for e in engines),
                "flooded_area_km2": summary.get("flooded_area_km2"),
                "max_depth_m": summary.get("max_depth_m"),
                "has_frames": any(path.parent.glob("frames_*.npz")),
                "has_impact": (path.parent / "impact.json").exists(),
                "_mtime": path.stat().st_mtime,
            }
        )
    items.sort(key=lambda r: r["_mtime"], reverse=True)
    for item in items:
        item.pop("_mtime")
    return items[:limit]


# --- share links ------------------------------------------------------------------

_share_lock = threading.Lock()
_ALPHABET = string.ascii_letters + string.digits


class ShareRequest(BaseModel):
    """What the recipient should see: layer, engine, frame. All optional."""

    view: dict[str, Any] = Field(default_factory=dict)


def _shares_path():
    return get_settings().floodguard_data_dir / "shares.json"


def _load_shares() -> dict[str, Any]:
    path = _shares_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


@router.post("/api/results/{run_id}/share")
def create_share(run_id: str, request: ShareRequest | None = None) -> dict[str, Any]:
    """A short, unguessable code that opens this run in the dashboard.

    The code maps to a run id and an optional view state. It grants nothing
    beyond what the run id already does; it exists so a district officer can
    be sent a link that fits in an SMS.
    """
    load_result(run_id)  # 404/409 if the run is not viewable
    view = (request.view if request else {}) or {}
    allowed = {"layer", "engine", "frame", "tab"}
    view = {k: v for k, v in view.items() if k in allowed}
    with _share_lock:
        shares = _load_shares()
        code = "".join(secrets.choice(_ALPHABET) for _ in range(8))
        while code in shares:
            code = "".join(secrets.choice(_ALPHABET) for _ in range(8))
        shares[code] = {
            "run_id": run_id,
            "view": view,
            "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        path = _shares_path()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(shares, indent=2), encoding="utf-8")
        tmp.replace(path)
    return {"code": code, "path": f"/s/{code}", "run_id": run_id, "view": view}


@router.get("/api/share/{code}")
def resolve_share(code: str) -> dict[str, Any]:
    if not code.isalnum() or len(code) > 16:
        raise HTTPException(status_code=422, detail="malformed share code")
    entry = _load_shares().get(code)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"no share link {code!r}")
    return {"code": code, **entry}


# --- 3D scene ---------------------------------------------------------------------

MAX_3D_PIXELS = 1024


@lru_cache(maxsize=8)
def _scene(run_id: str, frame: int | None, engine: str | None):
    """Bed and depth reprojected to a lon/lat grid, which deck.gl's TerrainLayer needs.

    The TerrainLayer maps an image linearly onto [west, south, east, north],
    so the rasters must be in EPSG:4326 — draping a UTM raster over those
    bounds would shear the valley. Downsampled to at most 1024 px so the
    browser receives a few hundred kilobytes, not the full grid.
    """
    import rasterio
    from rasterio.warp import Resampling, calculate_default_transform, reproject

    folder = run_dir(run_id)
    bed_path = folder / "bed.tif"
    if not bed_path.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                "this run has no bed.tif (it predates the 3D view). Re-run the scenario to "
                "produce one; the 3D view is not drawn over a different surface."
            ),
        )

    with rasterio.open(bed_path) as src:
        bed = src.read(1).astype(np.float32)
        if src.nodata is not None:
            bed[bed == src.nodata] = np.nan
        src_transform, src_crs = src.transform, src.crs
        width, height, bounds = src.width, src.height, src.bounds

    if frame is None:
        depth_name = f"max_depth_{engine}.tif" if engine else "max_depth.tif"
        with rasterio.open(folder / depth_name) as src:
            depth = src.read(1).astype(np.float32)
            if src.nodata is not None:
                depth[depth == src.nodata] = 0.0
    else:
        from app.api.results import _primary_engine

        eid = engine or _primary_engine(run_id)
        path = folder / f"frames_{eid}.npz"
        if not path.exists():
            raise HTTPException(status_code=404, detail="no stored frames for this engine")
        with np.load(path) as npz:
            key = f"f{frame:04d}"
            if key not in npz.files:
                raise HTTPException(status_code=404, detail=f"frame {frame} does not exist")
            depth = npz[key].astype(np.float32)

    _, dst_w, dst_h = calculate_default_transform(src_crs, "EPSG:4326", width, height, *bounds)
    scale = max(dst_w, dst_h) / MAX_3D_PIXELS
    if scale > 1:
        dst_w, dst_h = int(dst_w / scale), int(dst_h / scale)
    dst_transform = _fit(src_crs, bounds, dst_w, dst_h)

    out_bed = np.full((dst_h, dst_w), np.nan, dtype=np.float32)
    out_depth = np.zeros((dst_h, dst_w), dtype=np.float32)
    reproject(bed, out_bed, src_transform=src_transform, src_crs=src_crs,
              dst_transform=dst_transform, dst_crs="EPSG:4326",
              resampling=Resampling.bilinear, src_nodata=np.nan, dst_nodata=np.nan)
    reproject(depth, out_depth, src_transform=src_transform, src_crs=src_crs,
              dst_transform=dst_transform, dst_crs="EPSG:4326",
              resampling=Resampling.max)

    west, north = dst_transform @ (0, 0)
    east, south = dst_transform @ (dst_w, dst_h)
    return out_bed, out_depth, (float(west), float(south), float(east), float(north))


def _fit(src_crs, bounds, dst_w, dst_h):
    """A lon/lat transform covering the reprojected extent at a given pixel size."""
    from rasterio.transform import from_bounds
    from rasterio.warp import transform_bounds

    w, s, e, n = transform_bounds(src_crs, "EPSG:4326", *bounds, densify_pts=21)
    return from_bounds(w, s, e, n, dst_w, dst_h)


def _terrarium(elev: np.ndarray) -> bytes:
    """Encode elevation as a Terrarium PNG (R*256 + G + B/256 - 32768)."""
    from PIL import Image

    v = np.nan_to_num(elev, nan=-100.0).astype(np.float64) + 32768.0
    r = np.floor(v / 256.0)
    g = np.floor(v - r * 256.0)
    b = np.floor((v - np.floor(v)) * 256.0)
    rgb = np.stack([r, g, b], axis=-1).clip(0, 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(rgb, mode="RGB").save(buf, format="PNG")
    return buf.getvalue()


def _png(rgba: np.ndarray) -> Response:
    from PIL import Image

    buf = io.BytesIO()
    Image.fromarray(rgba, mode="RGBA").save(buf, format="PNG")
    return Response(buf.getvalue(), media_type="image/png",
                    headers={"Cache-Control": "public, max-age=3600"})


@router.get("/api/results/{run_id}/3d/meta")
def scene_meta(run_id: str) -> dict[str, Any]:
    bed, depth, bounds = _scene(run_id, None, None)
    wet = depth >= WET_THRESHOLD_M
    return {
        "run_id": run_id,
        "bounds": bounds,
        "size": [int(bed.shape[1]), int(bed.shape[0])],
        "bed_min_m": float(np.nanmin(bed)) if np.isfinite(bed).any() else None,
        "bed_max_m": float(np.nanmax(bed)) if np.isfinite(bed).any() else None,
        "max_depth_m": float(depth.max()) if wet.any() else None,
        "encoding": "terrarium",
        "note": (
            "Bed and water surface are reprojected to EPSG:4326 and downsampled to at most "
            f"{MAX_3D_PIXELS} px for display; depths shown are the per-pixel maximum of "
            "the solver cells that fall inside it."
        ),
    }


@router.get("/api/results/{run_id}/3d/terrain.png")
def scene_terrain(run_id: str) -> Response:
    bed, _, _ = _scene(run_id, None, None)
    return Response(_terrarium(bed), media_type="image/png",
                    headers={"Cache-Control": "public, max-age=3600"})


@router.get("/api/results/{run_id}/3d/terrain-texture.png")
def scene_terrain_texture(run_id: str) -> Response:
    """A hillshade (sun from the north-west, 45 degrees up), so relief reads in 3D."""
    bed, _, bounds = _scene(run_id, None, None)
    z = np.nan_to_num(bed, nan=float(np.nanmin(bed)) if np.isfinite(bed).any() else 0.0)
    # Pixel size in metres, approximately, for a sensible slope.
    lat = np.radians(0.5 * (bounds[1] + bounds[3]))
    px = (bounds[2] - bounds[0]) / bed.shape[1] * 111_320 * np.cos(lat)
    py = (bounds[3] - bounds[1]) / bed.shape[0] * 110_574
    gy, gx = np.gradient(z, py, px)
    slope = np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    az, alt = np.radians(315.0), np.radians(45.0)
    shade = np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect)
    grey = (np.clip(shade, 0, 1) * 200 + 40).astype(np.uint8)
    rgba = np.stack([grey, (grey * 0.97).astype(np.uint8), (grey * 0.9).astype(np.uint8),
                     np.where(np.isfinite(bed), 255, 0).astype(np.uint8)], axis=-1)
    return _png(rgba)


@router.get("/api/results/{run_id}/3d/water.png")
def scene_water(
    run_id: str,
    frame: int | None = Query(None, ge=0),
    engine: str | None = None,
) -> Response:
    """Water-surface elevation. Dry pixels sit 50 m under the bed, hidden by it."""
    bed, depth, _ = _scene(run_id, frame, engine)
    surface = np.where(depth >= WET_THRESHOLD_M, bed + depth, bed - 50.0)
    return Response(_terrarium(surface), media_type="image/png",
                    headers={"Cache-Control": "public, max-age=3600"})


@router.get("/api/results/{run_id}/3d/water-texture.png")
def scene_water_texture(
    run_id: str,
    frame: int | None = Query(None, ge=0),
    engine: str | None = None,
) -> Response:
    from floodguard.postprocess.hazard import DEPTH_BANDS

    _, depth, _ = _scene(run_id, frame, engine)
    rgba = np.zeros((*depth.shape, 4), dtype=np.uint8)
    for lo, hi, _label, colour in DEPTH_BANDS:
        h = colour.lstrip("#")
        sel = (depth >= max(lo, WET_THRESHOLD_M)) & (depth < hi)
        rgba[sel] = (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 215)
    return _png(rgba)


# --- AOI statistics ----------------------------------------------------------------


@router.get("/api/results/{run_id}/aoi-stats")
def aoi_stats(run_id: str, upload_id: str) -> dict[str, Any]:
    """Flood statistics inside an uploaded polygon — a district, a block, a campus.

    If the polygon lies outside the compute domain the answer is "not covered",
    with a null value, never zero: the model said nothing about that area.
    """
    import geopandas as gpd
    import rasterio
    from rasterio.features import geometry_mask

    from app.api.uploads import load_upload, uploads_dir

    meta = load_upload(upload_id)
    if meta["kind"] != "aoi":
        raise HTTPException(status_code=422, detail="upload is not an AOI")
    folder = run_dir(run_id)
    load_result(run_id)

    with rasterio.open(folder / "max_depth.tif") as src:
        depth = src.read(1).astype(np.float64)
        if src.nodata is not None:
            depth[depth == src.nodata] = np.nan
        transform, crs, shape = src.transform, src.crs, (src.height, src.width)
        cell_area = abs(transform.a * transform.e)
    arrival = None
    if (folder / "arrival_time.tif").exists():
        with rasterio.open(folder / "arrival_time.tif") as src:
            arrival = src.read(1).astype(np.float64)

    aoi = gpd.read_file(uploads_dir() / upload_id / "aoi.geojson").to_crs(crs)
    inside = ~geometry_mask(aoi.geometry, out_shape=shape, transform=transform, all_touched=False)
    aoi_area_km2 = float(aoi.area.sum() / 1e6)
    covered_km2 = float(inside.sum() * cell_area / 1e6)

    base = {
        "run_id": run_id,
        "upload_id": upload_id,
        "aoi_name": meta.get("original_filename"),
        "aoi_area_km2": aoi_area_km2,
        "covered_by_model_km2": covered_km2,
        "coverage_fraction": covered_km2 / aoi_area_km2 if aoi_area_km2 > 0 else None,
        "wet_threshold_m": WET_THRESHOLD_M,
    }
    if not inside.any():
        return {
            **base,
            "flooded_area_km2": None,
            "max_depth_m": None,
            "earliest_arrival_min": None,
            "reason": "The AOI does not overlap the simulation domain, so the model says "
                      "nothing about it. This is not the same as 'no flooding'.",
        }

    d = np.nan_to_num(depth[inside])
    wet = d >= WET_THRESHOLD_M
    earliest = None
    if arrival is not None:
        a = arrival[inside]
        a = a[(a >= 0) & wet]
        earliest = float(a.min() / 60.0) if a.size else None
    return {
        **base,
        "flooded_area_km2": float(wet.sum() * cell_area / 1e6),
        "flooded_fraction_of_covered": float(wet.mean()),
        "max_depth_m": float(d[wet].max()) if wet.any() else None,
        "mean_flooded_depth_m": float(d[wet].mean()) if wet.any() else None,
        "earliest_arrival_min": earliest,
        "reason": (
            "" if base["coverage_fraction"] and base["coverage_fraction"] > 0.95 else
            "Part of the AOI lies outside the simulation domain; statistics cover only the "
            "modelled part."
        ),
    }
