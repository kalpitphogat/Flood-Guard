"""Thacker (1981) bowl and the Nash-Sutcliffe efficiency."""

from __future__ import annotations

import numpy as np
import pytest

from floodguard.validation import thacker as th


def test_exact_solution_satisfies_both_swe_residuals():
    h0, a, u0, eta0 = 10.0, 1000.0, 2.0, 12.0
    x = np.linspace(-400.0, 400.0, 9)
    t, dt = 30.0, 1e-3
    eta_m, u_m, _ = th.thacker_exact(x, t - dt, h0, a, u0, eta0)
    eta_0, u_0, _ = th.thacker_exact(x, t, h0, a, u0, eta0)
    eta_p, u_p, _ = th.thacker_exact(x, t + dt, h0, a, u0, eta0)
    slope = np.polyfit(x, eta_0, 1)[0]
    assert abs((u_p - u_m) / (2 * dt) + th.G * slope) < 1e-6  # momentum
    bed = h0 * (x / a) ** 2
    dh_dt = ((eta_p - bed) - (eta_m - bed)) / (2 * dt)
    dh_dx = np.gradient(eta_0 - bed, x, edge_order=2)
    assert np.max(np.abs(dh_dt + u_0 * dh_dx)) < 1e-6  # continuity


def test_nse_properties():
    obs = np.array([1.0, 2.0, 3.0, 4.0])
    assert th.nash_sutcliffe(obs, obs) == pytest.approx(1.0)
    assert th.nash_sutcliffe(obs, np.full(4, obs.mean())) == pytest.approx(0.0)
    assert th.nash_sutcliffe(obs, obs[::-1]) < 0
    assert th.nash_sutcliffe(np.ones(4), np.ones(4)) is None  # undefined, not 0


def test_floodguard_swe_reproduces_the_thacker_period(tmp_path):
    check = th.check_thacker(tmp_path, n_cells=200)
    assert check.passed, check.threshold
    assert check.metrics["period_error_pct"] < th.PERIOD_TOLERANCE_PCT
    assert check.metrics["nse_velocity"] > 0.9
