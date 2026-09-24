"""FloodGuard-SPH: depth-integrated Smoothed Particle Hydrodynamics.

The second, independent hydrodynamic engine
--------------------------------------------
The problem statement asks for two engines — SPH and a Delft3D-class solver —
run on the same scenario and compared quantitatively. FloodGuard-SWE is the
Eulerian finite-volume solver. This is the SPH one.

It solves the same depth-averaged shallow-water equations, but with numerics
that share nothing with the finite-volume code: water is a set of Lagrangian
particles of fixed volume, there is no mesh and no Riemann solver, depth is a
kernel summation over neighbours, and shocks are captured by artificial
viscosity rather than upwinding. Two discretisations that agree on the same
physics bound the numerical uncertainty; where they disagree, the difference
raster shows where to distrust both.

What it is NOT
--------------
It is not a 3D weakly-compressible SPH of the breach near field — that is what
PySPH or DualSPHysics would provide, and their case decks are generated
separately. The label on every output therefore reads
"FloodGuard-SPH (depth-integrated SWE-SPH)", never "PySPH", never
"DualSPHysics". A depth-averaged result under a 3D SPH label is exactly the
defect the Phase 0 audit found in a reference repository.

Formulation
-----------
* Depth by kernel summation, d_i = sum_j V_j W(r_ij, hs_i)
* Variable smoothing length hs_i = eta * sqrt(V_i / d_i), clamped
* Wendland C2 kernel (no pairing instability)
* Symmetric pressure gradient from the gas-dynamics analogy, P/rho^2 = g/2
* Monaghan (1992) artificial viscosity for shock capture
* Bed slope -g grad(z), bilinear in the particle position
* Semi-implicit Manning friction, symplectic Euler in time
* Breach inflow: particles injected over the breach face at critical-flow
  velocity sqrt(g d_c), d_c = (q_w^2 / g)^(1/3) from the unit discharge

References: Monaghan (1992) Annu. Rev. Astron. Astrophys. 30; Wang & Shen
(1999) Int. J. Numer. Meth. Fluids 30; Ata & Soulaimani (2005) Int. J. Numer.
Meth. Fluids 47; Vacondio, Rogers & Stansby (2012) Int. J. Numer. Meth. Fluids
69; Wendland (1995) Adv. Comput. Math. 4.

Known limitations, stated rather than hidden
--------------------------------------------
* Not exactly well-balanced: the SPH depth gradient and the DEM bed gradient
  are discretised differently, so a lake at rest develops small spurious
  velocities. The verification suite measures them and reports the number.
* Kernel truncation at a free surface under-estimates depth within about one
  smoothing length of the wet/dry edge, so the SPH extent is slightly
  smaller at the same wet threshold.
* The depth field is resolved at the particle spacing, not the grid spacing;
  the result is rasterised onto the solver grid for the comparison.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from floodguard.engines import _sph_kernels as k
from floodguard.engines.base import (
    Engine,
    EngineInput,
    ProgressCallback,
    ResultBundle,
    null_progress,
)

log = logging.getLogger(__name__)

G = 9.81


@dataclass
class SPHSettings:
    """Numerical parameters, recorded in provenance on every run."""

    #: Target particle count over the released volume. Sets the particle volume.
    target_particles: int = 120_000
    #: hs = eta * spacing. 1.6 gives ~30 neighbours in 2D with Wendland C2;
    #: chosen on the Ritter verification case (see docs/validation), where 1.3
    #: under-resolved the rarefaction and 2.0 cost 1.6x more for no gain in L2.
    eta: float = 1.6
    #: Smoothing-length clamp, as multiples of the grid cell size.
    #:
    #: The upper clamp is a cost control as much as an accuracy one. On real
    #: terrain a thin spray of particles runs out over the hillslopes; each has
    #: almost no neighbours, so its kernel grows to the clamp, and a particle
    #: with hs = 3 cells searches 13 x 13 = 169 buckets. Near a deep, dense pool
    #: that search visits thousands of candidates per particle and the step
    #: cost explodes (observed on Tehri: milliseconds -> ~11 s per step at 46k
    #: particles). 1.5 cells caps the search at 7 x 7 = 49 buckets. The spray
    #: it affects is below the wet threshold anyway.
    h_min_cells: float = 0.25
    h_max_cells: float = 1.5
    cfl: float = 0.3
    #: Artificial viscosity coefficients (Monaghan 1992).
    alpha: float = 0.5
    beta: float = 0.5
    #: Numerical backstop, matching FloodGuard-SWE.
    max_speed_ms: float = 120.0
    #: Depth floor used in the friction term only.
    friction_depth_floor_m: float = 0.01
    #: How often the particle field is rasterised for maxima/arrival, seconds.
    sample_interval_s: float = 20.0
    #: Hard cap on the particle arrays (memory safety).
    max_particles: int = 2_000_000
    #: Wall-clock budget. When exceeded the run stops, keeps what it computed
    #: and says loudly that it is truncated. None = no budget.
    max_runtime_s: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)

    @classmethod
    def from_scenario(cls, spec: Any | None) -> SPHSettings:
        """Build from a scenario's `solver.sph` block (floodguard.scenario.SPHSpec)."""
        if spec is None:
            return cls()
        values = {k: v for k, v in spec.model_dump().items() if v is not None}
        if "max_runtime_minutes" in values:
            values["max_runtime_s"] = 60.0 * values.pop("max_runtime_minutes")
        return cls(**values)


