"""Verification of FloodGuard-SPH against the same analytical solutions.

The SPH engine is the second of the two independent engines, so it is held to
the same exact solutions as FloodGuard-SWE: Ritter and Stoker, plus the
conservation properties the particle formulation guarantees by construction.

Thresholds are looser than the finite-volume ones, stated in advance here and
not tuned per run. SPH recovers depth by kernel smoothing, so it carries an
O(hs^2) smoothing error on top of the discretisation error; published SWE-SPH
schemes report relative depth errors of a few percent on these cases
(Vacondio et al. 2012, Int. J. Numer. Meth. Fluids 69). What is NOT loosened:
the front must never lead the analytical front, and conservation must hold to
round-off.
"""

from __future__ import annotations

import numpy as np

from floodguard.engines.sph_swe import (
    ParticleState,
    SPHDomain,
    SPHSettings,
    SPHSolver,
    solve_1d_dambreak_sph,
)
from floodguard.validation import analytical as exact

SPH_THRESHOLDS = {
    "ritter_relative_l2": 0.08,
    "ritter_dam_depth_pct": 5.0,
    "stoker_relative_l2": 0.08,
    "stoker_shock_spacings": 3.0,
    "volume_error": 1e-12,
    "momentum_error": 1e-10,
    # A still lake over a bumpy bed: spurious speed as a fraction of the
    # shallow-water celerity sqrt(g d). SWE-SPH is not exactly well-balanced;
    # 1% of celerity is ~0.1 m/s on 1 m of water, well below the flood speeds
    # this engine is used for, and is the band reported in the literature.
    "lake_at_rest_froude": 0.01,
}


def _check_cls():
    from floodguard.validation.run import Check

    return Check


def check_sph_ritter(out_dir, spacing_m: float = 5.0):
    from floodguard.validation.run import _plot

    Check = _check_cls()
    h0, x0 = 10.0, 1000.0
    res = solve_1d_dambreak_sph(h_left=h0, spacing_m=spacing_m)
    h_exact, _ = exact.ritter(res["x"], res["t"], h0, x0)
    norms = exact.error_norms(res["h"], h_exact, res["dx"])

    i0 = int(np.argmin(np.abs(res["x"] - x0)))
    dam_depth = float(res["h"][i0])
    dam_expected = exact.ritter_depth_at_dam(h0)
    dam_error_pct = 100.0 * abs(dam_depth - dam_expected) / dam_expected

    wet = res["h"] > 0.001 * h0
    front_num = float(res["x"][wet].max()) if wet.any() else x0
    front_exact = exact.ritter_front_position(res["t"], h0, x0)
    lag = (front_exact - front_num) / (front_exact - x0)

    passed = (
        norms["relative_L2"] < SPH_THRESHOLDS["ritter_relative_l2"]
        and dam_error_pct < SPH_THRESHOLDS["ritter_dam_depth_pct"]
        and lag >= 0.0
    )

    def draw(fig):
        ax = fig.add_subplot(111)
        ax.plot(res["x"], h_exact, "k-", lw=2, label="Ritter (1892) analytical")
        ax.plot(res["x"], res["h"], "C1--", lw=1.6, label="FloodGuard-SPH")
        ax.axvline(front_exact, color="C3", ls=":", lw=1, label="analytical front")
        ax.set_xlabel("x (m)")
        ax.set_ylabel("depth (m)")
        ax.set_title(
            f"SPH Ritter dam break, t = {res['t']:.1f} s, {res['particles']:,} particles "
            f"at {spacing_m:g} m\nrelative L2 = {norms['relative_L2']:.3%}, "
            f"h(dam) error = {dam_error_pct:.2f}%"
        )
        ax.legend()
        ax.grid(alpha=0.3)

    return Check(
        name="SPH: Ritter dry-bed dam break",
        passed=passed,
        metrics={
            **norms,
            "dam_depth_m": dam_depth,
            "dam_depth_error_pct": dam_error_pct,
            "front_numerical_m": front_num,
            "front_analytical_m": front_exact,
            "front_lag_fraction": lag,
            "particles": res["particles"],
            "spacing_m": spacing_m,
            "steps": res["steps"],
        },
        threshold=(
            f"relative L2 {norms['relative_L2']:.3%} < 8%, h(dam) error "
            f"{dam_error_pct:.2f}% < 5%, front lag {lag:.1%} >= 0 (never leads)"
        ),
        note=(
            "The SPH front lags further than the finite-volume front because the kernel "
            "sum under-counts depth within one smoothing length of a free surface. It "
            "lags; it never leads, which is the direction that matters for warning time."
        ),
        plot=_plot(out_dir, "sph_ritter_dam_break", draw),
    )


