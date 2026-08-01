"""Model-order reduction for the annual energy estimate.

The full solver in `fvm.py` is nonlinear -- the buoyancy circulation strength feeds
back from the temperature field -- which is right for the short, rich visualisation
window but far too expensive for 365 days. Two reductions live here:

**Adaptive (`build_adaptive_model`, current).** Uses the affine structure
`A(s) = A0 + s*A1` and a greedy reduced basis from `solver/rb.py`. The circulation
strength `s` is *recomputed every timestep* from the reduced state, so the buoyancy
nonlinearity is retained rather than frozen. This needs no full-solver trajectory at
all: the basis is trained by sampling `s` directly.

**Frozen single-point (`build_reduced_model`, baseline).** Freezes the velocity field
at the pattern implied by one representative day, then keeps the slowest-decaying
eigenmodes of that single operator. Kept because the app reports both side by side --
the measured gap between them is the argument for the extra machinery.

Why the adaptive version exists: `s` varies ~7x across the year *and* ~7x within a
single day, so freezing it is the dominant error source even on the day it was fitted
to. See `solver/validation.py` for the measured comparison.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import scipy.linalg

from solver.controller import ControllerState, PIControllerParams, pi_power_w
from solver.fvm import (
    AIR_RHO_C_J_PER_M3K,
    BuoyancyParams,
    DayResult,
    assemble_operator,
    buoyancy_speed_scale,
    buoyancy_velocity,
)
from solver.climate import DAYS_PER_YEAR, ClimateLocation, month_of_day
from solver.geometry import HeatSource, Room, RoomMesh, build_room_mesh
from solver.materials import ThermostatSettings
from solver.rb import GreedyBasis, build_affine_operator, greedy_basis

_CONJUGATE_PAIR_ATOL = 1e-6


def _select_mode_indices(eigenvalues: np.ndarray, n_modes: int) -> np.ndarray:
    """Pick the `n_modes` eigenvalues with the smallest real part (slowest decay,
    dominant for long-horizon dynamics). Extends the selection by one if the cut
    would split a complex-conjugate pair -- needed so the reduced model, projected
    back to physical space, stays real."""
    order = np.argsort(eigenvalues.real)
    count = min(n_modes, len(order))
    while count < len(order):
        last = eigenvalues[order[count - 1]]
        next_ = eigenvalues[order[count]]
        is_conjugate_pair = (
            abs(last.imag) > 1e-9
            and np.isclose(last.real, next_.real, atol=_CONJUGATE_PAIR_ATOL)
            and np.isclose(last.imag, -next_.imag, atol=_CONJUGATE_PAIR_ATOL)
        )
        if is_conjugate_pair:
            count += 1
        else:
            break
    return order[:count]


@dataclass
class ReducedModel:
    """Baseline: modal truncation about a single frozen operating point.

    Exposes the same `project` / `room_avg_temp_c` / `step` interface as
    `AdaptiveReducedModel` so both run through `simulate_reduced_days` unchanged --
    which is what makes the before/after comparison in `solver/validation.py` a fair
    one rather than two subtly different time loops.
    """

    lambdas: np.ndarray  # complex, shape (n_modes,)
    v_r: np.ndarray  # complex, shape (n_cells, n_modes) -- reconstructs the full field
    w_r: np.ndarray  # complex, shape (n_modes, n_cells) -- projects a field into modal coords
    avg_row: np.ndarray  # complex, shape (n_modes,) -- room-average reconstruction
    boundary_conductance_w_per_k: np.ndarray  # real, shape (n_cells,)
    cell_mass_j_per_k: float
    heat_source_cell: int
    room_mesh: RoomMesh

    @property
    def size(self) -> int:
        return self.v_r.shape[1]

    def project(self, temperature_c: np.ndarray) -> np.ndarray:
        return self.w_r @ temperature_c

    def room_avg_temp_c(self, z: np.ndarray) -> float:
        return float((self.avg_row @ z).real)

    def step(self, z: np.ndarray, outdoor_temp_c: float, heater_power_w: float, dt_s: float) -> np.ndarray:
        forcing = self.boundary_conductance_w_per_k * outdoor_temp_c
        forcing[self.heat_source_cell] += heater_power_w
        rhs = (self.w_r @ forcing) / self.cell_mass_j_per_k
        return _step_modal_state(z, self.lambdas, rhs, dt_s)


def build_reduced_model(
    room_mesh: RoomMesh,
    u_frozen: np.ndarray,
    v_frozen: np.ndarray,
    n_modes: int,
) -> ReducedModel:
    """Linearize about the frozen velocity field and reduce via modal truncation."""
    n = room_mesh.mesh.n_cells
    cell_volume_m3 = room_mesh.mesh.cell_measure_m2 * room_mesh.depth_m
    cell_mass_j_per_k = AIR_RHO_C_J_PER_M3K * cell_volume_m3

    # K doesn't depend on outdoor_temp_c; evaluating at 1.0 makes `b` exactly the
    # per-cell boundary conductance vector (0 for interior cells).
    K, boundary_conductance = assemble_operator(room_mesh, u_frozen, v_frozen, outdoor_temp_c=1.0)
    A_dense = K.toarray() / cell_mass_j_per_k

    eigenvalues, eigenvectors = scipy.linalg.eig(A_dense)
    eigenvectors_inv = np.linalg.inv(eigenvectors)

    selected = _select_mode_indices(eigenvalues, n_modes)
    lambdas = eigenvalues[selected]
    v_r = eigenvectors[:, selected]
    w_r = eigenvectors_inv[selected, :]
    avg_row = (np.ones(n) / n) @ v_r

    return ReducedModel(
        lambdas=lambdas,
        v_r=v_r,
        w_r=w_r,
        avg_row=avg_row,
        boundary_conductance_w_per_k=boundary_conductance,
        cell_mass_j_per_k=cell_mass_j_per_k,
        heat_source_cell=room_mesh.heat_source_cell,
        room_mesh=room_mesh,
    )


@dataclass
class AdaptiveReducedModel:
    """Galerkin reduction over a greedy basis, with the buoyancy strength recovered
    online instead of frozen.

    `A_r(s) = a_r0 + s * a_r1` is a scalar combination of two small precomputed
    matrices -- the affine offline/online split -- so re-evaluating the operator every
    timestep is essentially free. `s` itself comes from two linear functionals of the
    state (`heat_source_row`, `avg_row`), so it can be evaluated in reduced
    coordinates without ever rebuilding the full temperature field.
    """

    basis: np.ndarray  # (n_cells, n_basis), orthonormal
    a_r0: np.ndarray
    a_r1: np.ndarray
    forcing_boundary_r: np.ndarray  # reduced outdoor-coupling forcing direction
    forcing_heater_r: np.ndarray  # reduced heater-injection forcing direction
    avg_row: np.ndarray  # reduced functional giving room-average temperature
    heat_source_row: np.ndarray  # reduced functional giving heat-source-cell temperature
    buoyancy_params: BuoyancyParams
    s_max: float
    n_s_bins: int
    picard_iterations: int
    picard_relaxation: float
    room_mesh: RoomMesh = field(repr=False)
    _eigen_cache: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]] = field(
        default_factory=dict, repr=False
    )

    @property
    def size(self) -> int:
        return self.basis.shape[1]

    def project(self, temperature_c: np.ndarray) -> np.ndarray:
        return self.basis.T @ temperature_c

    def reconstruct(self, z: np.ndarray) -> np.ndarray:
        return self.basis @ z

    def room_avg_temp_c(self, z: np.ndarray) -> float:
        return float(self.avg_row @ z)

    def speed_scale(self, z: np.ndarray) -> float:
        return buoyancy_speed_scale(
            float(self.heat_source_row @ z), float(self.avg_row @ z), self.buoyancy_params
        )

    def _eigen_for_bin(self, bin_index: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Eigendecomposition of the reduced operator for a quantised `s`.

        Quantising lets the exact exponential integrator be reused -- it needs a fixed
        operator across the step -- while `s` still tracks the state. `s` varies
        smoothly, so binning it costs little; `n_s_bins` is a tunable and
        `test_rb.py` pins the resulting error rather than assuming it is negligible.
        """
        cached = self._eigen_cache.get(bin_index)
        if cached is not None:
            return cached

        s = bin_index * (self.s_max / self.n_s_bins)
        eigenvalues, eigenvectors = scipy.linalg.eig(self.a_r0 + s * self.a_r1)
        entry = (eigenvalues, eigenvectors, np.linalg.inv(eigenvectors))
        self._eigen_cache[bin_index] = entry
        return entry

    def _bin_index(self, s: float) -> int:
        bin_index = int(round(s / (self.s_max / self.n_s_bins)))
        return min(max(bin_index, 0), self.n_s_bins)

    def step(self, z: np.ndarray, outdoor_temp_c: float, heater_power_w: float, dt_s: float) -> np.ndarray:
        """One step, Picard-iterated on `s` exactly like `fvm.backward_euler_step`
        iterates its buoyancy velocity: each pass re-evaluates `s` from the latest
        end-of-step guess and re-solves, rather than freezing `s` at its start-of-step
        value. An explicit (start-of-step-only) `s` is a lower-order treatment of the
        same nonlinearity FOM solves implicitly.

        This iteration does **not** converge undamped. `s` closes a negative-feedback
        loop -- more circulation mixes the heater's local hot spot into the room
        faster, which *lowers* the delta-T driving that same circulation -- and the
        loop gain here is steep enough that plain fixed-point iteration (relaxation
        1.0) settles into an exact period-2 limit cycle rather than converging: traced
        directly, `s` alternates between ~0.048 and ~0.287 forever and never stops.
        Different fixed iteration counts then sample different phases of that cycle,
        which is what produced a confusing sign-alternating few-percent annual bias
        across every climate before this was diagnosed. Standard fixed-point
        under-relaxation (`picard_relaxation`, blending the new estimate with the old
        rather than replacing it) breaks the cycle and converges cleanly in ~4-5
        iterations at the default 0.5 -- measured by tracing the iterates directly,
        not assumed; see `test_rb.py`.

        `picard_iterations`/`picard_relaxation` are fields, not per-call arguments, so
        this keeps the exact same signature as `ReducedModel.step` and both run
        through `simulate_reduced_days` unchanged.
        """
        z_complex = z.astype(complex)
        rhs_complex = (self.forcing_boundary_r * outdoor_temp_c + self.forcing_heater_r * heater_power_w).astype(
            complex
        )

        s_guess = self.speed_scale(z)
        z_guess = z
        for _ in range(self.picard_iterations):
            eigenvalues, eigenvectors, eigenvectors_inv = self._eigen_for_bin(self._bin_index(s_guess))
            z_modal = _step_modal_state(eigenvectors_inv @ z_complex, eigenvalues, eigenvectors_inv @ rhs_complex, dt_s)
            z_guess = np.real(eigenvectors @ z_modal)

            s_computed = self.speed_scale(z_guess)
            s_guess = self.picard_relaxation * s_computed + (1 - self.picard_relaxation) * s_guess

        return z_guess


