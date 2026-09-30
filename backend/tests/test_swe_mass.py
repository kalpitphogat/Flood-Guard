"""Mass conservation where the Tehri presets broke it: steep, fast, wet/dry.

Two defects, both found on the 120 m Tehri presets and both fixed:

1. The breach inflow was added with the CFL timestep, while the step could then
   be shortened by the positivity limit, so water was injected for time that
   never elapsed (3.87e9 m3 in from a 3.53e9 m3 hydrograph).
2. Negative depths from over-draining fluxes were set to zero, creating water
   (7-29% extra volume). The outflow limiter now scales fluxes leaving a cell
   so it cannot lose more than it holds.
"""

from __future__ import annotations

import numpy as np

from floodguard.engines import _swe_kernels as k
from floodguard.engines.swe_fv import ShallowWaterFV, Work


def _steep_slope_sheet(n=40, slope=0.6, depth=0.05, speed=40.0):
    """A thin, fast sheet on a steep bed in a closed box: the Tehri regime."""
    yy, xx = np.mgrid[0:n, 0:n].astype(float)
    dx = 30.0
    z = slope * dx * (n - xx)  # falls steeply towards +x
    h = np.zeros_like(z)
    h[:, 2:8] = depth
    h[10:30, 2:8] += 2.0  # a deeper slug, so the front is uneven
    hu = h * speed
    hv = np.zeros_like(h)
    manning = np.full_like(h, 0.035)
    active = np.ones(h.shape, dtype=np.bool_)
    return h, hu, hv, z, manning, active, dx


def test_closed_steep_domain_conserves_mass_and_creates_nothing():
    h, hu, hv, z, manning, active, dx = _steep_slope_sheet()
    work = Work(z, active)
    v0 = float(h.sum())
    for _ in range(300):
        fastest = k.max_wave_speed(h, hu, hv, active, 1e-3)
        dt = 0.45 * dx / max(fastest, 1e-9)
        dt = ShallowWaterFV._step(
            h, hu, hv, z, manning, active, work, dx, dx, dt, 1e-3, True,
            open_edges=False,
        )
        k.apply_friction(h, hu, hv, manning, active, dt, 1e-3)
    assert (h >= 0).all()
    created, removed = work.clipped
    assert created == 0.0, f"the positivity guard created {created:.3e} m of water"
    final = float(h.sum())
    # Never a gain; any loss is bounded by the sub-millimetre films the dry
    # tolerance removed (RK2 averaging halves a stage-1 removal, so the tally is
    # an upper bound on the loss, not an exact ledger).
    assert final <= v0 * (1 + 1e-12)
    assert v0 - final <= removed + 1e-9


def test_outflow_limiter_caps_a_draining_cell_exactly_at_empty():
    rows, cols = 3, 3
    h = np.zeros((rows, cols))
    h[1, 1] = 0.1
    active = np.ones((rows, cols), dtype=np.bool_)
    fx0 = np.zeros((rows, cols)); fx1 = np.zeros_like(fx0); fx2 = np.zeros_like(fx0)
    fy0 = np.zeros_like(fx0); fyF1 = np.zeros_like(fx0); fy2 = np.zeros_like(fx0)
    fx0[1, 1] = 5.0     # out through the east face
    fx0[1, 0] = -5.0    # out through the west face
    dx = dy = 10.0
    dh = np.zeros_like(fx0); dhu = np.zeros_like(fx0); dhv = np.zeros_like(fx0)
    dh[1, 1] = -(5.0 + 5.0) / dx
    dh[1, 2] = 5.0 / dx
    dh[1, 0] = 5.0 / dx
    phi = np.ones_like(fx0)
    dt = 1.0  # would drain 1.0 m from a 0.1 m cell
    k.outflow_limiter(h, fx0, fx1, fx2, fy0, fyF1, fy2, phi, dh, dhu, dhv, active, dt, dx, dy)
    assert phi[1, 1] == np.float64(0.1)
    new = h + dt * dh
    assert abs(new[1, 1]) < 1e-15            # emptied, not negative
    assert abs(new.sum() - h.sum()) < 1e-15  # what it lost, its neighbours gained


def test_still_water_is_untouched_by_the_limiter():
    n = 20
    yy, xx = np.mgrid[0:n, 0:n]
    z = 0.5 * xx + 0.3 * yy
    level = z.max() + 3.0
    h = level - z
    hu = np.zeros_like(h); hv = np.zeros_like(h)
    manning = np.zeros_like(h)
    active = np.ones(h.shape, dtype=np.bool_)
    work = Work(z, active)
    ShallowWaterFV._step(h, hu, hv, z, manning, active, work, 10.0, 10.0, 0.05, 1e-3, True,
                         open_edges=False)
    assert (work.phi == 1.0).all()


def test_engine_injects_exactly_the_hydrograph_volume_on_a_steep_bed():
    """Regression: inflow used to be added with the CFL dt, before the step
    could shorten dt, so shortened steps injected water for time that never
    elapsed. On steep terrain (where the positivity limit bites) the domain
    received far more than the hydrograph released."""
    from rasterio.transform import from_origin

    from floodguard.engines.base import EngineInput
    from floodguard.engines.swe_fv import ShallowWaterFV as Engine

    rows, cols, cell = 24, 60, 30.0
    xx = np.tile(np.arange(cols, dtype=float), (rows, 1))
    bed = 0.4 * cell * (cols - xx)  # 40% slope, falling towards +x
    q, t_on = 800.0, 900.0
    spec = EngineInput(
        bed_elevation=bed,
        manning_n=np.full((rows, cols), 0.035),
        active=np.ones((rows, cols), dtype=bool),
        cell_size_m=cell,
        transform=from_origin(500000.0, 3300000.0, cell, cell),
        crs="EPSG:32644",
        source_rc=(rows // 2, 2),
        source_cells=[(rows // 2, 2, 1.0), (rows // 2 + 1, 2, 1.0)],
        inflow_q=lambda t: q if t < t_on else 0.0,
        inflow_volume_m3=q * t_on,
        duration_s=1200.0,
        output_interval_s=300.0,
    )
    bundle = Engine().run(spec)
    introduced = bundle.provenance["volume_introduced_m3"]
    assert abs(introduced - q * t_on) / (q * t_on) < 0.01
    assert bundle.provenance["volume_created_by_positivity_m3"] == 0.0
