"""Numba-jitted kernels for the depth-integrated SPH shallow-water solver.

The method is the "gas-dynamics analogy" of SPH for the shallow-water
equations (Wang & Shen 1999; Ata & Soulaimani 2005; Vacondio et al. 2012).
Each particle carries a fixed volume of water V, a position and a velocity.
Depth is not a state variable: it is recovered by kernel summation,

    d_i = sum_j V_j W(|x_i - x_j|, hs_i)

which plays the role that density summation plays in gas SPH. With areal
density rho = rho_w * d and pressure P = g rho^2 / (2 rho_w), the pressure
term P/rho^2 is the constant g/2, and the momentum equation collapses to

    dv_i/dt = - sum_j V_j (g + Pi_ij) grad_i W_ij  -  g grad(z)  -  friction

Every piece of that is used below. The audit in docs/AUDIT.md found a
reference repository whose "SPH" defined a kernel that was never called; the
test suite asserts that this solver's depth really is the kernel sum.

Neighbour search
----------------
Buckets are the cells of the DEM grid itself, sorted by counting sort. A
particle with smoothing length hs searches ceil(2 hs / dx) buckets in each
direction. Pairs are evaluated once, from the particle with the larger
smoothing length, using the averaged smoothing length for the symmetric
pressure gradient — so every interacting pair is found exactly once and
momentum is conserved to round-off.
"""

from __future__ import annotations

import math

import numpy as np

try:
    from numba import njit, prange

    HAVE_NUMBA = True
except ImportError:  # pragma: no cover
    HAVE_NUMBA = False
    prange = range

    def njit(*args, **kwargs):  # type: ignore[misc]
        def wrap(fn):
            return fn

        if args and callable(args[0]):
            return args[0]
        return wrap


G = 9.81
#: Wendland C2 normalisation in 2D, without the 1/h^2 factor.
WENDLAND_2D = 7.0 / (4.0 * math.pi)


@njit(cache=True, inline="always")
def kernel_w(r, h):
    """Wendland C2 kernel in 2D, support 2h.

    Chosen over the cubic spline because it does not suffer the pairing
    instability, which in a free-surface flow shows up as particles clumping
    at the front and the depth estimate there becoming noisy.
    """
    q = r / h
    if q >= 2.0:
        return 0.0
    a = 1.0 - 0.5 * q
    return WENDLAND_2D / (h * h) * a * a * a * a * (1.0 + 2.0 * q)


@njit(cache=True, inline="always")
def kernel_dwdr(r, h):
    """dW/dr for the Wendland C2 kernel: sigma/h^3 * (-5 q (1 - q/2)^3)."""
    q = r / h
    if q >= 2.0:
        return 0.0
    a = 1.0 - 0.5 * q
    return WENDLAND_2D / (h * h * h) * (-5.0 * q * a * a * a)


@njit(cache=True, inline="always")
def _row_range(ri, reach, rows, period_y):
    """Bucket rows to search; unclamped (wrapped by the caller) when periodic."""
    if period_y > 0.0:
        return ri - reach, ri + reach + 1
    return max(ri - reach, 0), min(ri + reach + 1, rows)


@njit(cache=True, inline="always")
def _wrap(dy, period_y):
    """Minimum-image separation in y for a periodic strip."""
    if period_y > 0.0:
        if dy > 0.5 * period_y:
            return dy - period_y
        if dy < -0.5 * period_y:
            return dy + period_y
    return dy


@njit(cache=True)
def build_cell_list(px, py, n, dx, rows, cols, cell_start, order, cell_of):
    """Counting sort of particles into DEM-grid buckets.

    `cell_start` has rows*cols + 1 entries; particles in bucket b are
    order[cell_start[b]:cell_start[b+1]].
    """
    ncell = rows * cols
    for b in range(ncell + 1):
        cell_start[b] = 0
    for i in range(n):
        c = int(px[i] / dx)
        r = int(py[i] / dx)
        if c < 0:
            c = 0
        elif c >= cols:
            c = cols - 1
        if r < 0:
            r = 0
        elif r >= rows:
            r = rows - 1
        b = r * cols + c
        cell_of[i] = b
        cell_start[b + 1] += 1
    for b in range(ncell):
        cell_start[b + 1] += cell_start[b]
    # Reuse cell_start as a running cursor via a copy of the offsets.
    cursor = cell_start[:ncell].copy()
    for i in range(n):
        b = cell_of[i]
        order[cursor[b]] = i
        cursor[b] += 1