def build_adaptive_model(
    room: Room,
    heat_source: HeatSource,
    nx: int = 12,
    ny: int = 9,
    tol: float = 1e-4,
    max_basis_size: int = 42,
    n_s_bins: int = 64,
    picard_iterations: int = 6,
    picard_relaxation: float = 0.5,
    buoyancy_params: BuoyancyParams = BuoyancyParams(),
) -> tuple[AdaptiveReducedModel, GreedyBasis]:
    """Build the adaptive reduced model directly from the geometry.

    Note there is no full-solver run anywhere in here: the greedy basis is trained by
    sampling the circulation strength, which the operator depends on affinely. That is
    what lets the API drop the extra linearisation day it used to need.
    """
    room_mesh = build_room_mesh(room, heat_source, nx, ny)
    operator = build_affine_operator(room_mesh, room)
    trained = greedy_basis(
        operator,
        s_max=buoyancy_params.max_speed_m_s,
        tol=tol,
        max_basis_size=max_basis_size,
    )

    basis = trained.basis
    n_cells = operator.n_cells
    directions = operator.forcing_directions()

    model = AdaptiveReducedModel(
        basis=basis,
        a_r0=basis.T @ operator.a0 @ basis,
        a_r1=basis.T @ operator.a1 @ basis,
        forcing_boundary_r=basis.T @ directions[:, 0],
        forcing_heater_r=basis.T @ directions[:, 1],
        avg_row=(np.ones(n_cells) / n_cells) @ basis,
        heat_source_row=basis[operator.heat_source_cell, :],
        buoyancy_params=buoyancy_params,
        s_max=buoyancy_params.max_speed_m_s,
        n_s_bins=n_s_bins,
        picard_iterations=picard_iterations,
        picard_relaxation=picard_relaxation,
        room_mesh=room_mesh,
    )
    return model, trained