@dataclass
class ParticleState:
    """Dense particle arrays with spare capacity for injected particles."""

    px: np.ndarray
    py: np.ndarray
    vx: np.ndarray
    vy: np.ndarray
    vol: np.ndarray
    hs: np.ndarray
    depth: np.ndarray
    manning: np.ndarray
    ax: np.ndarray
    ay: np.ndarray
    capped: np.ndarray
    n: int = 0
    lost_volume: np.ndarray = field(default_factory=lambda: np.zeros(1))

    @classmethod
    def allocate(cls, capacity: int) -> ParticleState:
        f = lambda: np.zeros(capacity, dtype=np.float64)  # noqa: E731
        return cls(
            px=f(), py=f(), vx=f(), vy=f(), vol=f(), hs=f(), depth=f(),
            manning=f(), ax=f(), ay=f(),
            capped=np.zeros(capacity, dtype=np.int8),
        )

    @property
    def capacity(self) -> int:
        return self.px.shape[0]


class SPHDomain:
    """The grid a particle set lives on: bed, mask, roughness and search buckets."""

    def __init__(
        self,
        bed: np.ndarray,
        active: np.ndarray,
        manning: np.ndarray,
        dx: float,
        period_y: float = 0.0,
    ):
        self.dx = float(dx)
        #: > 0 only in verification: a laterally periodic strip.
        self.period_y = float(period_y)
        self.rows, self.cols = bed.shape
        self.active = np.ascontiguousarray(active & np.isfinite(bed), dtype=np.bool_)
        z = np.where(self.active, bed, 0.0).astype(np.float64)
        self.z = np.ascontiguousarray(z)
        self.manning = np.ascontiguousarray(manning, dtype=np.float64)
        self.gzx = np.zeros_like(self.z)
        self.gzy = np.zeros_like(self.z)
        k.bed_gradient(self.z, self.active, self.dx, self.gzx, self.gzy)
        self.cell_start = np.zeros(self.rows * self.cols + 1, dtype=np.int64)

    def manning_at(self, px: np.ndarray, py: np.ndarray) -> np.ndarray:
        c = np.clip((px / self.dx).astype(np.int64), 0, self.cols - 1)
        r = np.clip((py / self.dx).astype(np.int64), 0, self.rows - 1)
        return self.manning[r, c]


def _thread_count() -> int:
    try:
        from numba import get_num_threads

        return int(get_num_threads())
    except ImportError:  # pragma: no cover
        return 1


