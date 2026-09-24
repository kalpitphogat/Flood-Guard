"""Early warning for a completed run.

    GET /api/results/{run_id}/warning                 alert levels, safe ground, SMS (JSON)
    GET /api/results/{run_id}/warning/bulletin.txt    ?lang=en|hi — printable bulletin
    GET /api/results/{run_id}/warning/cap.xml         ?status=Exercise|Test|Draft — CAP 1.2
    GET /api/results/{run_id}/breach-ensemble         outflow for every breach model

Computed on request from the run's own files (result.json, max_depth.tif,
bed.tif, breach_ensemble.json); nothing here is stored or invented.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

import numpy as np
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from app.api.results import _read_raster, load_result, run_dir
from app.core.config import get_settings

router = APIRouter(prefix="/api/results", tags=["warning"])


def _scenario_name(scenario_id: str) -> str:
    path = get_settings().scenarios_dir / f"{scenario_id}.yaml"
    if path.exists():
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return str(data.get("name") or scenario_id)
    return scenario_id


@lru_cache(maxsize=8)
def _bulletin(run_id: str) -> dict[str, Any]:
    from floodguard.warning.bulletin import build

    data = load_result(run_id)
    folder = run_dir(run_id)
    depth = bed = transform = crs = None
    if (folder / "max_depth.tif").exists() and (folder / "bed.tif").exists():
        depth, transform, crs = _read_raster(folder / "max_depth.tif")
        bed, _, _ = _read_raster(folder / "bed.tif")
        depth = depth.astype(np.float64)
        bed = bed.astype(np.float64)
    return build(
        data,
        scenario_name=_scenario_name(data.get("scenario_id", "")),
        depth=depth,
        bed=bed,
        transform=transform,
        crs=crs,
    )


@router.get("/{run_id}/warning")
def warning(run_id: str) -> dict[str, Any]:
    payload = _bulletin(run_id)
    if not payload["towns"]:
        raise HTTPException(
            status_code=404,
            detail="this run has no named towns, so there is nobody to warn by name",
        )
    return payload


@router.get("/{run_id}/warning/bulletin.txt")
def bulletin_text(run_id: str, lang: str = Query("en", pattern="^(en|hi)$")) -> Response:
    payload = warning(run_id)
    text = payload["text_hi"] if lang == "hi" else payload["text_en"]
    return Response(
        text,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{run_id}_bulletin_{lang}.txt"'},
    )


@router.get("/{run_id}/warning/cap.xml")
def cap(run_id: str, status: str = "Exercise") -> Response:
    from floodguard.warning.bulletin import cap_xml

    payload = warning(run_id)
    try:
        xml = cap_xml(payload, status=status)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return Response(
        xml,
        media_type="application/cap+xml",
        headers={"Content-Disposition": f'attachment; filename="{run_id}_cap.xml"'},
    )


@router.get("/{run_id}/breach-ensemble")
def breach_ensemble(run_id: str) -> dict[str, Any]:
    path = run_dir(run_id) / "breach_ensemble.json"
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                "no breach ensemble for this run: it predates the feature, or its "
                "hydrograph was user-supplied (then there is no breach model to vary)"
            ),
        )
    return json.loads(path.read_text(encoding="utf-8"))
