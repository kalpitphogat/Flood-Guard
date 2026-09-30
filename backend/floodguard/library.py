"""Precomputed scenario library — the presets the dashboard answers instantly.

A full 120 m run takes minutes (Tehri) to tens of minutes (Hirakud), which is
too slow for a live demo. So a fixed set of presets is computed ahead of time
with the real pipeline, and served as what they are: *precomputed* runs, with
the date they were computed. Anything that is not a preset runs live as a
coarse, labelled *quick estimate*. Neither is ever presented as the other.

This module is pure bookkeeping — preset definitions, keys, the index file —
and never runs a solver itself, so all of it is testable in milliseconds.
`floodguard precompute` (cli.py) is the only thing that drives the solver.

Failure types
-------------
Only `complete_dam_break` is precomputed. `overtopping` exists as a
scenario-type label, but the breach model and the routing treat it identically
to a complete break today; precomputing it would store the same numbers under a
different name, which is a fabricated distinction. `partial_breach` is modelled
(a user-set breach-depth fraction raises the invert), but only live: the
fraction is the user's assumption, and a preset would have to choose it for
them. Both stay listed, `modelled=False`, with the reason.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from floodguard.scenario import Scenario, ScenarioType

#: Failure types offered as presets, in priority order.
PRESET_TYPES: tuple[str, ...] = (
    ScenarioType.COMPLETE_DAM_BREAK.value,
    ScenarioType.PARTIAL_BREACH.value,
    ScenarioType.OVERTOPPING.value,
)

#: Failure types the current breach model actually distinguishes. The others are
#: listed but never computed — see the module docstring.
MODELLED_TYPES: frozenset[str] = frozenset({ScenarioType.COMPLETE_DAM_BREAK.value})

UNMODELLED_REASON = (
    "Not modelled distinctly yet: FloodGuard's breach model and routing treat this "
    "failure type exactly like a complete dam break, so a separate run would repeat "
    "the complete-break numbers under a different name."
)

#: Why a listed type is not precomputed, per type. A partial breach IS modelled
#: now, but only live: it needs a breach-depth fraction that is the user's own
#: assumption, and a preset would have to pick that assumption for them.
NOT_PRECOMPUTED_REASONS: dict[str, str] = {
    ScenarioType.PARTIAL_BREACH.value: (
        "Runs live only: a partial breach needs a breach-depth fraction that you choose "
        "(an assumption, not a published value), so none is precomputed. Use Custom — "
        "quick estimate and set the fraction."
    ),
    ScenarioType.OVERTOPPING.value: UNMODELLED_REASON,
}


def not_precomputed_reason(scenario_type: str) -> str:
    """Why a failure type has no preset."""
    return NOT_PRECOMPUTED_REASONS.get(scenario_type, UNMODELLED_REASON)

#: Reservoir levels, in priority order.
PRESET_LEVELS: tuple[str, ...] = ("frl", "mid", "mddl")

LEVEL_LABELS: dict[str, str] = {
    "frl": "Full reservoir level (FRL)",
    "mid": "Midway between FRL and MDDL",
    "mddl": "Minimum drawdown level (MDDL)",
}

TYPE_LABELS: dict[str, str] = {
    "complete_dam_break": "Complete dam break",
    "partial_breach": "Partial breach",
    "overtopping": "Overtopping failure",
}

#: The default preset resolution. Keys at this resolution carry no suffix, so
#: the first library (all 120 m) keeps its keys and run folders.
LIBRARY_RESOLUTION_M = 120.0
#: Resolutions the library may hold, coarsest (fastest, default) first.
LIBRARY_RESOLUTIONS: tuple[float, ...] = (120.0, 60.0)
LIBRARY_ENGINES: tuple[str, ...] = ("swe_fv",)

QUICK_RESOLUTION_M = 200.0
QUICK_DURATION_H = 1.0
QUICK_ENGINES: tuple[str, ...] = ("swe_fv",)
QUICK_LABEL = "Quick estimate — 200 m, 1 h simulated"

RUN_PREFIX = "lib_"
KEY_SEP = "__"


# --- keys and levels ----------------------------------------------------------------


def _res_suffix(resolution_m: float) -> str:
    value = float(resolution_m)
    return f"r{int(value)}" if value.is_integer() else "r" + f"{value:g}".replace(".", "p")


def preset_key(
    scenario_id: str, scenario_type: str, level_name: str,
    resolution_m: float = LIBRARY_RESOLUTION_M,
) -> str:
    """Deterministic key, e.g. `tehri_bhagirathi__complete_dam_break__frl`.

    Presets at the default resolution have no suffix; any other resolution
    appends one, e.g. `...__frl__r60`.
    """
    parts = [scenario_id, scenario_type, level_name]
    if float(resolution_m) != LIBRARY_RESOLUTION_M:
        parts.append(_res_suffix(resolution_m))
    return KEY_SEP.join(parts)


def parse_key(key: str) -> tuple[str, str, str, float]:
    """Inverse of `preset_key`: (scenario id, type, level, resolution m)."""
    parts = key.split(KEY_SEP)
    if len(parts) not in (3, 4) or not all(parts):
        raise ValueError(f"malformed preset key: {key!r}")
    resolution = LIBRARY_RESOLUTION_M
    if len(parts) == 4:
        tag = parts[3]
        try:
            if not tag.startswith("r"):
                raise ValueError
            resolution = float(tag[1:].replace("p", "."))
        except ValueError:
            raise ValueError(f"malformed resolution in preset key: {key!r}") from None
        if resolution == LIBRARY_RESOLUTION_M or resolution <= 0:
            raise ValueError(f"malformed resolution in preset key: {key!r}")
    return parts[0], parts[1], parts[2], resolution


def run_id_for(key: str) -> str:
    """The run folder name. Deterministic, so a finished preset is recognisable."""
    return f"{RUN_PREFIX}{key}"


def level_values(scenario: Scenario) -> dict[str, float]:
    """Reservoir level (m MSL) for each preset level this dam supports.

    Derived from the scenario's own FRL and MDDL, never hard-coded. A dam
    without an MDDL only gets `frl`; one without an FRL gets nothing.
    """
    frl = scenario.dam.frl_m
    mddl = scenario.dam.mddl_m
    out: dict[str, float] = {}
    if frl is None:
        return out
    out["frl"] = float(frl)
    if mddl is not None:
        out["mid"] = round((frl + mddl) / 2.0, 2)
        out["mddl"] = float(mddl)
    return out


@dataclass(frozen=True)
class Preset:
    key: str
    scenario_id: str
    scenario_type: str
    level: str
    level_m: float
    modelled: bool
    resolution_m: float = LIBRARY_RESOLUTION_M

    @property
    def run_id(self) -> str:
        return run_id_for(self.key)


def iter_presets(
    scenario: Scenario,
    *,
    include_unmodelled: bool = False,
    resolution_m: float = LIBRARY_RESOLUTION_M,
) -> Iterator[Preset]:
    """Presets for one dam at one resolution, in priority order.

    Complete break at FRL first (the headline case), then the other levels of
    the complete break, then partial breach, then overtopping. Unmodelled types
    are skipped unless asked for (the API lists them so the UI can explain).
    """
    levels = level_values(scenario)
    for stype in PRESET_TYPES:
        modelled = stype in MODELLED_TYPES
        if not modelled and not include_unmodelled:
            continue
        for level in PRESET_LEVELS:
            if level not in levels:
                continue
            yield Preset(
                key=preset_key(scenario.id, stype, level, resolution_m),
                scenario_id=scenario.id,
                scenario_type=stype,
                level=level,
                level_m=levels[level],
                modelled=modelled,
                resolution_m=float(resolution_m),
            )


def build_preset_scenario(
    base: Scenario, scenario_type: str, level: str,
    resolution_m: float = LIBRARY_RESOLUTION_M,
) -> Scenario:
    """The validated scenario a preset runs. `base` is not modified.

    `id` is kept unchanged: it is the key of the processed-data folder, so a
    preset reuses the dam's DEM rather than acquiring its own.
    """
    if scenario_type not in MODELLED_TYPES:
        raise ValueError(f"{scenario_type!r}: {not_precomputed_reason(scenario_type)}")
    levels = level_values(base)
    if level not in levels:
        raise ValueError(
            f"scenario {base.id!r} has no {level!r} level "
            f"(FRL={base.dam.frl_m}, MDDL={base.dam.mddl_m})"
        )
    raw = base.model_dump(mode="json")
    raw["scenario_type"] = scenario_type
    raw["reservoir"]["initial_level_m"] = levels[level]
    raw["domain"]["resolution_m"] = float(resolution_m)
    raw["engines"] = list(LIBRARY_ENGINES)
    return Scenario.model_validate(raw)


def apply_quick_settings(scenario: Scenario) -> Scenario:
    """Force the quick-estimate settings onto a scenario (returns a new one)."""
    raw = scenario.model_dump(mode="json")
    raw["domain"]["resolution_m"] = QUICK_RESOLUTION_M
    raw["solver"]["duration_hours"] = QUICK_DURATION_H
    raw["engines"] = list(QUICK_ENGINES)
    return Scenario.model_validate(raw)


# --- index --------------------------------------------------------------------------


def library_dir(data_dir: Path) -> Path:
    return Path(data_dir) / "library"


def index_path(data_dir: Path) -> Path:
    return library_dir(data_dir) / "index.json"


def result_path(data_dir: Path, key: str) -> Path:
    return Path(data_dir) / "runs" / run_id_for(key) / "result.json"


def load_index(data_dir: Path) -> dict[str, dict[str, Any]]:
    path = index_path(data_dir)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_index(data_dir: Path, index: dict[str, dict[str, Any]]) -> Path:
    """Atomic write: a reader never sees a half-written index."""
    path = index_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".index.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(index, fh, indent=2, sort_keys=True)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path


def record(data_dir: Path, key: str, entry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Merge one entry into the index and write it."""
    index = load_index(data_dir)
    index[key] = entry
    write_index(data_dir, index)
    return index


