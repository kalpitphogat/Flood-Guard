"""Datasets on this machine, with their licences.

GET /api/datasets groups `data/MANIFEST.json` — which records the URL, SHA-256,
size, licence and fetch time of every downloaded or derived file — by source,
so the attribution every output owes is one request away.
"""

from __future__ import annotations

import json
from collections import OrderedDict
from typing import Any

from fastapi import APIRouter

from app.core.config import get_settings

router = APIRouter(tags=["datasets"])


@router.get("/api/datasets")
def datasets() -> dict[str, Any]:
    path = get_settings().manifest_path
    if not path.exists():
        return {
            "sources": [],
            "note": (
                "No MANIFEST.json on this machine — typical for a demo laptop that "
                "received its runs through a data pack. Each pack carries the "
                "attribution for the data behind its runs, and docs/DATA_SOURCES.md "
                "lists every source and licence."
            ),
        }
    manifest = json.loads(path.read_text(encoding="utf-8"))
    groups: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
    for e in manifest.get("entries", []):
        g = groups.setdefault(e.get("source") or "unknown", {
            "source": e.get("source") or "unknown",
            "licences": [],
            "files": 0,
            "total_bytes": 0,
            "example_url": e.get("url"),
            "last_fetched_utc": None,
        })
        if e.get("licence") and e["licence"] not in g["licences"]:
            g["licences"].append(e["licence"])
        g["files"] += 1
        g["total_bytes"] += int(e.get("size_bytes") or 0)
        fetched = e.get("fetched_utc")
        if fetched and (g["last_fetched_utc"] is None or fetched > g["last_fetched_utc"]):
            g["last_fetched_utc"] = fetched
    return {
        "sources": list(groups.values()),
        "entry_count": manifest.get("entry_count"),
        "updated_utc": manifest.get("updated_utc"),
        "note": "Every file is checksummed; `floodguard verify` re-hashes them all.",
    }
