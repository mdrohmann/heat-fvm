"""Reduced-basis machinery: affine operator decomposition and greedy basis training.

The buoyancy circulation always has the same spatial shape and differs only by a
scalar strength `s` (see `fvm.buoyancy_speed_scale`). Because the upwind advection
term scales linearly with a *non-negative* scalar, the discretised operator is
exactly affine in it:

    A(s) = A0 + s * A1

verified to machine precision by `test_rb.py`. That is the classical affine
parameter dependence reduced-basis methods are built around, and it buys two things:

1. A basis can be trained by sampling `s` directly instead of running the full solver
   on many days. The operator depends on the calendar *only* through `s` -- outdoor
   temperature enters the forcing, which is handled exactly -- so two days with equal
   `s` give an identical operator. Sampling `s` costs a few small dense solves;
   sampling days would cost a full nonlinear solve each.
2. Online, the reduced operator for any `s` is `A_r0 + s * A_r1`: a scalar combination
   of two small precomputed matrices. That is cheap enough to re-evaluate every
   timestep, which is what lets the reduced model recover the buoyancy nonlinearity
   instead of freezing it (see `solver/mor.py`).

Measured motivation for (2): `s` varies ~7x across the year *and* ~7x within a single
day, so freezing it is the dominant error source even on the day it was fitted to.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import scipy.sparse as sp

from solver.fvm import (
    AIR_RHO_C_J_PER_M3K,
    BuoyancyParams,
    assemble_operator,
    buoyancy_speed_scale,
    unit_buoyancy_velocity,
)
from solver.geometry import Room, RoomMesh

# The forcing is dominated by a constant (seasonal mean) plus the daily cycle, so
# snapshots at these two frequencies span the periodic response directly rather than
# hoping a time-marched trajectory happens to cover it.
DIURNAL_ANGULAR_FREQUENCY_RAD_PER_S = 2 * math.pi / (24 * 3600.0)
SNAPSHOT_FREQUENCIES_RAD_PER_S = (0.0, DIURNAL_ANGULAR_FREQUENCY_RAD_PER_S)


@dataclass
class AffineOperator:
    """`A(s) = a0 + s * a1`, already divided by cell thermal mass so it acts directly
    on dT/dt. `boundary_conductance_w_per_k` is the per-cell coupling to outdoor
    temperature, and `heat_source_cell` marks where heater power is injected."""

    a0: np.ndarray
    a1: np.ndarray
    boundary_conductance_w_per_k: np.ndarray
    cell_mass_j_per_k: float
    heat_source_cell: int
    room_mesh: RoomMesh = field(repr=False)

    @property
    def n_cells(self) -> int:
        return self.a0.shape[0]

    def at(self, s: float) -> np.ndarray:
        return self.a0 + s * self.a1

    def forcing_directions(self) -> np.ndarray:
        """The two spatial directions the system can be driven through, as columns:
        outdoor coupling and heater injection. Any forcing is a combination of these,
        so a basis that represents their responses represents every reachable state."""
        heater = np.zeros(self.n_cells)
        heater[self.heat_source_cell] = 1.0
        return np.column_stack([self.boundary_conductance_w_per_k, heater]) / self.cell_mass_j_per_k


def build_affine_operator(room_mesh: RoomMesh, room: Room) -> AffineOperator:
    """Assemble the affine decomposition by evaluating the existing FVM assembly at
    zero and unit circulation strength and differencing."""
    u_unit, v_unit = unit_buoyancy_velocity(room_mesh, room.width_m, room.height_m)
    zero = np.zeros_like(u_unit)

    cell_volume_m3 = room_mesh.mesh.cell_measure_m2 * room_mesh.depth_m
    cell_mass_j_per_k = AIR_RHO_C_J_PER_M3K * cell_volume_m3

    # outdoor_temp_c=1.0 makes `b` exactly the per-cell boundary conductance vector.
    k_at_zero, boundary_conductance = assemble_operator(room_mesh, zero, zero, outdoor_temp_c=1.0)
    k_at_one, _ = assemble_operator(room_mesh, u_unit, v_unit, outdoor_temp_c=1.0)

    a0 = _to_dense(k_at_zero) / cell_mass_j_per_k
    a1 = (_to_dense(k_at_one) - _to_dense(k_at_zero)) / cell_mass_j_per_k

    return AffineOperator(
        a0=a0,
        a1=a1,
        boundary_conductance_w_per_k=boundary_conductance,
        cell_mass_j_per_k=cell_mass_j_per_k,
        heat_source_cell=room_mesh.heat_source_cell,
        room_mesh=room_mesh,
    )


def _to_dense(matrix: sp.spmatrix | np.ndarray) -> np.ndarray:
    return matrix.toarray() if sp.issparse(matrix) else np.asarray(matrix)


def snapshots_at(operator: AffineOperator, s: float) -> np.ndarray:
    """Frequency-domain responses `(i*omega*I + A(s))^-1 b` for each forcing direction
    and each retained frequency, returned as real columns (real and imaginary parts
    split, since a real basis must span both).

    These are the states the system can actually be driven into by a DC-plus-diurnal
    forcing, which is exactly the forcing this problem has.
    """
    a_s = operator.at(s)
    identity = np.eye(operator.n_cells)
    directions = operator.forcing_directions()

    columns: list[np.ndarray] = []
    for omega in SNAPSHOT_FREQUENCIES_RAD_PER_S:
        system = (1j * omega) * identity + a_s
        response = np.linalg.solve(system, directions)
        if omega == 0.0:
            columns.append(response.real)
        else:
            columns.append(response.real)
            columns.append(response.imag)

    snapshots = np.column_stack(columns)
    return _drop_negligible_columns(snapshots)


def _drop_negligible_columns(matrix: np.ndarray, rtol: float = 1e-12) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=0)
    if norms.max() <= 0.0:
        return matrix[:, :0]
    return matrix[:, norms > rtol * norms.max()]


def _normalized_columns(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=0)
    norms[norms == 0.0] = 1.0
    return matrix / norms


def projection_error(basis: np.ndarray, snapshots: np.ndarray) -> float:
    """Worst relative error with which `basis` represents any snapshot column.

    This is the *true* projection error, not an a-posteriori residual bound. That is
    affordable here only because the full model is ~100-300 cells, so evaluating truth
    at every candidate parameter is cheaper than building a certified estimator; on a
    large model this is exactly the step you would replace with a residual-based error
    bound to keep the greedy loop offline-cheap.
    """
    if basis.size == 0:
        return 1.0
    unit_snapshots = _normalized_columns(snapshots)
    residual = unit_snapshots - basis @ (basis.T @ unit_snapshots)
    return float(np.linalg.norm(residual, axis=0).max())


@dataclass
class GreedyBasis:
    basis: np.ndarray  # (n_cells, n_basis), orthonormal columns
    selected_s: list[float]
    error_history: list[float]  # max projection error before each selection
    training_s: list[float]

    @property
    def size(self) -> int:
        return self.basis.shape[1]


def greedy_basis(
    operator: AffineOperator,
    s_max: float,
    n_training: int = 40,
    tol: float = 1e-6,
    max_basis_size: int = 30,
) -> GreedyBasis:
    """Train a reduced basis by strong greedy search over the circulation strength `s`.

    At each iteration, find the training parameter whose snapshots the current basis
    represents worst, add them, and re-orthonormalise. The error history it returns is
    the interesting artifact: it shows the basis actually converging, rather than
    asserting that some fixed mode count is enough.

    `s_max` should be the model's own speed cap (`BuoyancyParams.max_speed_m_s`) rather
    than an estimate of the strengths a particular run will visit. Covering the whole
    reachable range costs only a few extra basis vectors -- it converges to ~1e-5 in
    ~30 -- and removes any possibility of the online model wandering outside the range
    it was trained on.
    """
    if s_max <= 0.0:
        raise ValueError(f"s_max must be positive, got {s_max}")

    # Denser sampling at low `s`: the operator changes proportionally fastest there,
    # and mild days -- the ones the single-point model handled worst -- live there.
    unit_positions = np.linspace(0.0, 1.0, n_training)
    training_s = sorted({round(float(s_max * u**1.5), 12) for u in unit_positions})

    snapshot_cache = {s: snapshots_at(operator, s) for s in training_s}

    basis = np.zeros((operator.n_cells, 0))
    selected_s: list[float] = []
    error_history: list[float] = []

    while True:
        errors = {s: projection_error(basis, snapshot_cache[s]) for s in training_s}
        worst_s = max(errors, key=lambda s: errors[s])
        # Recorded before the stopping check, so the last entry is the error the
        # returned basis actually achieves rather than the one before the last add.
        error_history.append(errors[worst_s])

        if errors[worst_s] <= tol or basis.shape[1] >= max_basis_size:
            break

        basis = _orthonormalize(np.column_stack([basis, snapshot_cache[worst_s]]))
        selected_s.append(worst_s)

    return GreedyBasis(
        basis=basis,
        selected_s=selected_s,
        error_history=error_history,
        training_s=training_s,
    )


def _orthonormalize(matrix: np.ndarray, rcond: float = 1e-11) -> np.ndarray:
    """SVD-based orthonormalisation, dropping directions that are numerically already
    represented -- snapshots from nearby `s` values are strongly correlated, so this
    keeps the basis from becoming rank-deficient."""
    u, singular_values, _ = np.linalg.svd(matrix, full_matrices=False)
    if singular_values.size == 0:
        return matrix[:, :0]
    keep = singular_values > rcond * singular_values[0]
    return u[:, keep]
