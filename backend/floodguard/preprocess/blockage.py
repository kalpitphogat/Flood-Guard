"""A river blockage burned into the DEM.

A real dam is in the DEM: the embankment or the concrete stands between the
reservoir and the valley below, so water the solver releases downstream of it
cannot run back upstream. A landslide barrier being assessed *before* it forms
(or a hypothetical one) is not in the DEM at all. Without it, the breach
outflow injected below the barrier point spreads upstream into the empty valley
where the lake would be, and the downstream flood is understated.

So for a natural blockage the barrier is raised into the terrain the solver
runs on:

* a wall across the valley, perpendicular to the traced flow path at the
  snapped barrier point, walked outward on both sides until the ground reaches
  the crest elevation (the valley wall) — its crest length is therefore
  measured from the terrain, not assumed;
* its thickness along the river is `blockage.base_length_m` when given; when not,
  two cells, which is a NUMERICAL minimum that stops flow leaking through a
  one-cell line, not a claim about the barrier's size;
* cells below the crest are raised to the crest; ground already above it is
  left alone.

The lake's stage-storage curve is built from the PRE-EVENT DEM, before this
burn, so it measures storage above the pre-event water surface (a surface
model records the river's own water surface, so the river's pre-event flow is
never counted as releasable lake water).

The breach itself is not carved into the burned wall: as for an engineered
dam, the routed breach hydrograph is injected just downstream of the barrier.
Every output that used a burned barrier says so (preprocess.json `barrier`,
the burned DEM's tags, and a run warning).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

#: How far each way the wall is walked before it is declared unconfined, m.
MAX_HALF_WIDTH_M = 5000.0
#: Thickness when no base length is given, cells (numerical minimum).
MIN_THICKNESS_CELLS = 2


@dataclass
class Barrier:
    mask: np.ndarray
    crest_m: float
    crest_length_m: float
    thickness_m: float
    thickness_source: str
    cells_raised: int
    raised_volume_m3: float
    pre_event_water_surface_m: float
    confined: bool
    release_rc: tuple[int, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "burned_into_dem": True,
            "crest_m": self.crest_m,
            "crest_length_m": round(self.crest_length_m, 1),
            "thickness_m": round(self.thickness_m, 1),
            "thickness_source": self.thickness_source,
            "cells_raised": self.cells_raised,
            "raised_volume_m3": round(self.raised_volume_m3, 0),
            "pre_event_water_surface_m": round(self.pre_event_water_surface_m, 2),
            "confined_by_valley_walls": self.confined,
            "release_cell": list(self.release_rc),
            "note": (
                "Barrier raised into the solver's DEM across the valley at the barrier "
                "point. Lake storage is measured on the pre-event DEM, i.e. above the "
                "pre-event water surface. The breach outflow is injected just downstream."
            ),
        }


def _downstream_unit(path_rc: np.ndarray, start: int = 0, window: int = 6) -> tuple[float, float]:
    end = min(start + window, len(path_rc) - 1)
    if end <= start:
        return (0.0, 1.0)
    d = np.asarray(path_rc[end], dtype=float) - np.asarray(path_rc[start], dtype=float)
    n = float(np.hypot(*d))
    return (0.0, 1.0) if n < 1e-9 else (float(d[0] / n), float(d[1] / n))


def burn_barrier(
    dem: np.ndarray,
    nodata_mask: np.ndarray,
    path_rc: np.ndarray,
    cell_size_m: float,
    crest_m: float,
    base_length_m: float | None = None,
    max_half_width_m: float = MAX_HALF_WIDTH_M,
) -> tuple[np.ndarray, Barrier]:
    """Return (burned DEM copy, Barrier). `path_rc[0]` is the snapped barrier cell."""
    if len(path_rc) < 2:
        raise ValueError("the traced flow path is too short to orient a barrier across it")
    rows, cols = dem.shape
    r0, c0 = (int(path_rc[0][0]), int(path_rc[0][1]))
    dr, dc = _downstream_unit(path_rc)
    pr, pc = -dc, dr  # perpendicular, across the valley

    if base_length_m:
        n_thick = max(1, int(math.ceil(base_length_m / cell_size_m)))
        thickness_source = f"blockage.base_length_m = {base_length_m:g} m"
    else:
        n_thick = MIN_THICKNESS_CELLS
        thickness_source = (
            f"{MIN_THICKNESS_CELLS} cells: a numerical minimum to stop leakage, not the "
            f"barrier's real base length (none was given)"
        )

    mask = np.zeros(dem.shape, dtype=bool)
    confined = True
    extent_m = [0.0, 0.0]
    step = 0.5  # half-cell steps, so the wall is 4-connected
    max_steps = int(max_half_width_m / (step * cell_size_m)) + 1

    for s in range(n_thick):
        # Wall runs upstream from the snapped cell: the snapped cell is its
        # downstream face, so the release point is the next cell down the path.
        cr, cc = r0 - s * dr, c0 - s * dc
        for side_i, side in enumerate((1.0, -1.0)):
            reached_wall = False
            for k in range(max_steps):
                r = int(round(cr + side * k * step * pr))
                c = int(round(cc + side * k * step * pc))
                if not (0 <= r < rows and 0 <= c < cols) or nodata_mask[r, c]:
                    break
                if dem[r, c] >= crest_m:
                    reached_wall = True
                    break
                mask[r, c] = True
                if s == 0:
                    extent_m[side_i] = k * step * cell_size_m
            if not reached_wall:
                confined = False

    burned = dem.copy()
    raise_by = np.where(mask, crest_m - dem, 0.0)
    burned[mask] = crest_m

    release = None
    for rc in path_rc[1:]:
        if not mask[int(rc[0]), int(rc[1])]:
            release = (int(rc[0]), int(rc[1]))
            break
    if release is None:
        raise ValueError("no flow-path cell lies downstream of the burned barrier")

    return burned, Barrier(
        mask=mask,
        crest_m=float(crest_m),
        crest_length_m=extent_m[0] + extent_m[1] + cell_size_m,
        thickness_m=n_thick * cell_size_m,
        thickness_source=thickness_source,
        cells_raised=int(mask.sum()),
        raised_volume_m3=float(raise_by.sum() * cell_size_m**2),
        pre_event_water_surface_m=float(dem[r0, c0]),
        confined=confined,
        release_rc=release,
    )
