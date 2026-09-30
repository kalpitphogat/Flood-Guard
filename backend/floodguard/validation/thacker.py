"""Thacker (1981) planar oscillation in a parabolic bowl, and the NSE metric.

Thacker, W.C. (1981). Some exact solutions to the nonlinear shallow-water wave
equations. J. Fluid Mech. 107, 499-508.

Bed b(x) = h0 (x/a)^2. The free surface stays a straight line that rocks
about the bowl axis while the whole water body sloshes with a spatially
uniform velocity:

    omega    = sqrt(2 g h0) / a
    u(t)     = -U0 sin(omega t)
    beta(t)  = (U0 omega / g) cos(omega t)                      (surface slope)
    eta(x,t) = eta0 - (U0 beta0 / (4 omega)) cos(2 omega t) + beta(t) x

Substituting shows both SWE residuals vanish exactly: momentum because
du/dt = -g beta, continuity because beta0 = U0 omega / g and omega^2 = 2 g h0 / a^2.

It is the one classical test with a MOVING SHORELINE OVER A CURVED BED, which is
what a dam-break front does on real terrain. The pass criterion is the period,
2 pi a / sqrt(2 g h0): every finite-volume scheme with a wet/dry threshold damps
the amplitude, but a wrong period means the momentum balance itself is wrong.

The Nash-Sutcliffe efficiency (Nash & Sutcliffe 1970) of the simulated against
the exact velocity series is reported alongside. It is a descriptive score,
not the pass criterion: no standard NSE threshold exists for analytical
benchmarks (Moriasi et al. 2007 treat NSE > 0.5 as "satisfactory" for
watershed models, a different use).
"""

from __future__ import annotations

from typing import Any

import numpy as np

G = 9.81
PERIOD_TOLERANCE_PCT = 5.0

NSE_REFERENCE = (
    "Nash, J.E. & Sutcliffe, J.V. (1970). River flow forecasting through conceptual "
    "models part I. J. Hydrology 10(3), 282-290."
)
THACKER_REFERENCE = (
    "Thacker, W.C. (1981). Some exact solutions to the nonlinear shallow-water wave "
    "equations. J. Fluid Mech. 107, 499-508."
)


def nash_sutcliffe(observed, simulated) -> float | None:
    """NSE = 1 - sum((obs - sim)^2) / sum((obs - mean(obs))^2).

    1 is perfect; 0 means no better than the mean of the observations; negative
    is worse than the mean. None when the observations have no variance (the
    score is undefined, not zero).
    """
    obs = np.asarray(observed, dtype=float)
    sim = np.asarray(simulated, dtype=float)
    if obs.shape != sim.shape:
        raise ValueError(f"shape mismatch: {obs.shape} vs {sim.shape}")
    ok = np.isfinite(obs) & np.isfinite(sim)
    obs, sim = obs[ok], sim[ok]
    if obs.size < 2:
        return None
    denom = float(np.sum((obs - obs.mean()) ** 2))
    if denom <= 0.0:
        return None
    return 1.0 - float(np.sum((obs - sim) ** 2)) / denom


def thacker_exact(x, t, h0: float, a: float, u0: float, eta0: float):
    """(surface elevation, velocity, omega) at positions x and time t."""
    omega = np.sqrt(2.0 * G * h0) / a
    beta0 = u0 * omega / G
    eta = eta0 - (u0 * beta0 / (4.0 * omega)) * np.cos(2.0 * omega * t) \
        + beta0 * np.cos(omega * t) * np.asarray(x, dtype=float)
    return eta, -u0 * np.sin(omega * t), omega


