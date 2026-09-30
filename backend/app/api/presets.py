"""Precomputed presets: what the dashboard can answer instantly.

GET /api/presets lists every preset the library defines, whether its stored run
exists, and — for the ones that are not offered — why. The quick-estimate
settings are returned alongside, so the UI never hard-codes them.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.core.config import get_settings


#: Words kept upper case when a catalogue name is title-cased for the UI.
NAME_ACRONYMS = {"HPP", "HEP", "HE", "NHPC", "NTPC", "SJVN", "THDC", "MIP", "LIS"}


def display_name(name: str) -> str:
    """Catalogue names are upper case ("TEHRI HPP"); title-case them for the UI,
    keeping known acronyms ("Tehri HPP", not "Tehri Hpp")."""
    return " ".join(w if w.upper() in NAME_ACRONYMS else w.capitalize() for w in name.split())
from app.schemas.models import (
    PresetCatalog,
    PresetDam,
    PresetEntry,
    PresetLevel,
    QuickSettings,
)

router = APIRouter(tags=["presets"])


def library_scenarios() -> list[Any]:
    """Every bundled scenario, i.e. every dam that can have presets."""
    from floodguard.scenario import Scenario

    out = []
    for path in sorted(get_settings().scenarios_dir.glob("*.yaml")):
        try:
            out.append(Scenario.from_yaml(path))
        except Exception:  # noqa: BLE001 - one broken YAML must not hide the others
            continue
    return out


@router.get("/api/presets", response_model=PresetCatalog)
def list_presets() -> PresetCatalog:
    from floodguard import library as lib

    data_dir = get_settings().floodguard_data_dir
    index = lib.load_index(data_dir)
    dams: list[PresetDam] = []
    entries: list[PresetEntry] = []

    for scenario in library_scenarios():
        levels = lib.level_values(scenario)
        if not levels:
            continue
        dams.append(
            PresetDam(
                scenario_id=scenario.id,
                name=display_name(scenario.dam.name),
                duration_hours=scenario.solver.duration_hours,
                levels=[
                    PresetLevel(level=k, label=lib.LEVEL_LABELS[k], level_m=v)
                    for k, v in levels.items()
                ],
            )
        )
        for preset in (
            p
            for res in lib.LIBRARY_RESOLUTIONS
            for p in lib.iter_presets(scenario, include_unmodelled=True, resolution_m=res)
        ):
            found = lib.lookup(data_dir, preset.key)
            raw = index.get(preset.key) or {}
            if not preset.modelled:
                reason = lib.not_precomputed_reason(preset.scenario_type)
            elif found:
                reason = None
            elif raw.get("status") == "failed":
                reason = f"The precompute run failed: {raw.get('error') or 'see the log'}"
            else:
                reason = "Not precomputed yet."
            entries.append(
                PresetEntry(
                    key=preset.key,
                    scenario_id=preset.scenario_id,
                    scenario_type=preset.scenario_type,
                    type_label=lib.TYPE_LABELS[preset.scenario_type],
                    level=preset.level,
                    level_label=lib.LEVEL_LABELS[preset.level],
                    level_m=preset.level_m,
                    modelled=preset.modelled,
                    available=found is not None,
                    reason=reason,
                    run_id=preset.run_id,
                    completed_utc=(found or {}).get("completed_utc"),
                    wall_seconds=(found or {}).get("wall_seconds"),
                    resolution_m=preset.resolution_m,
                )
            )

    return PresetCatalog(
        resolution_m=lib.LIBRARY_RESOLUTION_M,
        resolutions=list(lib.LIBRARY_RESOLUTIONS),
        engines=list(lib.LIBRARY_ENGINES),
        dams=dams,
        failure_types=dict(lib.TYPE_LABELS),
        presets=entries,
        quick=QuickSettings(
            resolution_m=lib.QUICK_RESOLUTION_M,
            duration_hours=lib.QUICK_DURATION_H,
            engines=list(lib.QUICK_ENGINES),
            label=lib.QUICK_LABEL,
        ),
    )


@router.get("/api/registry")
def site_registry() -> dict[str, Any]:
    """Which bundled dams this install can model, and the facts that say so."""
    from floodguard.registry import registry

    return {
        "sites": registry(library_scenarios(), get_settings().floodguard_data_dir),
        "note": "Readiness is computed from the files on this machine: a DEM that covers "
                "the area of interest, the input layers present, and the stored preset runs.",
    }