def check_sph_stoker(out_dir, spacing_m: float = 5.0):
    from floodguard.validation.run import _plot

    Check = _check_cls()
    h0, h1, x0 = 10.0, 2.0, 1000.0
    res = solve_1d_dambreak_sph(h_left=h0, h_right=h1, spacing_m=spacing_m)
    h_exact, _ = exact.stoker(res["x"], res["t"], h0, h1, x0)
    norms = exact.error_norms(res["h"], h_exact, res["dx"])

    downstream = res["x"] > x0
    grad = np.abs(np.gradient(res["h"][downstream], res["dx"]))
    shock_num = float(res["x"][downstream][int(np.argmax(grad))])
    shock_exact = x0 + exact.stoker_shock_speed(h0, h1) * res["t"]
    shock_err = abs(shock_num - shock_exact) / spacing_m

    passed = (
        norms["relative_L2"] < SPH_THRESHOLDS["stoker_relative_l2"]
        and shock_err < SPH_THRESHOLDS["stoker_shock_spacings"]
    )

    def draw(fig):
        ax = fig.add_subplot(111)
        ax.plot(res["x"], h_exact, "k-", lw=2, label="Stoker (1957) analytical")
        ax.plot(res["x"], res["h"], "C1--", lw=1.6, label="FloodGuard-SPH")
        ax.axvline(shock_exact, color="C3", ls=":", lw=1, label="analytical shock")
        ax.set_xlabel("x (m)")
        ax.set_ylabel("depth (m)")
        ax.set_title(
            f"SPH Stoker dam break, t = {res['t']:.1f} s\n"
            f"relative L2 = {norms['relative_L2']:.3%}, shock within "
            f"{shock_err:.1f} particle spacings"
        )
        ax.legend()
        ax.grid(alpha=0.3)

    return Check(
        name="SPH: Stoker wet-bed dam break",
        passed=passed,
        metrics={
            **norms,
            "shock_numerical_m": shock_num,
            "shock_analytical_m": shock_exact,
            "shock_error_spacings": shock_err,
            "particles": res["particles"],
        },
        threshold=(
            f"relative L2 {norms['relative_L2']:.3%} < 8%, shock within "
            f"{shock_err:.1f} < 3 spacings"
        ),
        note=(
            "The shock is captured by Monaghan artificial viscosity rather than by a "
            "Riemann solver, which is what makes this an independent check on the "
            "finite-volume result rather than the same numerics twice."
        ),
        plot=_plot(out_dir, "sph_stoker_dam_break", draw),
    )


def check_sph_conservation(out_dir):
    """Volume and momentum, exactly, for a collapsing hump on a flat bed.

    Particles carry fixed volumes, and every pair force is applied equal and
    opposite, so both invariants must hold to round-off — not approximately.
    """
    Check = _check_cls()
    dx = 5.0
    rows, cols = 16, 200
    bed = np.zeros((rows, cols))
    active = np.ones((rows, cols), dtype=bool)
    domain = SPHDomain(bed, active, np.zeros((rows, cols)), dx, period_y=rows * dx)

    xs = np.arange(0.5 * dx, cols * dx, dx)
    ys = np.arange(0.5 * dx, rows * dx, dx)
    gx, gy = np.meshgrid(xs, ys)
    centre = cols * dx / 2.0
    depth0 = 1.0 + 4.0 * np.exp(-(((gx - centre) / 60.0) ** 2))
    keep = np.abs(gx - centre) < 300.0  # stay clear of the raster edge
    n = int(keep.sum())
    state = ParticleState.allocate(n)
    state.px[:n] = gx[keep]
    state.py[:n] = gy[keep]
    state.vol[:n] = depth0[keep] * dx * dx
    state.n = n

    cfg = SPHSettings(sample_interval_s=1e9)
    solver = SPHSolver(domain, state, cfg)
    solver.initialise()

    v0 = float(state.vol[:n].sum())
    t = 0.0
    speed_scale = 0.0
    while t < 5.0:
        solver.accelerations()
        dt = min(solver.stable_dt(), 5.0 - t)
        solver.advance(dt)
        t += dt
        speed_scale = max(speed_scale, float(np.abs(state.vx[: state.n]).max()))

    v1 = float(state.vol[: state.n].sum())
    mx = float(np.sum(state.vol[: state.n] * state.vx[: state.n]))
    my = float(np.sum(state.vol[: state.n] * state.vy[: state.n]))
    # Normalise by the momentum the flow actually carries in one direction,
    # which is what round-off accumulates against.
    right = state.vx[: state.n] > 0
    carried = float(np.sum(state.vol[: state.n][right] * state.vx[: state.n][right]))
    vol_err = abs(v1 - v0) / v0
    mom_err = float(np.hypot(mx, my)) / max(carried, 1e-30)

    passed = (
        state.n == n
        and vol_err < SPH_THRESHOLDS["volume_error"]
        and mom_err < SPH_THRESHOLDS["momentum_error"]
    )
    return Check(
        name="SPH: exact volume and momentum conservation",
        passed=passed,
        metrics={
            "relative_volume_error": vol_err,
            "relative_momentum_error": mom_err,
            "momentum_carried_m4s": carried,
            "max_speed_ms": speed_scale,
            "particles": n,
            "t_s": t,
        },
        threshold=(
            f"volume error {vol_err:.1e} < 1e-12, net momentum {mom_err:.1e} "
            f"of carried < 1e-10"
        ),
        note=(
            "A symmetric hump collapses into two waves moving in opposite directions; the "
            "net momentum must stay zero. This is the test that proves the pair forces "
            "really are equal and opposite — and that the kernel is actually evaluated."
        ),
    )


