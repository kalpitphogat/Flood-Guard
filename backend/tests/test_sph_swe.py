"""FloodGuard-SPH: the second, independent engine.

Tested for the same properties as FloodGuard-SWE — it floods downstream, its
numbers are computed, its provenance is complete — and for the two properties
specific to a particle method: the kernel is genuinely what produces the depth
(the defect the Phase 0 audit found elsewhere), and the pair forces are
exactly equal and opposite.
"""

from __future__ import annotations

import numpy as np
import pytest

from floodguard.engines import _sph_kernels as k
from floodguard.engines.base import EngineInput
from floodguard.engines.sph_swe import (
    ParticleState,
    SmoothedParticleSWE,
    SPHDomain,
    SPHSettings,
    SPHSolver,
    solve_1d_dambreak_sph,
)
from floodguard.validation import analytical as exact

FAST = SPHSettings(target_particles=6_000, sample_interval_s=10.0)


def make_spec(**overrides) -> EngineInput:
    """The same sloping valley FloodGuard-SWE is tested on."""
    rows, cols = 30, 60
    yy, xx = np.mgrid[0:rows, 0:cols]
    z = 100.0 - 0.5 * xx + 0.8 * np.abs(yy - rows // 2)
    spec = dict(
        bed_elevation=z,
        manning_n=np.full((rows, cols), 0.03),
        active=np.ones((rows, cols), dtype=bool),
        cell_size_m=50.0,
        transform=None,
        crs="EPSG:32644",
        source_rc=(rows // 2, 2),
        source_cells=[(rows // 2, 2, 1.0), (rows // 2 + 1, 2, 0.6), (rows // 2 - 1, 2, 0.6)],
        source_direction=(0.0, 1.0),
        inflow_q=lambda t: 2000.0 if t < 600.0 else 0.0,
        inflow_volume_m3=2000.0 * 600.0,
        duration_s=1200.0,
        output_interval_s=300.0,
        wet_threshold_m=0.3,
    )
    spec.update(overrides)
    return EngineInput(**spec)


@pytest.fixture(scope="module")
def result():
    return SmoothedParticleSWE(FAST).run(make_spec())


# --- labelling ----------------------------------------------------------------------


def test_sph_is_labelled_as_depth_integrated_and_never_as_pysph(result):
    name = result.display_name
    assert "SPH" in name and "depth-integrated" in name
    assert "PySPH" not in name and "DualSPHysics" not in name
    assert "not a 3D WCSPH" in result.provenance["not_3d_sph"]


def test_sph_is_listed_as_an_available_native_engine():
    from floodguard.engines.availability import resolve

    status = resolve("sph_swe")
    assert status.available
    assert status.display_name == SmoothedParticleSWE.display_name


def test_pysph_requests_substitute_to_our_sph_and_say_so():
    from floodguard.engines.availability import resolve
    from floodguard.pipeline import _select_engine

    if resolve("sph_pysph").available:
        pytest.skip("PySPH is installed here")
    run = _select_engine("sph_pysph")
    assert run.actual_id == "sph_swe"
    assert run.substituted
    assert "not available" in run.honesty_note()


# --- the kernel is real ------------------------------------------------------------


def test_wendland_kernel_integrates_to_one():
    h = 3.0
    xs = np.linspace(-2 * h, 2 * h, 401)
    step = xs[1] - xs[0]
    gx, gy = np.meshgrid(xs, xs)
    r = np.hypot(gx, gy)
    total = sum(k.kernel_w(float(ri), h) for ri in r.ravel()) * step * step
    assert total == pytest.approx(1.0, rel=2e-3)


def test_kernel_derivative_matches_finite_difference():
    h, r, eps = 2.0, 1.3, 1e-6
    fd = (k.kernel_w(r + eps, h) - k.kernel_w(r - eps, h)) / (2 * eps)
    assert k.kernel_dwdr(r, h) == pytest.approx(fd, rel=1e-5)


def test_depth_is_the_kernel_sum_and_recovers_a_uniform_layer():
    """Particles on a lattice with volume d*s^2 must sum back to depth d."""
    s, d = 5.0, 3.0
    rows, cols = 12, 40
    domain = SPHDomain(
        np.zeros((rows, cols)), np.ones((rows, cols), bool), np.zeros((rows, cols)), s,
        period_y=rows * s,
    )
    xs = np.arange(0.5 * s, cols * s, s)
    ys = np.arange(0.5 * s, rows * s, s)
    gx, gy = np.meshgrid(xs, ys)
    n = gx.size
    state = ParticleState.allocate(n)
    state.px[:n], state.py[:n] = gx.ravel(), gy.ravel()
    state.vol[:n] = d * s * s
    state.n = n
    solver = SPHSolver(domain, state, SPHSettings())
    solver.initialise()
    interior = np.abs(state.px[:n] - cols * s / 2) < cols * s / 4
    # The compact-support kernel is integrated on a finite particle lattice
    # with the production smoothing-length clamp, so the discrete quadrature
    # carries a small, deterministic bias even away from the boundaries.
    assert np.allclose(state.depth[:n][interior], d, rtol=1e-2)
    # And zeroing the volume must zero the depth: the kernel is actually used.
    state.vol[:n] = 0.0
    solver.initialise()
    assert np.all(state.depth[:n] == 0.0)


# --- analytical ------------------------------------------------------------------


def test_sph_ritter_error_is_within_the_stated_band():
    res = solve_1d_dambreak_sph(spacing_m=10.0)
    h_exact, _ = exact.ritter(res["x"], res["t"], 10.0, 1000.0)
    assert exact.error_norms(res["h"], h_exact, res["dx"])["relative_L2"] < 0.08


def test_sph_front_never_outruns_ritter():
    res = solve_1d_dambreak_sph(spacing_m=10.0)
    wet = res["h"] > 0.01
    assert res["x"][wet].max() <= exact.ritter_front_position(res["t"], 10.0, 1000.0)


def test_sph_conserves_volume_and_momentum_exactly():
    from floodguard.validation.sph_checks import check_sph_conservation

    check = check_sph_conservation(None)
    assert check.passed, check.threshold
    assert check.metrics["relative_momentum_error"] < 1e-12


# --- full engine -----------------------------------------------------------------


def test_sph_engine_floods_downstream(result):
    assert result.steps > 0
    assert result.max_depth.max() > 0.3
    wet_cols = np.nonzero((result.max_depth > 0.3).any(axis=0))[0]
    assert wet_cols.max() > 10


def test_sph_summary_is_computed_not_hardcoded(result):
    s = result.summary()
    for key in ("flooded_area_km2", "max_depth_m", "max_velocity_ms", "earliest_arrival_min"):
        assert s[key] is not None and np.isfinite(s[key])
    assert s["max_depth_m"] == pytest.approx(result.max_depth.max())


def test_sph_mass_is_accounted_for(result):
    p = result.provenance
    total = p["volume_in_domain_m3"] + p["volume_left_domain_m3"] + p[
        "volume_pending_in_injector_m3"
    ]
    # Every injected particle is either still in the domain or left through
    # the edge: exact, because particle volumes never change.
    assert result.mass_error < 1e-9
    # And what was injected is the hydrograph's volume, to quadrature accuracy.
    assert total == pytest.approx(p["volume_released_in_window_m3"], rel=0.03)


def test_sph_arrival_increases_downstream(result):
    mid = result.arrival_time_s.shape[0] // 2
    row = result.arrival_time_s[mid]
    arrived = np.nonzero(row >= 0)[0]
    assert arrived.size > 3
    assert row[arrived][-1] > row[arrived][0]


def test_sph_frames_share_the_solver_grid(result):
    assert len(result.frames) >= 2
    assert all(f.shape == result.max_depth.shape for _, f in result.frames)


def test_sph_and_fv_agree_on_where_the_water_goes(result):
    """Two independent discretisations of the same physics must broadly agree.

    Not identical — that would be suspicious — but the extents must overlap
    far better than chance.
    """
    from floodguard.compare.metrics import extent_agreement
    from floodguard.engines.swe_fv import ShallowWaterFV

    fv = ShallowWaterFV().run(make_spec())
    agreement = extent_agreement(fv.max_depth, result.max_depth)
    assert agreement["critical_success_index"] > 0.5


def test_sph_rejects_a_release_point_outside_the_domain():
    active = np.ones((30, 60), dtype=bool)
    active[15, 2] = False
    with pytest.raises(ValueError, match="outside the active domain"):
        SmoothedParticleSWE(FAST).run(make_spec(active=active))


def test_sph_refuses_an_empty_hydrograph():
    with pytest.raises(ValueError, match="releases no water"):
        SmoothedParticleSWE(FAST).run(
            make_spec(inflow_q=lambda t: 0.0, inflow_volume_m3=0.0)
        )