def _step_modal_state(z: np.ndarray, lambdas: np.ndarray, rhs: np.ndarray, dt_s: float) -> np.ndarray:
    """Exact solution of dz/dt = -lambda*z + rhs over one step, for piecewise-
    constant rhs -- exponential (matrix-exponential-equivalent, decoupled per
    mode) integration, so there is no timestep-size stability constraint."""
    exp_term = np.exp(-lambdas * dt_s)
    small = np.abs(lambdas) < 1e-10
    safe_lambdas = np.where(small, 1.0, lambdas)
    integral_term = np.where(small, rhs * dt_s, (rhs / safe_lambdas) * (1 - exp_term))
    return z * exp_term + integral_term


@dataclass
class ReducedDayResult:
    day_of_year: int
    hours: np.ndarray
    room_avg_temp_c: np.ndarray
    heater_power_w: np.ndarray

    def energy_kwh(self, dt_s: float) -> float:
        return float(np.sum(self.heater_power_w) * dt_s / 3600.0 / 1000.0)


def simulate_reduced_days(
    reduced_model: ReducedModel | AdaptiveReducedModel,
    heat_source: HeatSource,
    climate: ClimateLocation,
    thermostat: ThermostatSettings,
    initial_temp_c: float,
    dt_s: float,
    n_days: int,
    start_day_of_year: int = 0,
    controller_params: PIControllerParams = PIControllerParams(),
) -> list[ReducedDayResult]:
    """Time-step a reduced model across `n_days` consecutive days of the year, using
    the same PI controller as the full solver.

    Each day sees its own climatological outdoor temperature, and thermal state
    carries across midnight, so a cold snap genuinely leaves the room colder going
    into the next morning. Running this for a full year costs seconds, where the
    full nonlinear solver would cost well over half an hour -- that gap is the whole
    reason the reduction exists.

    Works with either reduction: both expose `project` / `room_avg_temp_c` / `step`,
    and the choice of which one is passed in is the only difference between the
    baseline and adaptive results reported by the app.
    """
    n_cells = reduced_model.room_mesh.mesh.n_cells
    z = reduced_model.project(np.full(n_cells, initial_temp_c))

    steps_per_day = int(round(24 * 3600 / dt_s))
    controller_state = ControllerState()
    results: list[ReducedDayResult] = []

    for day_offset in range(n_days):
        day_of_year = (start_day_of_year + day_offset) % DAYS_PER_YEAR
        day_start_hours = day_of_year * 24.0

        hours = np.zeros(steps_per_day)
        room_avg_temp_c = np.zeros(steps_per_day)
        heater_power_w = np.zeros(steps_per_day)

        for step in range(steps_per_day):
            hour = (step * dt_s) / 3600.0
            room_avg_now_c = reduced_model.room_avg_temp_c(z)
            power_w = pi_power_w(
                room_avg_now_c,
                hour,
                thermostat,
                heat_source.max_power_w,
                dt_s,
                controller_state,
                controller_params,
            )
            outdoor_temp_c = climate.outdoor_temp_c(day_start_hours + hour)

            z = reduced_model.step(z, outdoor_temp_c, power_w, dt_s)

            hours[step] = hour
            room_avg_temp_c[step] = room_avg_now_c
            heater_power_w[step] = power_w

        results.append(
            ReducedDayResult(
                day_of_year=day_of_year,
                hours=hours,
                room_avg_temp_c=room_avg_temp_c,
                heater_power_w=heater_power_w,
            )
        )

    return results