@njit(cache=True, parallel=True)
def compute_depth(px, py, vol, hs, n, dx, rows, cols, cell_start, order, depth, period_y=0.0):
    """Depth by kernel summation (gather, each particle with its own hs).

    `period_y` > 0 wraps the domain in y. Only the verification harness uses
    it, to make a laterally infinite strip without wall truncation.
    """
    for i in prange(n):
        xi = px[i]
        yi = py[i]
        h = hs[i]
        support = 2.0 * h
        reach = int(math.ceil(support / dx))
        ci = int(xi / dx)
        ri = int(yi / dx)
        acc = 0.0
        r_lo, r_hi = _row_range(ri, reach, rows, period_y)
        for rr in range(r_lo, r_hi):
            r = rr % rows
            for c in range(max(ci - reach, 0), min(ci + reach + 1, cols)):
                b = r * cols + c
                for k in range(cell_start[b], cell_start[b + 1]):
                    j = order[k]
                    dxp = xi - px[j]
                    dyp = _wrap(yi - py[j], period_y)
                    rij = math.sqrt(dxp * dxp + dyp * dyp)
                    if rij < support:
                        acc += vol[j] * kernel_w(rij, h)
        depth[i] = acc


@njit(cache=True, parallel=True)
def update_smoothing_length(vol, depth, hs, n, eta, h_min, h_max):
    """hs = eta * sqrt(V / d): the kernel tracks the local particle spacing.

    In 2D the spacing of particles of volume V spread at depth d is
    sqrt(V/d). A fixed smoothing length would leave thin sheets of water
    with too few neighbours and deep pools with far too many; both bias
    the depth estimate. Clamped so a stray particle cannot grow a kernel
    wider than the valley.
    """
    for i in prange(n):
        d = depth[i]
        if d <= 1e-9:
            hs[i] = h_max
        else:
            h = eta * math.sqrt(vol[i] / d)
            if h < h_min:
                h = h_min
            elif h > h_max:
                h = h_max
            hs[i] = h


@njit(cache=True, parallel=True)
def compute_forces(
    px, py, vx, vy, vol, hs, depth, n, dx, rows, cols, cell_start, order,
    alpha, beta, ax, ay, buf_x, buf_y, period_y=0.0,
):
    """Pressure gradient and artificial viscosity, pairwise and symmetric.

    Each pair is evaluated ONCE, from the particle with the larger smoothing
    length (ties broken by index), whose search radius necessarily covers the
    averaged support, and the force is written to both particles equal and
    opposite. That is what makes momentum conservation exact.

    Writing to both particles from parallel threads would race, so each
    thread accumulates into its own row of `buf_x`/`buf_y` (shape
    threads x capacity) and the rows are summed afterwards. The pair logic is
    identical to a serial loop; only the order of floating-point additions
    changes, which the conservation test bounds at round-off.
    """
    threads = buf_x.shape[0]
    for t in prange(threads):
        for i in range(n):
            buf_x[t, i] = 0.0
            buf_y[t, i] = 0.0

    for t in prange(threads):
        for i in range(t, n, threads):
            xi = px[i]
            yi = py[i]
            hi = hs[i]
            reach = int(math.ceil(2.0 * hi / dx))
            ci = int(xi / dx)
            ri = int(yi / dx)
            ci_c = math.sqrt(G * max(depth[i], 0.0))
            r_lo, r_hi = _row_range(ri, reach, rows, period_y)
            for rr in range(r_lo, r_hi):
                r = rr % rows
                for c in range(max(ci - reach, 0), min(ci + reach + 1, cols)):
                    b = r * cols + c
                    for k in range(cell_start[b], cell_start[b + 1]):
                        j = order[k]
                        if j == i:
                            continue
                        hj = hs[j]
                        if hj > hi or (hj == hi and j <= i):
                            continue  # evaluated from j's side
                        rx = xi - px[j]
                        ry = _wrap(yi - py[j], period_y)
                        r2 = rx * rx + ry * ry
                        hbar = 0.5 * (hi + hj)
                        if r2 >= 4.0 * hbar * hbar or r2 < 1e-24:
                            continue
                        rij = math.sqrt(r2)
                        dw = kernel_dwdr(rij, hbar) / rij  # grad W = dw * (rx, ry)

                        # Monaghan (1992) artificial viscosity, only on approach.
                        wx = vx[i] - vx[j]
                        wy = vy[i] - vy[j]
                        vr = wx * rx + wy * ry
                        visc = 0.0
                        if vr < 0.0:
                            mu = hbar * vr / (r2 + 0.01 * hbar * hbar)
                            cbar = 0.5 * (ci_c + math.sqrt(G * max(depth[j], 0.0)))
                            dbar = 0.5 * (depth[i] + depth[j])
                            if dbar > 1e-6:
                                visc = (-alpha * cbar * mu + beta * mu * mu) / dbar

                        coef = (G + visc) * dw
                        buf_x[t, i] -= vol[j] * coef * rx
                        buf_y[t, i] -= vol[j] * coef * ry
                        buf_x[t, j] += vol[i] * coef * rx
                        buf_y[t, j] += vol[i] * coef * ry

    for i in prange(n):
        sx = 0.0
        sy = 0.0
        for t in range(threads):
            sx += buf_x[t, i]
            sy += buf_y[t, i]
        ax[i] = sx
        ay[i] = sy


