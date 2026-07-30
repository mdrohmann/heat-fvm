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
    simulate_representative_day,
)
from solver.geometry import HeatSource, Room, RoomMesh
from solver.materials import ClimatePreset, ThermostatSettings

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
    hours: np.ndarray
    room_avg_temp_c: np.ndarray
    heater_power_w: np.ndarray


def simulate_reduced_days(
    reduced_model: ReducedModel,
    heat_source: HeatSource,
    climate: ClimatePreset,
    thermostat: ThermostatSettings,
    initial_temp_c: float,
    dt_s: float,
    n_days: int,
    controller_params: PIControllerParams = PIControllerParams(),
) -> list[ReducedDayResult]:
    """Time-step the reduced (linear) model for `n_days`, using the same PI
    controller as the full solver. Cheap enough to run for a whole month directly,
    but the caller typically only needs enough days to reach the repeating
    (periodic-steady-state) daily pattern -- see `estimate_monthly_energy_kwh`."""
    n_cells = reduced_model.room_mesh.mesh.n_cells
    z = reduced_model.w_r @ np.full(n_cells, initial_temp_c)

    steps_per_day = int(round(24 * 3600 / dt_s))
    controller_state = ControllerState()
    results: list[ReducedDayResult] = []

    for _day in range(n_days):
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
            outdoor_temp_c = climate.outdoor_temp_c(hour)

            forcing = reduced_model.boundary_conductance_w_per_k * outdoor_temp_c
            forcing[reduced_model.heat_source_cell] += power_w
            rhs = (reduced_model.w_r @ forcing) / reduced_model.cell_mass_j_per_k

            z = _step_modal_state(z, reduced_model.lambdas, rhs, dt_s)

            hours[step] = hour
            room_avg_temp_c[step] = room_avg_now_c
            heater_power_w[step] = power_w

        results.append(
            ReducedDayResult(hours=hours, room_avg_temp_c=room_avg_temp_c, heater_power_w=heater_power_w)
        )

    return results


def estimate_monthly_energy_kwh(
    room: Room,
    heat_source: HeatSource,
    climate: ClimatePreset,
    thermostat: ThermostatSettings,
    nx: int = 20,
    ny: int = 15,
    n_modes: int = 10,
    settle_days: int = 4,
    days_in_month: int = 30,
    dt_s: float = 900.0,
) -> float:
    """Estimate monthly heater energy by linearizing about a representative day
    and reducing via modal truncation, instead of running the full nonlinear FVM
    for a whole month."""
    representative = simulate_representative_day(room, heat_source, climate, thermostat, nx=nx, ny=ny)
    return estimate_monthly_energy_from_day(
        representative,
        room,
        heat_source,
        climate,
        thermostat,
        n_modes=n_modes,
        settle_days=settle_days,
        days_in_month=days_in_month,
        dt_s=dt_s,
    )


def estimate_monthly_energy_from_day(
    representative: DayResult,
    room: Room,
    heat_source: HeatSource,
    climate: ClimatePreset,
    thermostat: ThermostatSettings,
    n_modes: int = 10,
    settle_days: int = 4,
    days_in_month: int = 30,
    dt_s: float = 900.0,
) -> float:
    """Same as `estimate_monthly_energy_kwh`, but reuses an already-computed
    representative-day solve (e.g. one also used to drive the visualization),
    instead of paying for a second full nonlinear FVM day."""
    mean_field_c = representative.temperature_fields_c.mean(axis=0)
    u_frozen, v_frozen = buoyancy_velocity(
        representative.room_mesh, room.width_m, room.height_m, mean_field_c, BuoyancyParams()
    )

    reduced_model = build_reduced_model(representative.room_mesh, u_frozen, v_frozen, n_modes)

    day_results = simulate_reduced_days(
        reduced_model,
        heat_source,
        climate,
        thermostat,
        initial_temp_c=float(mean_field_c.mean()),
        dt_s=dt_s,
        n_days=settle_days + 1,
    )
    periodic_day = day_results[-1]
    daily_energy_kwh = float(np.sum(periodic_day.heater_power_w) * dt_s / 3600.0 / 1000.0)

    return daily_energy_kwh * days_in_month