class SPHSolver:
    """One particle system advancing in time. Used by the engine and by verification."""

    def __init__(self, domain: SPHDomain, state: ParticleState, settings: SPHSettings):
        self.domain = domain
        self.s = state
        self.cfg = settings
        cap = state.capacity
        self.order = np.zeros(cap, dtype=np.int64)
        self.cell_of = np.zeros(cap, dtype=np.int64)
        # Per-thread force accumulators; see _sph_kernels.compute_forces.
        threads = _thread_count()
        self.buf_x = np.zeros((threads, cap))
        self.buf_y = np.zeros((threads, cap))
        self.h_min = settings.h_min_cells * domain.dx
        self.h_max = settings.h_max_cells * domain.dx
        self.steps = 0

    def _neighbours(self) -> None:
        d, s = self.domain, self.s
        k.build_cell_list(
            s.px, s.py, s.n, d.dx, d.rows, d.cols, d.cell_start, self.order, self.cell_of
        )

    def _depth(self, iterations: int = 1) -> None:
        """Smoothing length from the latest depth, then depth by summation.

        `iterations` extra (depth -> hs) passes converge a fresh particle set;
        during time stepping one pass suffices, because hs lags the depth by a
        single step and the particles move less than a kernel width per step.
        """
        d, s = self.domain, self.s
        k.update_smoothing_length(
            s.vol, s.depth, s.hs, s.n, self.cfg.eta, self.h_min, self.h_max
        )
        for _ in range(iterations):
            k.compute_depth(
                s.px, s.py, s.vol, s.hs, s.n, d.dx, d.rows, d.cols,
                d.cell_start, self.order, s.depth, d.period_y,
            )
            k.update_smoothing_length(
                s.vol, s.depth, s.hs, s.n, self.cfg.eta, self.h_min, self.h_max
            )
        # Final depth consistent with the smoothing length just chosen.
        k.compute_depth(
            s.px, s.py, s.vol, s.hs, s.n, d.dx, d.rows, d.cols,
            d.cell_start, self.order, s.depth, d.period_y,
        )

    def initialise(self) -> None:
        """Converge hs and depth for a freshly seeded particle set."""
        s = self.s
        if s.n == 0:
            return
        s.hs[: s.n] = np.where(s.hs[: s.n] > 0, s.hs[: s.n], self.h_max)
        self._neighbours()
        self._depth(iterations=4)

    def accelerations(self) -> None:
        d, s, cfg = self.domain, self.s, self.cfg
        self._neighbours()
        self._depth(iterations=0)
        k.compute_forces(
            s.px, s.py, s.vx, s.vy, s.vol, s.hs, s.depth, s.n, d.dx, d.rows, d.cols,
            d.cell_start, self.order, cfg.alpha, cfg.beta, s.ax, s.ay,
            self.buf_x, self.buf_y, d.period_y,
        )
        k.add_bed_slope(
            s.px, s.py, s.vx, s.vy, s.depth, s.n, d.dx, d.rows, d.cols,
            d.gzx, d.gzy, s.ax, s.ay,
        )

    def stable_dt(self) -> float:
        s = self.s
        if s.n == 0:
            return math.inf
        return float(k.timestep(s.hs, s.vx, s.vy, s.depth, s.ax, s.ay, s.n, self.cfg.cfl))

    def advance(self, dt: float) -> None:
        """Kick then drift, with forces already evaluated for the current state."""
        d, s, cfg = self.domain, self.s, self.cfg
        if s.n == 0:
            return
        k.kick(
            s.vx, s.vy, s.ax, s.ay, s.depth, s.manning, s.n, dt, cfg.max_speed_ms,
            cfg.friction_depth_floor_m, s.capped,
        )
        s.n = int(
            k.drift(
                s.px, s.py, s.vx, s.vy, s.vol, s.hs, s.depth, s.manning, s.n, dt,
                d.dx, d.rows, d.cols, d.active, s.lost_volume, d.period_y,
            )
        )
        self.steps += 1

    def rasterise(self, grid_d: np.ndarray, grid_q: np.ndarray) -> None:
        d, s = self.domain, self.s
        k.rasterise(
            s.px, s.py, s.vx, s.vy, s.vol, s.hs, s.n, d.dx, d.rows, d.cols,
            d.active, grid_d, grid_q,
        )

    def depth_at(self, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
        """SPH-interpolated depth at arbitrary points (scatter form)."""
        s = self.s
        out = np.zeros(len(xs))
        px, py, vol, hs = s.px[: s.n], s.py[: s.n], s.vol[: s.n], s.hs[: s.n]
        for m, (x, y) in enumerate(zip(xs, ys)):
            r = np.hypot(px - x, py - y)
            near = r < 2.0 * hs
            if near.any():
                out[m] = float(
                    np.sum(vol[near] * np.array([k.kernel_w(ri, hi) for ri, hi in zip(r[near], hs[near])]))
                )
        return out


class Injector:
    """Turns the breach hydrograph into particles over the breach face."""

    def __init__(
        self,
        spec: EngineInput,
        particle_volume: float,
        breach_width_m: float,
        seed: int = 20260924,
    ):
        cells = spec.source_cells or [(*spec.source_rc, 1.0)]
        cells = [(r, c, w) for r, c, w in cells if spec.active[r, c]] or [
            (*spec.source_rc, 1.0)
        ]
        w = np.array([c[2] for c in cells], dtype=np.float64)
        self.rows = np.array([c[0] for c in cells])
        self.cols = np.array([c[1] for c in cells])
        self.cum = np.cumsum(w / w.sum())
        self.v0 = particle_volume
        self.width = max(breach_width_m, spec.cell_size_m)
        self.dx = spec.cell_size_m
        dr, dc = spec.source_direction
        norm = math.hypot(dr, dc) or 1.0
        # Particle frame: x along columns, y along rows.
        self.dir_x, self.dir_y = dc / norm, dr / norm
        self.rng = np.random.default_rng(seed)
        self.buffer = 0.0
        self.injected_volume = 0.0
        self.count = 0

    def inject(self, state: ParticleState, q: float, dt: float, manning_lookup) -> int:
        """Add particles for q*dt of released water. Returns how many were added."""
        if q <= 0.0:
            return 0
        self.buffer += q * dt
        n_new = int(self.buffer // self.v0)
        if n_new <= 0:
            return 0
        room = state.capacity - state.n
        if n_new > room:
            n_new = room
        if n_new <= 0:
            return 0
        self.buffer -= n_new * self.v0

        # Critical flow through the opening: unit discharge q_w, critical
        # depth d_c = (q_w^2 / g)^(1/3), velocity sqrt(g d_c).
        q_w = q / self.width
        d_c = (q_w * q_w / G) ** (1.0 / 3.0)
        speed = math.sqrt(G * d_c)

        pick = np.searchsorted(self.cum, self.rng.random(n_new), side="right")
        pick = np.clip(pick, 0, len(self.rows) - 1)
        jitter = self.rng.random((n_new, 2))
        a, b = state.n, state.n + n_new
        state.px[a:b] = (self.cols[pick] + jitter[:, 0]) * self.dx
        state.py[a:b] = (self.rows[pick] + jitter[:, 1]) * self.dx
        state.vx[a:b] = speed * self.dir_x
        state.vy[a:b] = speed * self.dir_y
        state.vol[a:b] = self.v0
        state.hs[a:b] = 0.0  # set from the local depth on the next density pass
        state.depth[a:b] = 0.0
        state.manning[a:b] = manning_lookup(state.px[a:b], state.py[a:b])
        state.n = b
        self.injected_volume += n_new * self.v0
        self.count += n_new
        return n_new


def released_volume(spec: EngineInput, samples: int = 4000) -> float:
    """Volume the hydrograph releases within the simulated duration."""
    t = np.linspace(0.0, spec.duration_s, samples)
    q = np.array([spec.inflow_q(float(ti)) for ti in t])
    return float(np.trapezoid(q, t))


class SmoothedParticleSWE(Engine):
    """Depth-integrated SPH shallow-water engine."""

    id = "sph_swe"
    display_name = "FloodGuard-SPH (depth-integrated SWE-SPH)"
    is_real_solver = True
    version = "0.1.0"

    def __init__(self, settings: SPHSettings | None = None) -> None:
        self.settings = settings or SPHSettings()

    def run(
        self, spec: EngineInput, progress: ProgressCallback = null_progress
    ) -> ResultBundle:
        started = time.perf_counter()
        cfg = self.settings
        rows, cols = spec.shape
        dx = float(spec.cell_size_m)

        domain = SPHDomain(spec.bed_elevation, spec.active, spec.manning_n, dx)
        src_r, src_c = spec.source_rc
        if not domain.active[src_r, src_c]:
            raise ValueError(
                f"the breach release cell ({src_r}, {src_c}) is outside the active domain."
            )

        volume = released_volume(spec)
        if volume <= 0.0:
            raise ValueError("the breach hydrograph releases no water within the duration")

        particle_volume = volume / cfg.target_particles
        capacity = min(int(cfg.target_particles * 1.05) + 1024, cfg.max_particles)
        state = ParticleState.allocate(capacity)
        solver = SPHSolver(domain, state, cfg)

        n_face = len(spec.source_cells or [(src_r, src_c, 1.0)])
        breach_width = 2.0 * math.sqrt(n_face / math.pi) * dx
        injector = Injector(spec, particle_volume, breach_width)

        max_depth = np.zeros((rows, cols))
        max_speed = np.zeros((rows, cols))
        max_hazard = np.zeros((rows, cols))
        arrival = np.full((rows, cols), -1.0)
        grid_d = np.zeros((rows, cols))
        grid_q = np.zeros((rows, cols))

        frames: list[tuple[float, np.ndarray]] = []
        warnings: list[str] = []

        t = 0.0
        next_sample = 0.0
        next_output = 0.0
        peak_particles = 0
        progress(fraction=0.0, phase="solve", message="injecting particles")

        log.info(
            "SPH: %.3e m3 released over %.1f h -> particle volume %.1f m3, capacity %d",
            volume, spec.duration_s / 3600, particle_volume, capacity,
        )

        truncated_reason = ""
        window_start = time.perf_counter()
        window_steps = 0
        while t < spec.duration_s and solver.steps < spec.max_steps:
            if cfg.max_runtime_s is not None and time.perf_counter() - started > cfg.max_runtime_s:
                truncated_reason = (
                    f"the {cfg.max_runtime_s / 60:.0f}-minute wall-clock budget "
                    f"(solver.sph.max_runtime_minutes) ran out"
                )
                break
            if state.n > 0:
                solver.accelerations()
                dt = min(solver.stable_dt(), spec.duration_s - t)
            else:
                dt = min(10.0, spec.duration_s - t)
            # Never let one step span more than one sample interval, or the
            # arrival-time resolution silently degrades.
            dt = min(dt, cfg.sample_interval_s)
            if dt <= 0:
                break

            added = injector.inject(state, spec.inflow_q(t + 0.5 * dt), dt, domain.manning_at)
            if added and state.n == added:
                # First particles: nothing to take forces from yet.
                solver.initialise()
                continue
            if added:
                # New particles need a smoothing length before they can move;
                # they sit still for this step and join the next force pass.
                solver._neighbours()
                solver._depth(iterations=2)

            solver.advance(dt)
            t += dt
            window_steps += 1
            peak_particles = max(peak_particles, state.n)

            if t >= next_sample or t >= spec.duration_s:
                solver.rasterise(grid_d, grid_q)
                k.update_maxima(
                    grid_d, grid_q, max_depth, max_speed, max_hazard, arrival,
                    domain.active, t, spec.wet_threshold_m,
                )
                next_sample = t + cfg.sample_interval_s

                if t >= next_output:
                    frames.append((t, grid_d.copy()))
                    next_output += spec.output_interval_s
                    wet = int((grid_d >= spec.wet_threshold_m).sum())
                    # Cost per step since the last report: the number to watch
                    # when diagnosing a slow run (see scripts/profile_sph.py).
                    now = time.perf_counter()
                    ms_per_step = 1000.0 * (now - window_start) / max(window_steps, 1)
                    window_start, window_steps = now, 0
                    n_live = state.n
                    at_clamp = (
                        float(np.mean(state.hs[:n_live] >= solver.h_max * 0.999))
                        if n_live else 0.0
                    )
                    progress(
                        fraction=min(t / spec.duration_s, 1.0),
                        phase="solve",
                        message=(
                            f"t={t / 3600:.2f} h  step={solver.steps}  dt={dt:.3f} s  "
                            f"particles={n_live:,}  wet={wet:,} cells  "
                            f"{ms_per_step:.0f} ms/step  hs@max={at_clamp:.0%}"
                        ),
                        ms_per_step=ms_per_step,
                        t_seconds=t,
                        step=solver.steps,
                        dt=dt,
                        wet_cells=wet,
                    )

        runtime = time.perf_counter() - started

        in_domain = k.total_volume(state.vol, state.n)
        lost = float(state.lost_volume[0])
        pending = injector.buffer
        # Particles carry fixed volumes, so mass is conserved by construction;
        # the only discrepancy is the sub-particle remainder still in the
        # injection buffer. Reported rather than assumed.
        introduced = injector.injected_volume + pending
        mass_error = abs(in_domain + lost + pending - introduced) / max(introduced, 1.0)

        capped = int(state.capped[: max(state.n, 1)].sum())
        if truncated_reason:
            warnings.insert(
                0,
                f"SPH RUN TRUNCATED at t={t / 60:.1f} min of the requested "
                f"{spec.duration_s / 60:.0f} min because {truncated_reason}. Maxima and "
                f"arrival times cover only the simulated window; do not compare them with "
                f"a complete run as if they were like for like.",
            )
        if solver.steps >= spec.max_steps:
            warnings.append(
                f"The SPH solver hit its {spec.max_steps:,} step cap at t={t / 3600:.2f} h."
            )
        if injector.count >= capacity - 1:
            warnings.append(
                "The particle arrays filled before the hydrograph finished; later "
                "outflow was not injected, so the SPH result under-represents volume."
            )
        if lost > 0:
            warnings.append(
                f"{lost / 1e6:,.1f} million m3 left the SPH domain through the raster "
                f"edge, so the SPH flooded area is a lower bound there."
            )
        if capped:
            warnings.append(
                f"The SPH speed cap engaged on {capped:,} particles; treat velocities "
                f"at the wet/dry front with caution."
            )
        if not (max_depth >= spec.wet_threshold_m).any():
            warnings.append(
                f"No cell ever exceeded the {spec.wet_threshold_m} m wet threshold in SPH."
            )

        progress(fraction=1.0, phase="solve", message=f"done in {runtime:.1f}s")

        spacing_typical = math.sqrt(particle_volume / 5.0)
        return ResultBundle(
            engine_id=self.id,
            display_name=self.display_name,
            is_real_solver=True,
            max_depth=max_depth,
            max_velocity=max_speed,
            max_hazard=max_hazard,
            arrival_time_s=arrival,
            transform=spec.transform,
            crs=spec.crs,
            cell_size_m=spec.cell_size_m,
            frames=frames,
            runtime_s=runtime,
            steps=solver.steps,
            mass_error=float(mass_error),
            clipped_fraction=capped / max(peak_particles, 1),
            provenance={
                "engine": self.display_name,
                "engine_id": self.id,
                "engine_version": self.version,
                "is_real_solver": True,
                "scheme": (
                    "Depth-integrated SPH (gas-dynamics analogy), Wendland C2 kernel, "
                    "variable smoothing length, symmetric pressure gradient, Monaghan "
                    "artificial viscosity, semi-implicit Manning, symplectic Euler"
                ),
                "references": [
                    "Monaghan (1992), Annu. Rev. Astron. Astrophys. 30, 543-574",
                    "Wang & Shen (1999), Int. J. Numer. Meth. Fluids 30, 1051-1076",
                    "Ata & Soulaimani (2005), Int. J. Numer. Meth. Fluids 47, 139-159",
                    "Vacondio, Rogers & Stansby (2012), Int. J. Numer. Meth. Fluids 69, 1377-1410",
                    "Wendland (1995), Adv. Comput. Math. 4, 389-396",
                ],
                "not_3d_sph": (
                    "Depth-averaged. This is not a 3D WCSPH solve of the breach near field; "
                    "that is PySPH/DualSPHysics, whose case decks are generated separately."
                ),
                "settings": cfg.to_dict(),
                "jit": k.HAVE_NUMBA,
                "grid": {"rows": rows, "cols": cols, "cell_size_m": dx},
                "crs": spec.crs,
                "particle_volume_m3": particle_volume,
                "particles_injected": injector.count,
                "peak_particles": peak_particles,
                "typical_spacing_at_5m_depth_m": spacing_typical,
                "breach_face_width_m": breach_width,
                "volume_released_in_window_m3": volume,
                "volume_in_domain_m3": in_domain,
                "volume_left_domain_m3": lost,
                "volume_pending_in_injector_m3": pending,
                "mass_error": float(mass_error),
                "duration_s": spec.duration_s,
                "simulated_to_s": t,
                "truncated": bool(truncated_reason),
                "truncated_reason": truncated_reason or None,
                "steps": solver.steps,
                "runtime_s": runtime,
                "wet_threshold_m": spec.wet_threshold_m,
                **spec.scenario_provenance,
            },
            warnings=warnings,
        )


# --- verification harness -------------------------------------------------------


def solve_1d_dambreak_sph(
    length_m: float = 2000.0,
    h_left: float = 10.0,
    duration_s: float = 20.0,
    h_right: float = 0.0,
    spacing_m: float = 5.0,
    strip_particles: int = 16,
    settings: SPHSettings | None = None,
) -> dict[str, Any]:
    """Ritter dry-bed dam break on a strip, with the production kernels.

    The strip is `strip_particles` wide and periodic in y, so it is the 1-D
    problem without wall truncation. The upstream end is a closed wall (an
    inactive column), exercising the same wall code the real valley uses.
    """
    cfg = settings or SPHSettings(sample_interval_s=1e9)
    dx = spacing_m
    cols = int(length_m / dx)
    rows = strip_particles
    bed = np.zeros((rows, cols))
    active = np.ones((rows, cols), dtype=bool)
    active[:, 0] = False  # closed upstream end of the reservoir
    manning = np.zeros((rows, cols))

    # Periodic in y: a laterally infinite strip, so the centreline sees no
    # wall truncation and the problem is genuinely the 1-D Ritter problem.
    domain = SPHDomain(bed, active, manning, dx, period_y=rows * dx)
    xs = np.arange(dx + 0.5 * spacing_m, length_m / 2.0, spacing_m)
    ys = np.arange(0.5 * spacing_m, strip_particles * dx, spacing_m)
    gx, gy = np.meshgrid(xs, ys)
    px, py = gx.ravel(), gy.ravel()
    vol = np.full(px.size, h_left * spacing_m * spacing_m)
    if h_right > 0.0:
        # Wet bed downstream (Stoker): same lattice, shallower water, so each
        # particle carries proportionally less volume.
        xr = np.arange(length_m / 2.0 + 0.5 * spacing_m, length_m, spacing_m)
        rx, ry = np.meshgrid(xr, ys)
        px = np.concatenate([px, rx.ravel()])
        py = np.concatenate([py, ry.ravel()])
        vol = np.concatenate([vol, np.full(rx.size, h_right * spacing_m * spacing_m)])
    n = px.size
    state = ParticleState.allocate(n)
    state.px[:n] = px
    state.py[:n] = py
    state.vol[:n] = vol
    state.n = n

    solver = SPHSolver(domain, state, cfg)
    solver.initialise()

    t = 0.0
    while t < duration_s:
        solver.accelerations()
        dt = min(solver.stable_dt(), duration_s - t)
        if dt <= 0:
            break
        solver.advance(dt)
        t += dt

    solver._neighbours()
    solver._depth(iterations=1)
    x_line = np.arange(0.5 * spacing_m, length_m, spacing_m)
    y_mid = (rows * dx) / 2.0
    depth = solver.depth_at(x_line, np.full_like(x_line, y_mid))
    return {
        "x": x_line,
        "h": depth,
        "t": t,
        "steps": solver.steps,
        "dx": spacing_m,
        "particles": n,
    }
