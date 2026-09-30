"""Site readiness: which dams this install can model, and how it knows.

Readiness is COMPUTED from files on this machine, never asserted:

    terrain     a processed DEM exists at the resolution AND its footprint
                covers the scenario's area of interest (a file that exists
                but covers a different window is not readiness)
    land cover  WorldCover on the same grid (else Manning's n is uniform)
    population  a population raster is present (else exposure is "not computed")
    OSM         which exposure layers were fetched
    presets     how many modelled presets have a stored run, per resolution

The tier is derived in that order and travels with its reason:

    presets ready     every modelled preset at the default resolution is stored
    partly ready      some presets stored
    inputs ready      terrain covers the AOI but nothing is precomputed
    not ready         no covering terrain — the reason says why
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from floodguard import library as lib
from floodguard import processed
from floodguard.scenario import Scenario


def _footprint_wgs84(dem_path: Path) -> tuple[float, float, float, float] | None:
    try:
        import rasterio
        from rasterio.warp import transform_bounds

        with rasterio.open(dem_path) as src:
            return tuple(transform_bounds(src.crs, "EPSG:4326", *src.bounds, densify_pts=21))
    except Exception:  # noqa: BLE001 - an unreadable DEM is not readiness
        return None


def _covers(outer, inner, tol_deg: float = 0.01) -> bool:
    return (outer[0] <= inner[0] + tol_deg and outer[1] <= inner[1] + tol_deg
            and outer[2] >= inner[2] - tol_deg and outer[3] >= inner[3] - tol_deg)


def terrain_status(scenario: Scenario, data_dir: Path, resolution_m: float) -> dict[str, Any]:
    from floodguard.data.acquire import derive_aoi

    aoi = derive_aoi(scenario)
    folder = processed.inputs_dir(data_dir, scenario.id, resolution_m)
    dem = folder / processed.DEM_NAME
    if not dem.exists():
        return {"ok": False, "reason": f"no {resolution_m:g} m DEM has been processed",
                "aoi": list(aoi)}
    footprint = _footprint_wgs84(dem)
    if footprint is None:
        return {"ok": False, "reason": "the DEM file cannot be read", "aoi": list(aoi)}
    if not _covers(footprint, aoi):
        return {"ok": False, "reason": "the processed DEM does not cover the scenario's area "
                "of interest", "aoi": list(aoi), "footprint": list(footprint)}
    return {
        "ok": True, "reason": f"{resolution_m:g} m DEM covers the area of interest",
        "aoi": list(aoi), "footprint": [round(v, 4) for v in footprint],
        "landcover": (folder / processed.LANDCOVER_NAME).exists(),
    }


def site_row(scenario: Scenario, data_dir: Path) -> dict[str, Any]:
    data_dir = Path(data_dir)
    raw = data_dir / "raw"
    osm_dir = raw / "osm" / scenario.id
    osm_layers = sorted(
        p.stem for p in osm_dir.glob("*.geojson")
    ) if osm_dir.exists() else []
    population = any((raw / "population").rglob("*.tif")) if (raw / "population").exists() else False

    by_res = {}
    for res in lib.LIBRARY_RESOLUTIONS:
        modelled = list(lib.iter_presets(scenario, resolution_m=res))
        stored = [p.key for p in modelled if lib.lookup(data_dir, p.key)]
        by_res[f"{res:g}"] = {
            "terrain": terrain_status(scenario, data_dir, res),
            "presets_defined": len(modelled),
            "presets_stored": len(stored),
        }

    default = by_res[f"{lib.LIBRARY_RESOLUTION_M:g}"]
    stored_any = sum(v["presets_stored"] for v in by_res.values())
    if default["presets_defined"] and default["presets_stored"] == default["presets_defined"]:
        tier, reason = "presets ready", (
            f"all {default['presets_defined']} modelled presets at "
            f"{lib.LIBRARY_RESOLUTION_M:g} m are stored on this machine"
        )
    elif stored_any:
        tier, reason = "partly ready", f"{stored_any} preset run(s) stored"
    elif any(v["terrain"]["ok"] for v in by_res.values()):
        tier, reason = "inputs ready", "terrain covers the area of interest; nothing precomputed yet"
    else:
        tier, reason = "not ready", default["terrain"]["reason"]
    if tier in ("presets ready", "partly ready") and not default["terrain"]["ok"]:
        reason += (
            "; terrain is not on this machine (the runs came from a data pack), so a "
            "quick estimate for this dam would download it first"
        )

    return {
        "scenario_id": scenario.id,
        "name": scenario.name,
        "dam": scenario.dam.name,
        "river": scenario.dam.river,
        "tier": tier,
        "tier_reason": reason,
        "towns": len(scenario.towns),
        "population_raster": population,
        "osm_layers": osm_layers,
        "resolutions": by_res,
    }


def registry(scenarios: list[Scenario], data_dir: Path) -> list[dict[str, Any]]:
    return [site_row(s, data_dir) for s in scenarios]