def check_sph_lake_at_rest(out_dir):
    """Still water over a sinusoidal bed: how much spurious motion appears.

    SWE-SPH is not exactly well-balanced, and this check measures by how much,
    rather than asserting a property the method does not have.
    """
    Check = _check_cls()
    dx = 5.0
    rows, cols = 16, 400
    x = (np.arange(cols) + 0.5) * dx
    bed_row = 0.5 + 0.4 * np.sin(2 * np.pi * x / 250.0)
    bed = np.tile(bed_row, (rows, 1))
    active = np.ones((rows, cols), dtype=bool)
    active[:, 0] = False
    active[:, -1] = False
    domain = SPHDomain(bed, active, np.zeros((rows, cols)), dx, period_y=rows * dx)

    surface = 2.0
    xs = np.arange(dx + 0.5 * dx, (cols - 1) * dx, dx)
    ys = np.arange(0.5 * dx, rows * dx, dx)
    gx, gy = np.meshgrid(xs, ys)
    z_at = 0.5 + 0.4 * np.sin(2 * np.pi * gx / 250.0)
    n = gx.size
    state = ParticleState.allocate(n)
    state.px[:n] = gx.ravel()
    state.py[:n] = gy.ravel()
    state.vol[:n] = (surface - z_at).ravel() * dx * dx
    state.n = n

    solver = SPHSolver(domain, state, SPHSettings(sample_interval_s=1e9))
    solver.initialise()

    duration = 30.0
    t = 0.0
    while t < duration:
        solver.accelerations()
        dt = min(solver.stable_dt(), duration - t)
        solver.advance(dt)
        t += dt

    # Measure away from the end walls, whose kernel truncation is a separate
    # (boundary) effect travelling in at sqrt(g d).
    centre = (cols * dx) / 2.0
    celerity = float(np.sqrt(9.81 * surface))
    reach = 0.5 * cols * dx - celerity * duration - 4 * dx
    mid = np.abs(state.px[: state.n] - centre) < max(reach, 50.0)
    speed = np.hypot(state.vx[: state.n][mid], state.vy[: state.n][mid])
    depth = np.maximum(state.depth[: state.n][mid], 1e-6)
    froude = speed / np.sqrt(9.81 * depth)
    max_fr = float(froude.max())
    passed = max_fr < SPH_THRESHOLDS["lake_at_rest_froude"]

    return Check(
        name="SPH: lake at rest (measured, not exact)",
        passed=passed,
        metrics={
            "max_spurious_speed_ms": float(speed.max()),
            "max_spurious_froude": max_fr,
            "rms_spurious_speed_ms": float(np.sqrt(np.mean(speed**2))),
            "t_s": t,
            "particles_measured": int(mid.sum()),
        },
        threshold=f"spurious Froude {max_fr:.2e} < 1e-2",
        note=(
            "Unlike FloodGuard-SWE, which is well-balanced to round-off, SPH balances the "
            "kernel depth gradient against the DEM bed slope only approximately. This "
            "measures the residual. It is orders of magnitude below dam-break flow speeds, "
            "but it is why FloodGuard-SWE, not SPH, is the primary engine for the KPIs."
        ),
    )


def check_sph_convergence(out_dir, spacings=(20.0, 10.0, 5.0, 2.5)):
    """Error must fall as the particle spacing is refined."""
    Check = _check_cls()
    errors = []
    for sp in spacings:
        res = solve_1d_dambreak_sph(spacing_m=sp)
        h_exact, _ = exact.ritter(res["x"], res["t"], 10.0, 1000.0)
        errors.append(exact.error_norms(res["h"], h_exact, res["dx"])["relative_L2"])
    order = float(np.polyfit(np.log(spacings), np.log(errors), 1)[0])
    monotone = all(b < a for a, b in zip(errors, errors[1:]))
    return Check(
        name="SPH: convergence under particle refinement",
        passed=monotone and order > 0.0,
        metrics={
            "spacings_m": list(spacings),
            "relative_L2": errors,
            "observed_order": order,
        },
        threshold=(
            f"error falls monotonically ({' > '.join(f'{e:.2%}' for e in errors)}), "
            f"observed order {order:.2f}"
        ),
        note=(
            "SPH at a fixed smoothing-length-to-spacing ratio converges slowly — the "
            "kernel smoothing error does not vanish with spacing alone. The order is "
            "reported, not dressed up: it is well below the finite-volume solver's."
        ),
    )


SPH_CHECKS = (
    check_sph_ritter,
    check_sph_stoker,
    check_sph_conservation,
    check_sph_lake_at_rest,
    check_sph_convergence,
)
