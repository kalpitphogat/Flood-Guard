"""What produced a run's numbers, read back from the run's own files.

Every row names the field it came from — `result.json:…` or a GeoTIFF tag
`max_depth.tif:FG_…` — so the table is emitted by the run itself rather than
maintained by hand beside it, and a judge can check any row on disk.

The labels at the top are derived from the same fields: every assumption,
substitution or caveat the run carries is listed where it cannot be missed
(reconstructed bathymetry, values flagged in their own source notes, an engine
substitution, a numerical mass gain, breach regressions that do not apply,
hypothetical inputs). None is typed in here; each is a rule over the run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

#: Words that dam-source notes use to mark a value as not directly cited.
FLAG_WORDS = ("FLAGGED", "NOT in the NRLD", "ILLUSTRATIVE", "Derived as", "verify")


def _tags(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    import rasterio

    with rasterio.open(path) as src:
        return dict(src.tags())


def _json_tag(tags: dict[str, str], key: str) -> Any:
    try:
        return json.loads(tags[key])
    except (KeyError, ValueError):
        return None


def _row(label: str, value: Any, source: str) -> dict[str, Any]:
    if isinstance(value, float):
        value = round(value, 4)
    return {"label": label, "value": value, "source": source}


def build_provenance(run_dir: Path) -> dict[str, Any]:
    run_dir = Path(run_dir)
    r = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    tags = _tags(run_dir / "max_depth.tif")
    T = "max_depth.tif:"
    engine = next((e for e in r.get("engines", []) if e.get("summary")), {}) or {}
    breach = (r.get("breach") or {}).get("used") or {}
    hyd = r.get("hydrograph") or {}
    reservoir = _json_tag(tags, "FG_RESERVOIR") or {}
    dam = _json_tag(tags, "FG_DAM") or {}
    meta = r.get("run_meta") or {}

    def f(key: str) -> float | None:
        try:
            return float(tags[key])
        except (KeyError, ValueError):
            return None

    sections = [
        {"title": "Run", "rows": [
            _row("Run id", r.get("run_id"), "result.json:run_id"),
            _row("How it was produced", r.get("run_mode", "full"), "result.json:run_mode"),
            _row("Preset key", meta.get("library_key"), "result.json:run_meta.library_key"),
            _row("Completed (UTC)", r.get("completed_utc"), "result.json:completed_utc"),
            _row("Grid resolution (m)", r.get("resolution_m"), "result.json:resolution_m"),
            _row("Simulated duration (h)", f("FG_DURATION_HOURS"), T + "FG_DURATION_HOURS"),
            _row("Engine", engine.get("display_name"), "result.json:engines[0].display_name"),
            _row("Engine version", tags.get("FG_ENGINE_VERSION"), T + "FG_ENGINE_VERSION"),
            _row("Engine honesty note", engine.get("honesty_note"), "result.json:engines[0].honesty_note"),
        ]},
        {"title": "Dam and reservoir", "rows": [
            _row("Scenario", r.get("scenario_id"), "result.json:scenario_id"),
            _row("Failure type", tags.get("FG_SCENARIO_TYPE"), T + "FG_SCENARIO_TYPE"),
            _row("Dam", dam.get("name"), T + "FG_DAM.name"),
            _row("Initial reservoir level (m MSL)", f("FG_INITIAL_LEVEL_M"), T + "FG_INITIAL_LEVEL_M"),
            _row("Reservoir curve method", reservoir.get("method"), T + "FG_RESERVOIR.method"),
            _row("Storage at the curve top (MCM)", reservoir.get("final_storage_mcm"), T + "FG_RESERVOIR.final_storage_mcm"),
            _row("Published area used (km²)", reservoir.get("water_surface_area_km2") if reservoir.get("area_source") else None, T + "FG_RESERVOIR.water_surface_area_km2"),
            _row("Area source", reservoir.get("area_source"), T + "FG_RESERVOIR.area_source"),
        ] + [
            _row(f"Source of {field}", text, T + f"FG_DAM.sources.{field}")
            for field, text in sorted((dam.get("sources") or {}).items())
        ]},
        {"title": "Breach and outflow", "rows": [
            _row("Breach model", breach.get("model"), "result.json:breach.used.model"),
            _row("Reference", breach.get("reference"), "result.json:breach.used.reference"),
            _row("Width (m)", breach.get("width_m"), "result.json:breach.used.width_m"),
            _row("Formation time (min)", breach.get("formation_time_min"), "result.json:breach.used.formation_time_min"),
            _row("Model spread on width (×)", ((r.get("breach") or {}).get("spread") or {}).get("width_m", {}).get("spread_ratio"), "result.json:breach.spread.width_m.spread_ratio"),
            _row("Peak outflow (m³/s)", hyd.get("peak_discharge_m3s"), "result.json:hydrograph.peak_discharge_m3s"),
            _row("Volume released (m³)", hyd.get("total_volume_m3"), "result.json:hydrograph.total_volume_m3"),
            _row("Routing mass error", hyd.get("mass_error"), "result.json:hydrograph.mass_error"),
        ]},
        {"title": "Solver", "rows": [
            _row("Scheme", tags.get("FG_SCHEME"), T + "FG_SCHEME"),
            _row("References", "; ".join(_json_tag(tags, "FG_REFERENCES") or []) or None, T + "FG_REFERENCES"),
            _row("CFL", f("FG_CFL"), T + "FG_CFL"),
            _row("Wet threshold (m)", f("FG_WET_THRESHOLD_M"), T + "FG_WET_THRESHOLD_M"),
            _row("Timesteps", f("FG_STEPS"), T + "FG_STEPS"),
            _row("Solver runtime (s)", f("FG_RUNTIME_S"), T + "FG_RUNTIME_S"),
            _row("Volume introduced (m³)", f("FG_VOLUME_INTRODUCED_M3"), T + "FG_VOLUME_INTRODUCED_M3"),
            _row("Volume in domain at end (m³)", f("FG_VOLUME_REMAINING_M3"), T + "FG_VOLUME_REMAINING_M3"),
            _row("Water created by positivity (m³)", f("FG_VOLUME_CREATED_BY_POSITIVITY_M3"), T + "FG_VOLUME_CREATED_BY_POSITIVITY_M3"),
            _row("Solver mass error", f("FG_MASS_ERROR"), T + "FG_MASS_ERROR"),
            _row("Cell-updates speed-capped", f("FG_CELL_UPDATES_SPEED_CAPPED"), T + "FG_CELL_UPDATES_SPEED_CAPPED"),
        ]},
    ]
    for s in sections:
        s["rows"] = [row for row in s["rows"] if row["value"] not in (None, "", [])]

    labels: list[dict[str, str]] = []

    def label(level: str, text: str, source: str) -> None:
        labels.append({"level": level, "text": text, "source": source})

    mode = r.get("run_mode", "full")
    if mode == "precomputed":
        label("info", f"Precomputed on {str(r.get('completed_utc', ''))[:10]} and loaded from disk; "
              "nothing was computed at view time.", "result.json:run_mode")
    elif mode == "quick_estimate":
        label("caution", "Quick estimate: coarse grid and one simulated hour.", "result.json:run_mode")
    if reservoir.get("is_reconstruction") and reservoir.get("applied"):
        label("caution", "Reservoir bathymetry is RECONSTRUCTED, not surveyed.", T + "FG_RESERVOIR")
    for field, text in sorted((dam.get("sources") or {}).items()):
        if any(w.lower() in str(text).lower() for w in FLAG_WORDS):
            label("caution", f"Dam {field}: {text}", T + f"FG_DAM.sources.{field}")
    if engine.get("substituted"):
        label("caution", engine.get("honesty_note", "Engine substituted."), "result.json:engines[0].substituted")
    created = f("FG_VOLUME_CREATED_BY_POSITIVITY_M3")
    introduced = f("FG_VOLUME_INTRODUCED_M3") or 0.0
    remaining = f("FG_VOLUME_REMAINING_M3")
    if remaining is not None and introduced > 0 and (remaining - introduced) / introduced > 0.01:
        label("caution", f"Numerical mass gain of {(remaining - introduced) / introduced:.1%}.",
              T + "FG_VOLUME_REMAINING_M3")
    if created is None:
        label("info", "This run predates the water-created counter (solver fixes of 2026-09-30).",
              T + "FG_VOLUME_CREATED_BY_POSITIVITY_M3")
    if breach and breach.get("applicable") is False:
        label("caution", "The breach regressions do not apply to this dam; breach geometry was "
              "user-specified.", "result.json:breach.used.applicable")
    if (r.get("breach") or {}).get("natural_dam_check"):
        label("caution", (r["breach"]["natural_dam_check"] or {}).get("summary", "Natural blockage."),
              "result.json:breach.natural_dam_check")
    if "hypothetical" in str(r.get("scenario_id", "")).lower():
        label("caution", "HYPOTHETICAL scenario: illustrative inputs, not an assessment.",
              "result.json:scenario_id")
    label("info", f"{len(r.get('warnings', []))} run warning(s); read them before quoting a number.",
          "result.json:warnings")

    return {"run_id": r.get("run_id", run_dir.name), "labels": labels, "sections": sections}
