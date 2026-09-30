"""Phase 2 orchestration: `floodguard preprocess --scenario ...`.

Turns the fetched DEM into everything the solver needs:

1. Hydrological conditioning — fill, D8, accumulation
2. Dam point snapped to the stream
3. Downstream trace and corridor mask
4. Reservoir pool, elevation-area-capacity curve, storage sanity check
5. Cross-sections at named towns and regular chainages
6. Manning's n field

Outputs land in `data/processed/<scenario_id>/` with a `preprocess.json`
carrying provenance and every diagnostic a reviewer would want to see before
trusting the map.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from floodguard.preprocess import hydro, reservoir, roughness, sections
from floodguard.scenario import Scenario

log = logging.getLogger(__name__)


@dataclass
class PreprocessResult:
    """Everything Phase 2 produced, plus the diagnostics that qualify it."""

    scenario_id: str
    out_dir: Path
    shape: tuple[int, int]
    cell_size_m: float
    crs: str
    transform: Any

    dam_rc: tuple[int, int]
    dam_snapped_rc: tuple[int, int]
    snap_distance_m: float
    snap_accumulation_cells: float

    path_rc: np.ndarray
    path_length_km: float
    corridor_cells: int
    corridor_area_km2: float

    dem: np.ndarray = field(repr=False, default=None)
    filled: np.ndarray = field(repr=False, default=None)
    corridor: np.ndarray = field(repr=False, default=None)
    manning: np.ndarray = field(repr=False, default=None)

    reservoir: reservoir.ReservoirGeometry | None = None
    #: A natural blockage raised into `dem` (None for engineered dams).
    barrier: Any = None
    #: Where the solver releases the breach outflow; None -> dam_snapped_rc.
    release_rc: tuple[int, int] | None = None
    cross_sections: list[sections.CrossSection] = field(default_factory=list)
    catchment_km2: float = 0.0
    conditioning_stats: dict[str, Any] = field(default_factory=dict)
    roughness_stats: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    runtime_s: float = 0.0

    def summary(self) -> str:
        lines = [
            f"Preprocess complete for {self.scenario_id} in {self.runtime_s:.1f}s",
            f"  Grid            : {self.shape[1]} x {self.shape[0]} @ {self.cell_size_m:.0f} m ({self.crs})",
            f"  Dam cell        : {self.dam_rc} -> snapped {self.dam_snapped_rc} "
            f"({self.snap_distance_m:.0f} m, {self.snap_accumulation_cells:,.0f} upstream cells)",
            f"  Routed path     : {self.path_length_km:.1f} km, {len(self.path_rc)} cells",
            f"  Corridor        : {self.corridor_area_km2:.1f} km2 ({self.corridor_cells:,} cells)",
            f"  Dam catchment   : {self.catchment_km2:.1f} km2 (within the AOI)",
            f"  Cross-sections  : {len(self.cross_sections)}",
        ]
        if self.conditioning_stats:
            s = self.conditioning_stats
            lines.append(
                f"  DEM conditioning: {s['cells_filled']:,} cells filled, "
                f"max {s['max_fill_m']:.1f} m, {s['nodata_cells']:,} nodata"
            )
        if self.reservoir:
            lines.append("")
            lines.append(self.reservoir.summary())
        if self.roughness_stats:
            r = self.roughness_stats
            lines.append("")
            lines.append(
                f"Manning's n: {r['source']}, range {r['min']:.3f}-{r['max']:.3f}, "
                f"mean {r['mean']:.3f} ({r['coverage_fraction'] * 100:.0f}% from land cover)"
            )
        if self.warnings:
            lines.append("")
            lines.append("WARNINGS — read these before quoting any number from this run:")
            for w in self.warnings:
                lines.append(f"  - {w}")
        lines.append("")
        lines.append(f"Outputs: {self.out_dir}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "grid": {
                "rows": self.shape[0],
                "cols": self.shape[1],
                "cell_size_m": self.cell_size_m,
                "crs": self.crs,
            },
            "dam": {
                "cell": list(self.dam_rc),
                "snapped_cell": list(self.dam_snapped_rc),
                "snap_distance_m": self.snap_distance_m,
                "snap_accumulation_cells": self.snap_accumulation_cells,
            },
            "routing": {
                "path_length_km": self.path_length_km,
                "path_cells": len(self.path_rc),
                "corridor_cells": self.corridor_cells,
                "corridor_area_km2": self.corridor_area_km2,
            },
            "catchment_km2": self.catchment_km2,
            "conditioning": self.conditioning_stats,
            "roughness": self.roughness_stats,
            "reservoir": self.reservoir.to_dict() if self.reservoir else None,
            "barrier": self.barrier.to_dict() if self.barrier else None,
            "cross_sections": [s.to_dict() for s in self.cross_sections],
            "warnings": self.warnings,
            "runtime_s": self.runtime_s,
        }


def _write_raster(path: Path, array: np.ndarray, transform, crs: str, dtype: str, nodata) -> None:
    import rasterio

    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=array.shape[0],
        width=array.shape[1],
        count=1,
        dtype=dtype,
        crs=crs,
        transform=transform,
        nodata=nodata,
        compress="deflate",
        tiled=True,
        blockxsize=512,
        blockysize=512,
    ) as dst:
        dst.write(array.astype(dtype), 1)


def run_preprocess(
    scenario: Scenario,
    data_dir: Path,
    *,
    dem_path: Path | None = None,
    write_rasters: bool = True,
) -> PreprocessResult:
    """Run the full Phase 2 pipeline for a scenario."""
    import rasterio
    from pyproj import Transformer
    from rasterio.transform import rowcol

    from floodguard import processed

    started = time.perf_counter()
    # Resolution-scoped (data/processed/<id>/r<res>/), falling back to the
    # legacy flat folder when its DEM is at this resolution.
    out_dir = processed.inputs_dir(data_dir, scenario.id, scenario.domain.resolution_m)
    out_dir.mkdir(parents=True, exist_ok=True)

    dem_path = dem_path or (out_dir / "dem_utm.tif")
    if not dem_path.exists():
        raise FileNotFoundError(
            f"DEM not found at {dem_path}. Run `floodguard data --scenario ...` first."
        )

    with rasterio.open(dem_path) as src:
        dem = src.read(1).astype(np.float64)
        transform = src.transform
        crs = src.crs.to_string()
        nodata = src.nodata
        cell_size_m = float(abs(src.transform.a))

    nodata_mask = (
        np.isnan(dem) if nodata is None else (np.isnan(dem) | np.isclose(dem, nodata))
    )
    # Copernicus uses very negative fills over voids; treat them as nodata too.
    nodata_mask |= dem < -1000
    log.info(
        "DEM %dx%d @ %.0f m, %s, %.1f%% nodata",
        dem.shape[1],
        dem.shape[0],
        cell_size_m,
        crs,
        100 * nodata_mask.mean(),
    )

    warnings: list[str] = []

    # --- 1. conditioning ---
    conditioned = hydro.condition(dem, nodata_mask, cell_size_m, transform, crs)
    stats = conditioned.stats()
    if stats["max_fill_m"] > 50:
        warnings.append(
            f"Depression filling raised one or more cells by up to {stats['max_fill_m']:.0f} m. "
            f"That usually means a DEM void or a reservoir surface, not real topography. "
            f"Check the fill-depth raster before trusting the routed path."
        )

    # --- 2. snap the dam to the stream ---
    to_grid = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    dam_x, dam_y = to_grid.transform(scenario.dam.lon, scenario.dam.lat)
    dam_row, dam_col = rowcol(transform, dam_x, dam_y)
    dam_row, dam_col = int(dam_row), int(dam_col)

    if not (0 <= dam_row < dem.shape[0] and 0 <= dam_col < dem.shape[1]):
        raise ValueError(
            f"dam at ({scenario.dam.lat}, {scenario.dam.lon}) falls outside the DEM. "
            f"The AOI derivation or the dam coordinate is wrong."
        )

    # The search radius must scale with the structure. A 300 m window is fine
    # for a 575 m dam in a gorge, but Hirakud's embankment is 4.8 km long and
    # the published coordinate can sit kilometres from the spillway. Searching
    # too small a window snaps to whatever local drain happens to be nearest,
    # which at Hirakud produced a 28 km2 "catchment" for a dam that drains
    # 83,000 km2 — and every reservoir figure downstream of that was nonsense.
    search_m = max(500.0, (scenario.dam.crest_length_m or 0.0) / 2.0)
    snap_radius = max(3, int(round(search_m / cell_size_m)))
    snap_row, snap_col, snap_accum = hydro.snap_to_stream(
        conditioned.accumulation, dam_row, dam_col, snap_radius
    )
    snap_distance_m = float(np.hypot(snap_row - dam_row, snap_col - dam_col) * cell_size_m)
    log.info(
        "dam snapped %.0f m (searched %.0f m) to a cell with %.0f upstream cells",
        snap_distance_m,
        search_m,
        snap_accum,
    )
    if snap_distance_m > 250:
        warnings.append(
            f"The dam point moved {snap_distance_m:.0f} m when snapped to the stream network "
            f"(search radius {search_m:.0f} m, "
            + (
                f"scaled to the {scenario.dam.crest_length_m:.0f} m crest length"
                if scenario.dam.crest_length_m
                else "the default; no crest length is given"
            )
            + "). NRLD coordinates are ~30 m precision, so a move this large "
            f"suggests the published point is on an abutment rather than the spillway."
        )

    # Plausibility: a major dam sits on a major river. If the snapped cell
    # carries a trivial share of the domain's drainage, the snap found a
    # tributary and everything derived from it will be wrong.
    max_accum = float(conditioned.accumulation.max())
    accum_share = snap_accum / max_accum if max_accum > 0 else 0.0
    if accum_share < 0.05:
        warnings.append(
            f"The snapped dam cell carries only {snap_accum:,.0f} upstream cells, "
            f"{accum_share:.1%} of the largest drainage in the domain. A major dam sits on "
            f"a major river, so this almost certainly snapped to a tributary rather than "
            f"the main channel. The reservoir, the routed path and every downstream number "
            f"should be treated as wrong until the dam coordinate is corrected."
        )

    # --- 3. downstream trace + corridor ---
    path_rc, path_len_m = hydro.trace_downstream(
        conditioned.direction,
        snap_row,
        snap_col,
        cell_size_m,
        scenario.domain.reach_length_km * 1000.0,
    )
    if path_len_m < 0.5 * scenario.domain.reach_length_km * 1000.0:
        warnings.append(
            f"The downstream trace stopped after {path_len_m / 1000:.1f} km, well short of the "
            f"requested {scenario.domain.reach_length_km:.0f} km. The AOI is probably too "
            f"small, so the wave will hit the domain edge before reaching the far towns."
        )

    corridor = hydro.corridor_mask(
        dem.shape, path_rc, cell_size_m, scenario.domain.corridor_buffer_km * 1000.0
    )
    corridor &= ~nodata_mask

    # --- 4. reservoir ---
    # The pool must be confined to the dam's own catchment, or the fill at FRL
    # escapes downstream. See reservoir.delineate_pool for why this matters.
    catchment = hydro.upstream_watershed(conditioned.direction, snap_row, snap_col)
    catchment_km2 = float(catchment.sum() * cell_size_m**2 / 1e6)
    log.info("dam catchment within the AOI: %.1f km2", catchment_km2)

    # The curve is always built up to FRL, whatever the starting level. Two
    # reasons, both hit on the Tehri 120 m presets: (1) a surface model sees
    # the lake as a flat floor at its acquisition-time level, so a pool
    # delineated at MDDL finds no water at all (0.01 km2, "empty" reservoir);
    # (2) `area_at_frl_km2` is by definition the area AT FRL, so the
    # reconstruction must be calibrated there. Routing then starts from the
    # initial level on this curve. A starting level above FRL (towards the
    # crest) extends the curve to that level instead.
    frl = scenario.dam.frl_m
    curve_top_m = (
        max(frl, scenario.initial_level_m) if frl is not None else scenario.initial_level_m
    )
    at_frl = frl is not None and curve_top_m == frl

    reservoir_geom = None
    try:
        reservoir_geom = reservoir.build(
            dem,
            nodata_mask,
            snap_row,
            snap_col,
            cell_size_m**2,
            curve_top_m,
            scenario.dam.gross_storage_mcm,
            catchment_mask=catchment,
            # A reservoir bed cannot lie below the dam's own foundation.
            min_bed_elevation_m=(
                scenario.dam.crest_elevation_m - scenario.dam.structural_height_m
                if scenario.dam.crest_elevation_m is not None
                else None
            ),
            published_area_m2=(
                scenario.reservoir.area_at_frl_km2 * 1e6
                if scenario.reservoir.area_at_frl_km2 and (at_frl or frl is None)
                else None
            ),
            area_source=scenario.reservoir.area_source,
        )
        warnings.extend(reservoir_geom.warnings)
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"Reservoir geometry could not be derived: {type(exc).__name__}: {exc}")
        log.exception("reservoir derivation failed")

    # --- 4b. natural blockage: raise the barrier into the solver's terrain ---
    # After the lake curve (built on the pre-event DEM, so its storage is above
    # the pre-event water surface) and before anything the solver reads.
    barrier = None
    release_rc = None
    from floodguard.scenario import DamType

    if (
        scenario.dam.dam_type == DamType.NATURAL_BLOCKAGE
        and scenario.blockage.burn_into_dem
    ):
        from floodguard.preprocess import blockage

        crest_m = scenario.dam.crest_elevation_m
        if crest_m is None:
            raise ValueError(
                "a natural blockage needs dam.crest_elevation_m to be burned into the DEM "
                "(or set blockage.burn_into_dem: false)"
            )
        dem, barrier = blockage.burn_barrier(
            dem, nodata_mask, path_rc, cell_size_m, crest_m,
            base_length_m=scenario.blockage.base_length_m,
        )
        release_rc = barrier.release_rc
        warnings.append(
            f"The natural barrier was BURNED INTO THE DEM: crest {crest_m:g} m, "
            f"{barrier.crest_length_m:,.0f} m across the valley (measured from the terrain), "
            f"{barrier.thickness_m:,.0f} m thick ({barrier.thickness_source}). Lake storage is "
            f"measured above the pre-event water surface "
            f"({barrier.pre_event_water_surface_m:,.1f} m at the barrier point)."
        )
        if not barrier.confined:
            warnings.append(
                f"The burned barrier did not meet ground above its {crest_m:g} m crest within "
                f"{blockage.MAX_HALF_WIDTH_M / 1000:.0f} km on at least one side (or ran into the "
                f"DEM edge / a void). Water can pass around its end, so this crest height is "
                f"not physically consistent with the valley here."
            )
    elif scenario.dam.dam_type == DamType.NATURAL_BLOCKAGE:
        warnings.append(
            "blockage.burn_into_dem is off: the barrier is NOT in the solver's DEM, so breach "
            "outflow can spread upstream into the valley the lake occupies."
        )

    # A catchment that runs to the AOI edge means the pool may be truncated.
    edge_touch = (
        catchment[0, :].any()
        or catchment[-1, :].any()
        or catchment[:, 0].any()
        or catchment[:, -1].any()
    )
    if edge_touch:
        warnings.append(
            f"The dam's catchment ({catchment_km2:.0f} km2 inside the AOI) reaches the "
            f"domain edge, so the reservoir pool may be cut off by the raster boundary "
            f"rather than by terrain. Increase domain.reservoir_buffer_km and re-run "
            f"`floodguard data` if the derived storage looks low."
        )

    # --- 5. cross-sections ---
    xsections, xs_warnings = sections.extract_all(
        dem,
        transform,
        path_rc,
        cell_size_m,
        scenario.towns,
        interval_km=10.0,
        half_width_m=min(4000.0, scenario.domain.corridor_buffer_km * 1000.0),
        crs=crs,
    )
    warnings.extend(xs_warnings)

    # --- 6. Manning's n ---
    # Mapped from ESA WorldCover when `floodguard data` fetched it onto this
    # grid; otherwise an explicitly-labelled uniform field. A land-cover raster
    # on a different grid (an older resolution) is not used, rather than
    # resampled here behind the user's back.
    rough = None
    lc_path = out_dir / "landcover_utm.tif"
    if lc_path.exists():
        with rasterio.open(lc_path) as lc_src:
            if (lc_src.height, lc_src.width) == dem.shape and lc_src.transform == transform:
                from floodguard.preprocess.roughness import ESA_WORLDCOVER_MAP

                rough = roughness.from_landcover(
                    lc_src.read(1),
                    ESA_WORLDCOVER_MAP,
                    scenario.solver.default_manning_n,
                    scenario.solver.manning_n_overrides,
                )
            else:
                warnings.append(
                    "The land-cover raster is on a different grid from the DEM (probably an "
                    "older resolution), so it was not used and Manning's n is uniform. "
                    "Re-run `floodguard data` at this resolution."
                )
    if rough is None:
        rough = roughness.uniform(
            dem.shape, scenario.solver.default_manning_n, scenario.solver.manning_n_overrides
        )
    channel = conditioned.accumulation > max(100.0, 0.001 * conditioned.accumulation.max())
    rough = roughness.burn_channel(rough, channel)

    result = PreprocessResult(
        scenario_id=scenario.id,
        out_dir=out_dir,
        shape=dem.shape,
        cell_size_m=cell_size_m,
        crs=crs,
        transform=transform,
        dam_rc=(dam_row, dam_col),
        dam_snapped_rc=(snap_row, snap_col),
        snap_distance_m=snap_distance_m,
        snap_accumulation_cells=snap_accum,
        path_rc=path_rc,
        path_length_km=path_len_m / 1000.0,
        corridor_cells=int(corridor.sum()),
        corridor_area_km2=float(corridor.sum() * cell_size_m**2 / 1e6),
        dem=dem,
        filled=conditioned.filled,
        corridor=corridor,
        manning=rough.n,
        reservoir=reservoir_geom,
        barrier=barrier,
        release_rc=release_rc,
        cross_sections=xsections,
        catchment_km2=catchment_km2,
        conditioning_stats=stats,
        roughness_stats=rough.stats(),
        warnings=warnings,
        runtime_s=time.perf_counter() - started,
    )

    if write_rasters:
        _write_raster(out_dir / "filled.tif", conditioned.filled, transform, crs, "float32", -9999.0)
        _write_raster(
            out_dir / "flow_accumulation.tif", conditioned.accumulation, transform, crs, "float32", 0
        )
        _write_raster(out_dir / "flow_direction.tif", conditioned.direction, transform, crs, "uint8", 0)
        _write_raster(out_dir / "corridor.tif", corridor.astype(np.uint8), transform, crs, "uint8", 0)
        _write_raster(out_dir / "manning_n.tif", rough.n, transform, crs, "float32", -9999.0)
        if reservoir_geom is not None:
            _write_raster(
                out_dir / "reservoir_pool.tif",
                reservoir_geom.pool_mask.astype(np.uint8),
                transform,
                crs,
                "uint8",
                0,
            )
        np.save(out_dir / "flow_path_rc.npy", path_rc)
        if barrier is not None:
            _write_raster(out_dir / "barrier_mask.tif", barrier.mask.astype(np.uint8),
                          transform, crs, "uint8", 0)
            import rasterio as _rio

            burned_path = out_dir / "dem_barrier_utm.tif"
            _write_raster(burned_path, dem, transform, crs, "float32", -9999.0)
            with _rio.open(burned_path, "r+") as dst:
                dst.update_tags(
                    FG_BARRIER="burned into this DEM (FloodGuard preprocess/blockage.py)",
                    FG_BARRIER_CREST_M=str(barrier.crest_m),
                    FG_BARRIER_CREST_LENGTH_M=f"{barrier.crest_length_m:.0f}",
                    FG_BARRIER_THICKNESS=barrier.thickness_source,
                    FG_SOURCE_DEM="dem_utm.tif (pre-event, unchanged)",
                )

        (out_dir / "preprocess.json").write_text(
            json.dumps(result.to_dict(), indent=2, default=str), encoding="utf-8"
        )

    return result