@njit(cache=True, parallel=True)
def add_bed_slope(
    px, py, vx, vy, depth, n, dx, rows, cols, gzx, gzy, ax, ay,
):
    """Add the bed-slope acceleration -g grad(z), bilinear in the particle position.

    Bilinear rather than cell-constant: a particle crossing a cell boundary
    would otherwise feel a step change in forcing, which rings as noise in
    the depth field.
    """
    for i in prange(n):
        fx = px[i] / dx - 0.5
        fy = py[i] / dx - 0.5
        c0 = int(math.floor(fx))
        r0 = int(math.floor(fy))
        tx = fx - c0
        ty = fy - r0
        if c0 < 0:
            c0 = 0
            tx = 0.0
        if r0 < 0:
            r0 = 0
            ty = 0.0
        c1 = c0 + 1
        r1 = r0 + 1
        if c1 >= cols:
            c1 = cols - 1
            c0 = min(c0, cols - 1)
        if r1 >= rows:
            r1 = rows - 1
            r0 = min(r0, rows - 1)
        sx = (
            (1 - tx) * (1 - ty) * gzx[r0, c0] + tx * (1 - ty) * gzx[r0, c1]
            + (1 - tx) * ty * gzx[r1, c0] + tx * ty * gzx[r1, c1]
        )
        sy = (
            (1 - tx) * (1 - ty) * gzy[r0, c0] + tx * (1 - ty) * gzy[r0, c1]
            + (1 - tx) * ty * gzy[r1, c0] + tx * ty * gzy[r1, c1]
        )
        ax[i] -= G * sx
        ay[i] -= G * sy


@njit(cache=True, parallel=True)
def kick(vx, vy, ax, ay, depth, manning_p, n, dt, max_speed, dry_depth, capped):
    """Symplectic-Euler velocity update with semi-implicit Manning friction."""
    for i in prange(n):
        u = vx[i] + dt * ax[i]
        v = vy[i] + dt * ay[i]
        d = max(depth[i], dry_depth)
        speed = math.sqrt(u * u + v * v)
        nn = manning_p[i]
        if nn > 0.0 and speed > 0.0:
            denom = 1.0 + dt * G * nn * nn * speed / d ** (4.0 / 3.0)
            u /= denom
            v /= denom
            speed /= denom
        if speed > max_speed:
            s = max_speed / speed
            u *= s
            v *= s
            capped[i] = 1
        vx[i] = u
        vy[i] = v


@njit(cache=True)
def drift(
    px, py, vx, vy, vol, hs, depth, manning_p, n, dt, dx, rows, cols, active, lost,
    period_y=0.0,
):
    """Move particles; reflect off inactive cells; drop those leaving the raster.

    Returns the new particle count. Removed particles are swapped with the
    last live one so the arrays stay dense. `lost[0]` accumulates the volume
    that left through the open raster edge, which the mass budget reports.
    """
    i = 0
    width = cols * dx
    height = rows * dx
    while i < n:
        ox = px[i]
        oy = py[i]
        nx = ox + dt * vx[i]
        ny = oy + dt * vy[i]
        if period_y > 0.0:
            ny = ny % period_y
        if nx < 0.0 or ny < 0.0 or nx >= width or ny >= height:
            lost[0] += vol[i]
            last = n - 1
            px[i] = px[last]
            py[i] = py[last]
            vx[i] = vx[last]
            vy[i] = vy[last]
            vol[i] = vol[last]
            hs[i] = hs[last]
            depth[i] = depth[last]
            manning_p[i] = manning_p[last]
            n -= 1
            continue

        c_new = int(nx / dx)
        r_new = int(ny / dx)
        if not active[r_new, c_new]:
            c_old = int(ox / dx)
            r_old = int(oy / dx)
            # Slide along the wall: keep the motion along whichever axis is
            # still open and zero the component that carried the particle
            # into the inactive cell. Inelastic on purpose — a reflecting wall
            # would bounce water back up the valley with energy it never had.
            x_ok = active[r_old, c_new]
            y_ok = active[r_new, c_old]
            if x_ok and not y_ok:
                px[i] = nx
                vy[i] = 0.0
            elif y_ok and not x_ok:
                py[i] = ny
                vx[i] = 0.0
            else:
                # Blocked on both axes, or a diagonal corner. Stay put.
                vx[i] = 0.0
                vy[i] = 0.0
        else:
            px[i] = nx
            py[i] = ny
        i += 1
    return n