def build_reduced_model_from_day(
    representative: DayResult,
    room: Room,
    n_modes: int = 10,
) -> ReducedModel:
    """Linearize about an already-computed full-FVM day: freeze the buoyancy velocity
    field to the pattern implied by that day's time-averaged temperature, then reduce."""
    mean_field_c = representative.temperature_fields_c.mean(axis=0)
    u_frozen, v_frozen = buoyancy_velocity(
        representative.room_mesh, room.width_m, room.height_m, mean_field_c, BuoyancyParams()
    )
    return build_reduced_model(representative.room_mesh, u_frozen, v_frozen, n_modes)


@dataclass
class AnnualEnergyResult:
    total_kwh: float
    monthly_kwh: list[float]  # 12 entries, January first
    daily_kwh: list[float]  # 365 entries
    daily_mean_indoor_c: list[float]
    daily_mean_outdoor_c: list[float]


def _run_annual_energy(
    reduced_model: ReducedModel | AdaptiveReducedModel,
    heat_source: HeatSource,
    climate: ClimateLocation,
    thermostat: ThermostatSettings,
    initial_temp_c: float,
    spin_up_days: int,
    dt_s: float,
) -> AnnualEnergyResult:
    """Shared year-long time-marching core for both reductions.

    `spin_up_days` runs the tail end of December first, purely so the year starts from
    a thermally settled state rather than an arbitrary uniform temperature; those days
    are discarded.
    """
    spin_up = simulate_reduced_days(
        reduced_model,
        heat_source,
        climate,
        thermostat,
        initial_temp_c=initial_temp_c,
        dt_s=dt_s,
        n_days=spin_up_days,
        start_day_of_year=DAYS_PER_YEAR - spin_up_days,
    )
    warm_start_c = float(spin_up[-1].room_avg_temp_c[-1]) if spin_up else initial_temp_c

    year = simulate_reduced_days(
        reduced_model,
        heat_source,
        climate,
        thermostat,
        initial_temp_c=warm_start_c,
        dt_s=dt_s,
        n_days=DAYS_PER_YEAR,
        start_day_of_year=0,
    )

    daily_kwh = [day.energy_kwh(dt_s) for day in year]
    monthly_kwh = [0.0] * 12
    for day, energy_kwh in zip(year, daily_kwh):
        monthly_kwh[month_of_day(day.day_of_year)] += energy_kwh

    daily_mean_outdoor_c = [
        float(np.mean([climate.outdoor_temp_c(day.day_of_year * 24.0 + h) for h in day.hours]))
        for day in year
    ]

    return AnnualEnergyResult(
        total_kwh=float(sum(daily_kwh)),
        monthly_kwh=monthly_kwh,
        daily_kwh=daily_kwh,
        daily_mean_indoor_c=[float(np.mean(day.room_avg_temp_c)) for day in year],
        daily_mean_outdoor_c=daily_mean_outdoor_c,
    )