def is_done(data_dir: Path, key: str) -> bool:
    return result_path(data_dir, key).exists()


def lookup(data_dir: Path, key: str) -> dict[str, Any] | None:
    """The index entry for a finished preset, or None.

    An entry whose `result.json` is missing (deleted, or the run failed) is
    treated as unavailable: the API must never hand out a run that is not there.
    """
    entry = load_index(data_dir).get(key)
    if not entry or entry.get("status") != "succeeded":
        return None
    if not is_done(data_dir, key):
        return None
    return entry


def entry_for(
    preset: Preset,
    *,
    duration_hours: float,
    completed_utc: str | None,
    wall_seconds: float | None,
    status: str,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "run_id": preset.run_id,
        "scenario_id": preset.scenario_id,
        "scenario_type": preset.scenario_type,
        "level": preset.level,
        "level_m": preset.level_m,
        "resolution_m": preset.resolution_m,
        "engines": list(LIBRARY_ENGINES),
        "duration_hours": duration_hours,
        "completed_utc": completed_utc,
        "wall_seconds": wall_seconds,
        "status": status,
        "error": error,
    }


def run_meta_for(preset: Preset) -> dict[str, Any]:
    """What the pipeline writes into result.json for a library run."""
    return {
        "run_mode": "precomputed",
        "library_key": preset.key,
        "library_level": preset.level,
        "library_level_m": preset.level_m,
        "library_resolution_m": preset.resolution_m,
    }