@njit(cache=True)
def rasterise(px, py, vx, vy, vol, hs, n, dx, rows, cols, active, grid_d, grid_q):
    """SPH interpolation of depth and discharge onto the cell centres.

    Scatter form, each particle with its own smoothing length: the depth at a
    point is sum_j V_j W(x - x_j, hs_j), the same summation the particles use,
    so the raster and the particles agree about how much water is where.
    """
    grid_d[:, :] = 0.0
    grid_q[:, :] = 0.0
    for j in range(n):
        h = hs[j]
        support = 2.0 * h
        reach = int(math.ceil(support / dx))
        cj = int(px[j] / dx)
        rj = int(py[j] / dx)
        sp = math.sqrt(vx[j] * vx[j] + vy[j] * vy[j])
        for r in range(max(rj - reach, 0), min(rj + reach + 1, rows)):
            yc = (r + 0.5) * dx
            for c in range(max(cj - reach, 0), min(cj + reach + 1, cols)):
                if not active[r, c]:
                    continue
                xc = (c + 0.5) * dx
                dxp = xc - px[j]
                dyp = yc - py[j]
                rr = math.sqrt(dxp * dxp + dyp * dyp)
                if rr < support:
                    w = vol[j] * kernel_w(rr, h)
                    grid_d[r, c] += w
                    grid_q[r, c] += w * sp


@njit(cache=True)
def update_maxima(grid_d, grid_q, max_depth, max_speed, max_hazard, arrival, active, t, wet):
    """Running maxima and first-arrival time, from the rasterised field."""
    rows, cols = grid_d.shape
    for r in range(rows):
        for c in range(cols):
            if not active[r, c]:
                continue
            d = grid_d[r, c]
            if d <= 0.0:
                continue
            speed = grid_q[r, c] / d if d > 1e-3 else 0.0
            if d > max_depth[r, c]:
                max_depth[r, c] = d
            if d >= wet:
                if speed > max_speed[r, c]:
                    max_speed[r, c] = speed
                hz = d * speed
                if hz > max_hazard[r, c]:
                    max_hazard[r, c] = hz
                if arrival[r, c] < 0.0:
                    arrival[r, c] = t


@njit(cache=True)
def bed_gradient(z, active, dx, gzx, gzy):
    """Bed slope at cell centres, one-sided where a neighbour is inactive.

    Central differences across a corridor edge would difference against a
    nodata bed, which is a fictional cliff.
    """
    rows, cols = z.shape
    for r in range(rows):
        for c in range(cols):
            gzx[r, c] = 0.0
            gzy[r, c] = 0.0
            if not active[r, c]:
                continue
            left = c > 0 and active[r, c - 1]
            right = c < cols - 1 and active[r, c + 1]
            if left and right:
                gzx[r, c] = (z[r, c + 1] - z[r, c - 1]) / (2.0 * dx)
            elif right:
                gzx[r, c] = (z[r, c + 1] - z[r, c]) / dx
            elif left:
                gzx[r, c] = (z[r, c] - z[r, c - 1]) / dx
            up = r > 0 and active[r - 1, c]
            down = r < rows - 1 and active[r + 1, c]
            if up and down:
                gzy[r, c] = (z[r + 1, c] - z[r - 1, c]) / (2.0 * dx)
            elif down:
                gzy[r, c] = (z[r + 1, c] - z[r, c]) / dx
            elif up:
                gzy[r, c] = (z[r, c] - z[r - 1, c]) / dx


@njit(cache=True)
def timestep(hs, vx, vy, depth, ax, ay, n, cfl):
    """CFL on the shallow-water celerity plus a force criterion.

    dt <= CFL * hs / (sqrt(g d) + |v|) is the SPH analogue of the Courant
    condition; dt <= 0.25 sqrt(hs / |a|) stops a strongly accelerated
    particle overshooting its own kernel in one step (Monaghan 1992).
    """
    dt = 1e30
    for i in range(n):
        c = math.sqrt(G * max(depth[i], 0.0))
        sp = math.sqrt(vx[i] * vx[i] + vy[i] * vy[i])
        denom = c + sp
        if denom > 1e-9:
            t1 = cfl * hs[i] / denom
            if t1 < dt:
                dt = t1
        acc = math.sqrt(ax[i] * ax[i] + ay[i] * ay[i])
        if acc > 1e-9:
            t2 = 0.25 * math.sqrt(hs[i] / acc)
            if t2 < dt:
                dt = t2
    return dt


def total_volume(vol: np.ndarray, n: int) -> float:
    return float(vol[:n].sum())