def estimate_annual_energy(
    representative: DayResult,
    room: Room,
    heat_source: HeatSource,
    climate: ClimateLocation,
    thermostat: ThermostatSettings,
    n_modes: int = 10,
    spin_up_days: int = 10,
    dt_s: float = 900.0,
) -> AnnualEnergyResult:
    """Baseline path: simulate the full year on the frozen single-point reduction.

    Because the reduced operator is invariant to outdoor temperature, the single
    linearization built from `representative` is valid across the whole year -- only
    its *accuracy* degrades for days far from that operating point, which
    `solver/validation.py` quantifies (and which motivated `estimate_annual_energy_adaptive`).
    """
    reduced_model = build_reduced_model_from_day(representative, room, n_modes)
    initial_temp_c = float(representative.temperature_fields_c.mean())
    return _run_annual_energy(
        reduced_model, heat_source, climate, thermostat, initial_temp_c, spin_up_days, dt_s
    )


def estimate_annual_energy_adaptive(
    room: Room,
    heat_source: HeatSource,
    climate: ClimateLocation,
    thermostat: ThermostatSettings,
    nx: int = 12,
    ny: int = 9,
    spin_up_days: int = 10,
    dt_s: float = 900.0,
    initial_temp_c: float = 18.0,
) -> AnnualEnergyResult:
    """Adaptive path: simulate the full year on the greedy-RB model, recomputing the
    buoyancy nonlinearity every step instead of freezing it.

    Needs no full-solver day at all -- the basis is trained by sampling the
    circulation strength directly (see `build_adaptive_model`) -- which is what lets
    the API drop the separate linearisation solve the baseline path used to need.
    """
    reduced_model, _ = build_adaptive_model(room, heat_source, nx=nx, ny=ny)
    return _run_annual_energy(
        reduced_model, heat_source, climate, thermostat, initial_temp_c, spin_up_days, dt_s
    )
