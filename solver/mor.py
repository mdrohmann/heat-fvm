"""Model-order reduction: linearization about a representative day, modal
truncation, and monthly energy estimation.

The full solver in `fvm.py` is nonlinear (buoyancy velocity feeds back from the
temperature field), which is appropriate for the short, rich visualization window
but far too expensive to run for a full month. Here we freeze the buoyancy
velocity field to the pattern from a representative-day solve, which makes the
remaining dynamics linear (LTI) in temperature, then reduce that linear system via
modal truncation (keep the slowest-decaying eigenmodes of the discretized operator
-- these dominate the long-horizon/monthly behavior). The reduced model is
simulated with the *same* thermostat controller used by the full solver (see
`simulate_reduced_days`) until its daily energy consumption settles into a
repeating (periodic-steady-state) pattern; that representative day is then tiled
across the month.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import scipy.linalg

from solver.controller import ControllerState, PIControllerParams, pi_power_w
from solver.fvm import (
    AIR_RHO_C_J_PER_M3K,
    BuoyancyParams,
    DayResult,
    assemble_operator,
    buoyancy_velocity,
)
from solver.climate import DAYS_PER_YEAR, ClimateLocation, month_of_day
from solver.geometry import HeatSource, Room, RoomMesh
from solver.materials import ThermostatSettings

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
    lambdas: np.ndarray  # complex, shape (n_modes,)
    v_r: np.ndarray  # complex, shape (n_cells, n_modes) -- reconstructs the full field
    w_r: np.ndarray  # complex, shape (n_modes, n_cells) -- projects a field into modal coords
    avg_row: np.ndarray  # complex, shape (n_modes,) -- room-average reconstruction
    boundary_conductance_w_per_k: np.ndarray  # real, shape (n_cells,)
    cell_mass_j_per_k: float
    heat_source_cell: int
    room_mesh: RoomMesh


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
    reduced_model: ReducedModel,
    heat_source: HeatSource,
    climate: ClimateLocation,
    thermostat: ThermostatSettings,
    initial_temp_c: float,
    dt_s: float,
    n_days: int,
    start_day_of_year: int = 0,
    controller_params: PIControllerParams = PIControllerParams(),
) -> list[ReducedDayResult]:
    """Time-step the reduced (linear) model across `n_days` consecutive days of the
    year, using the same PI controller as the full solver.

    Each day sees its own climatological outdoor temperature, and thermal state
    carries across midnight, so a cold snap genuinely leaves the room colder going
    into the next morning. Running this for a full year costs seconds, where the
    full nonlinear solver would cost well over half an hour -- that gap is the whole
    reason the reduction exists.

    Note that only the *forcing* depends on outdoor temperature: the reduced
    operator (and hence the modal basis) is invariant to it, so one linearization
    serves every day of the year (see `build_reduced_model`).
    """
    n_cells = reduced_model.room_mesh.mesh.n_cells
    z = reduced_model.w_r @ np.full(n_cells, initial_temp_c)

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
            room_avg_now_c = float((reduced_model.avg_row @ z).real)
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

            forcing = reduced_model.boundary_conductance_w_per_k * outdoor_temp_c
            forcing[reduced_model.heat_source_cell] += power_w
            rhs = (reduced_model.w_r @ forcing) / reduced_model.cell_mass_j_per_k

            z = _step_modal_state(z, reduced_model.lambdas, rhs, dt_s)

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
    """Simulate a full year of genuinely different days on the reduced model and sum
    the heater energy.

    `spin_up_days` runs the tail end of December first, purely so the year starts from
    a thermally settled state rather than an arbitrary uniform temperature; those days
    are discarded. Because the reduced operator is invariant to outdoor temperature,
    the single linearization built from `representative` is valid across the whole
    year -- only its *accuracy* degrades for days far from that operating point, which
    `solver/validation.py` quantifies.
    """
    reduced_model = build_reduced_model_from_day(representative, room, n_modes)
    initial_temp_c = float(representative.temperature_fields_c.mean())

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
