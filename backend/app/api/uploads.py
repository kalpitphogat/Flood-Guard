"""Uploads: bring your own DEM, outflow hydrograph or area of interest.

    POST /api/uploads/dem         GeoTIFF elevation model
    POST /api/uploads/hydrograph  CSV, time + discharge in m3/s
    POST /api/uploads/aoi         GeoJSON, KML or zipped shapefile polygon
    GET  /api/uploads             everything accepted so far
    GET  /api/uploads/{id}        one upload's validation report
    GET  /api/uploads/{id}/geojson  an AOI as GeoJSON, for the map overlay

A file that fails validation is deleted and the response is a 422 listing
every reason. An accepted file is stored under data/uploads/{id}/ with its
validation report and SHA256, so a run that used it can be traced to the
exact bytes.
"""

from __future__ import annotations

import json
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response

from app.core.config import get_settings

router = APIRouter(prefix="/api/uploads", tags=["uploads"])

#: Accepted extensions and size caps per kind.
KINDS: dict[str, tuple[tuple[str, ...], int]] = {
    "dem": ((".tif", ".tiff"), 800 * 1024 * 1024),
    "hydrograph": ((".csv", ".txt"), 10 * 1024 * 1024),
    "aoi": ((".geojson", ".json", ".kml", ".zip"), 50 * 1024 * 1024),
}


def uploads_dir() -> Path:
    path = get_settings().floodguard_data_dir / "uploads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_upload(upload_id: str) -> dict[str, Any]:
    """The stored validation report for an accepted upload, or 404."""
    if not upload_id.replace("-", "").isalnum():
        raise HTTPException(status_code=422, detail="malformed upload id")
    meta_path = uploads_dir() / upload_id / "meta.json"
    if not meta_path.exists():
        raise HTTPException(status_code=404, detail=f"no upload {upload_id!r}")
    return json.loads(meta_path.read_text(encoding="utf-8"))


def upload_file_path(upload_id: str) -> Path:
    meta = load_upload(upload_id)
    return uploads_dir() / upload_id / meta["stored_as"]


def _validate(kind: str, path: Path) -> dict[str, Any]:
    from floodguard.data import uploads as v

    if kind == "dem":
        return v.validate_dem(path)
    if kind == "hydrograph":
        return v.validate_hydrograph(path)
    return v.validate_aoi(path)


@router.post("/{kind}")
async def upload(kind: str, file: UploadFile = File(...)) -> dict[str, Any]:
    if kind not in KINDS:
        raise HTTPException(status_code=404, detail=f"unknown upload kind {kind!r}; use {sorted(KINDS)}")
    extensions, cap = KINDS[kind]
    name = Path(file.filename or "upload").name
    suffix = Path(name).suffix.lower()
    if suffix not in extensions:
        raise HTTPException(
            status_code=422,
            detail=f"{kind} uploads must be one of {', '.join(extensions)}; got {suffix or 'no extension'}",
        )

    upload_id = uuid.uuid4().hex[:12]
    folder = uploads_dir() / upload_id
    folder.mkdir(parents=True)
    stored = folder / f"{kind}{suffix}"

    size = 0
    with stored.open("wb") as out:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > cap:
                out.close()
                shutil.rmtree(folder, ignore_errors=True)
                raise HTTPException(
                    status_code=413, detail=f"{kind} uploads are capped at {cap // (1024 * 1024)} MB"
                )
            out.write(chunk)

    report = _validate(kind, stored)
    if not report.get("ok"):
        shutil.rmtree(folder, ignore_errors=True)
        raise HTTPException(
            status_code=422,
            detail={"message": f"the {kind} file was refused", "issues": report.get("issues", [])},
        )

    geojson = report.pop("geojson", None)
    if geojson is not None:
        (folder / "aoi.geojson").write_text(geojson, encoding="utf-8")

    meta = {
        **report,
        "id": upload_id,
        "kind": kind,
        "original_filename": name,
        "stored_as": stored.name,
        "size_bytes": size,
        "uploaded_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    (folder / "meta.json").write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")
    return meta


@router.get("")
def list_uploads(kind: str | None = None) -> list[dict[str, Any]]:
    out = []
    for meta_path in sorted(uploads_dir().glob("*/meta.json"), reverse=True):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if kind is None or meta.get("kind") == kind:
            out.append(meta)
    return out


@router.get("/{upload_id}")
def get_upload(upload_id: str) -> dict[str, Any]:
    return load_upload(upload_id)


@router.get("/{upload_id}/geojson")
def upload_geojson(upload_id: str) -> Response:
    meta = load_upload(upload_id)
    if meta["kind"] != "aoi":
        raise HTTPException(status_code=422, detail="only AOI uploads have a GeoJSON view")
    path = uploads_dir() / upload_id / "aoi.geojson"
    return Response(path.read_text(encoding="utf-8"), media_type="application/geo+json")
