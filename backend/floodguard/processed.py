"""Where a scenario's processed inputs live, per compute resolution.

Processed inputs (DEM mosaic, land cover on the DEM grid, preprocess.json) are
resolution-specific. They used to live in one folder per scenario, so a 200 m
quick estimate re-mosaicked the DEM a 120 m preset had just used, two jobs at
different resolutions overwrote each other's files, and a land-cover raster
left from another resolution silently degraded to uniform Manning's n.

Now each resolution has its own folder:

    data/processed/<scenario_id>/r120/dem_utm.tif
    data/processed/<scenario_id>/r200/dem_utm.tif

Data made before this change sits directly in `data/processed/<scenario_id>/`.
It is still used when its DEM is at the requested resolution, so nothing has
to be re-fetched; new data is always written to the `r<res>` folder.
"""

from __future__ import annotations

from pathlib import Path

DEM_NAME = "dem_utm.tif"
LANDCOVER_NAME = "landcover_utm.tif"
PREPROCESS_NAME = "preprocess.json"


def res_tag(resolution_m: float) -> str:
    """`r120` for 120 m; `r92p5` for 92.5 m. Stable and filesystem-safe."""
    value = float(resolution_m)
    if value.is_integer():
        return f"r{int(value)}"
    return "r" + f"{value:g}".replace(".", "p")


def scenario_root(data_dir: Path, scenario_id: str) -> Path:
    return Path(data_dir) / "processed" / scenario_id


def resolution_dir(data_dir: Path, scenario_id: str, resolution_m: float) -> Path:
    """The folder new processed data for this resolution is written to."""
    return scenario_root(data_dir, scenario_id) / res_tag(resolution_m)


def _dem_resolution(path: Path) -> float | None:
    try:
        import rasterio

        with rasterio.open(path) as src:
            return float(abs(src.transform.a))
    except Exception:  # noqa: BLE001 - an unreadable DEM is treated as absent
        return None


def legacy_dir_if_matching(data_dir: Path, scenario_id: str, resolution_m: float) -> Path | None:
    """The pre-change flat folder, only if its DEM is at this resolution."""
    root = scenario_root(data_dir, scenario_id)
    have = _dem_resolution(root / DEM_NAME) if (root / DEM_NAME).exists() else None
    if have is not None and abs(have - float(resolution_m)) <= 0.01 * float(resolution_m):
        return root
    return None


def inputs_dir(data_dir: Path, scenario_id: str, resolution_m: float) -> Path:
    """Where this scenario's inputs at this resolution are read from.

    The `r<res>` folder when it holds a DEM; otherwise the legacy flat folder
    when its DEM matches; otherwise the `r<res>` folder (to be created).
    """
    new = resolution_dir(data_dir, scenario_id, resolution_m)
    if (new / DEM_NAME).exists():
        return new
    return legacy_dir_if_matching(data_dir, scenario_id, resolution_m) or new


def find_preprocess_json(
    data_dir: Path, scenario_id: str, resolution_m: float | None = None
) -> Path | None:
    """preprocess.json for a scenario: at the given resolution if known, else any."""
    root = scenario_root(data_dir, scenario_id)
    if resolution_m:
        path = inputs_dir(data_dir, scenario_id, resolution_m) / PREPROCESS_NAME
        if path.exists():
            return path
        # A machine that received runs through a data pack has preprocess.json
        # but no DEM, so inputs_dir cannot tell the layouts apart: accept a
        # candidate whose own recorded grid is at this resolution.
        for candidate in (resolution_dir(data_dir, scenario_id, resolution_m) / PREPROCESS_NAME,
                          root / PREPROCESS_NAME):
            if candidate.exists() and _grid_matches(candidate, resolution_m):
                return candidate
        return None
    candidates = sorted(root.glob(f"r*/{PREPROCESS_NAME}")) + [root / PREPROCESS_NAME]
    return next((p for p in candidates if p.exists()), None)


def all_preprocess_json(data_dir: Path) -> list[Path]:
    """Every preprocess.json under data/processed, in either layout."""
    base = Path(data_dir) / "processed"
    return sorted(base.glob(f"*/{PREPROCESS_NAME}")) + sorted(base.glob(f"*/r*/{PREPROCESS_NAME}"))


def _grid_matches(preprocess_json: Path, resolution_m: float) -> bool:
    import json

    try:
        grid = json.loads(preprocess_json.read_text(encoding="utf-8")).get("grid") or {}
        cell = float(grid.get("cell_size_m"))
    except (OSError, ValueError, TypeError):
        return False
    return abs(cell - float(resolution_m)) <= 0.01 * float(resolution_m)