def run_thacker(
    n_cells: int = 400,
    *,
    h0: float = 10.0,
    a: float = 1000.0,
    u0: float = 2.0,
    eta0: float = 10.0,
    periods: float = 2.5,
    cfl: float = 0.45,
    dry_tolerance_m: float = 1e-3,
) -> dict[str, Any]:
    """Run FloodGuard-SWE's production kernels on the bowl; sample the wet-mean velocity."""
    from floodguard.engines import _swe_kernels as k
    from floodguard.engines.swe_fv import ShallowWaterFV, Work

    half_width = 1.5 * a  # the shoreline stays well inside the domain
    dx = 2.0 * half_width / n_cells
    x = -half_width + (np.arange(n_cells) + 0.5) * dx
    rows = 3
    z = np.tile(h0 * (x / a) ** 2, (rows, 1))
    eta_init, u_init, omega = thacker_exact(x, 0.0, h0, a, u0, eta0)
    h = np.tile(np.maximum(eta_init - z[0], 0.0), (rows, 1))
    hu = h * np.where(h > 0, u_init, 0.0)
    hv = np.zeros_like(h)
    manning = np.zeros_like(h)  # frictionless: friction would confound the period
    active = np.ones_like(h, dtype=np.bool_)
    work = Work(z, active)

    period = 2.0 * np.pi / omega
    t_end = periods * period
    sample_every = period / 200.0
    next_sample = 0.0
    t = 0.0
    times, u_sim = [], []
    steps = 0
    while t < t_end and steps < 500_000:
        if t >= next_sample:
            wet = h[1] > 0.05
            if wet.any():
                times.append(t)
                u_sim.append(float(np.mean(hu[1][wet] / h[1][wet])))
            next_sample += sample_every
        fastest = k.max_wave_speed(h, hu, hv, active, dry_tolerance_m)
        if fastest < 1e-12:
            break
        dt = min(cfl * dx / fastest, t_end - t)
        if dt <= 0:
            break
        dt = ShallowWaterFV._step(
            h, hu, hv, z, manning, active, work, dx, dx, dt, dry_tolerance_m, True,
        )
        t += dt
        steps += 1

    times_a = np.array(times)
    u_a = np.array(u_sim)
    _, u_exact, _ = thacker_exact(0.0, times_a, h0, a, u0, eta0)

    crossings = []
    for i in np.where(np.sign(u_a[:-1]) != np.sign(u_a[1:]))[0]:
        crossings.append(
            times_a[i] + (times_a[i + 1] - times_a[i]) * u_a[i] / (u_a[i] - u_a[i + 1])
        )
    measured = float(2.0 * np.mean(np.diff(crossings))) if len(crossings) >= 3 else None
    return {
        "times_s": times_a,
        "u_sim": u_a,
        "u_exact": np.asarray(u_exact, dtype=float),
        "period_exact_s": float(period),
        "period_measured_s": measured,
        "zero_crossings": len(crossings),
        "nse_velocity": nash_sutcliffe(u_exact, u_a),
        "finite": bool(np.isfinite(h).all() and np.isfinite(hu).all()),
        "steps": steps,
        "dx": dx,
    }


def check_thacker(out_dir, n_cells: int = 400):
    """The validation-gate Check for the Thacker bowl."""
    from floodguard.validation.run import Check, _plot

    res = run_thacker(n_cells)
    measured = res["period_measured_s"]
    err_pct = (
        abs(measured - res["period_exact_s"]) / res["period_exact_s"] * 100.0
        if measured is not None else None
    )
    passed = bool(res["finite"] and err_pct is not None and err_pct <= PERIOD_TOLERANCE_PCT)

    def draw(fig):
        ax = fig.add_subplot(111)
        ax.plot(res["times_s"], res["u_exact"], "k-", lw=2, label="Thacker (1981), exact")
        ax.plot(res["times_s"], res["u_sim"], "C0--", label="FloodGuard-SWE, wet-mean velocity")
        ax.set_xlabel("t (s)")
        ax.set_ylabel("velocity (m/s)")
        nse = res["nse_velocity"]
        ax.set_title(
            "Thacker parabolic bowl: period "
            f"{measured if measured is None else round(measured, 1)} s vs exact "
            f"{res['period_exact_s']:.1f} s; NSE {nse if nse is None else round(nse, 3)}"
        )
        ax.legend()
        ax.grid(alpha=0.3)

    return Check(
        name="Thacker parabolic bowl (moving shoreline)",
        passed=passed,
        metrics={
            "period_exact_s": res["period_exact_s"],
            "period_measured_s": measured,
            "period_error_pct": err_pct,
            "zero_crossings": res["zero_crossings"],
            "nse_velocity": res["nse_velocity"],
            "cells": n_cells,
            "dx_m": res["dx"],
            "steps": res["steps"],
        },
        threshold=(
            f"period error {err_pct:.2f}% <= {PERIOD_TOLERANCE_PCT:.0f}%"
            if err_pct is not None else "oscillation died out before 3 zero crossings"
        ),
        note=(
            f"{THACKER_REFERENCE} Pass criterion: the oscillation period. The NSE of the "
            f"velocity series ({NSE_REFERENCE}) is reported as a descriptive score only; "
            "amplitude damping lowers it without indicating a momentum error."
        ),
        plot=_plot(out_dir, "thacker_bowl", draw),
    )
