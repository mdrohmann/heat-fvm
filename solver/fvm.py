"""FVM operator assembly (diffusion + Robin BCs + buoyancy advection) and time-stepping.

Energy balance per cell (flux-conservative form): M dT/dt = b - K(u) T, where
`K` bundles conductive diffusion between neighboring cells, upwind advection along
a buoyancy-driven circulation field `u`, and Robin (convective) boundary loss/gain;
`b` carries the boundary driving term (h*A*T_out) and the heat-source power.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterator

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

from solver.geometry import HeatSource, Mesh, Room, RoomMesh, WallElementType, build_room_mesh
from solver.materials import (
    AIR_DENSITY_KG_PER_M3,
    AIR_SPECIFIC_HEAT_J_PER_KGK,
    AIR_THERMAL_CONDUCTIVITY_W_PER_MK,
    ClimatePreset,
    DEFAULT_U_VALUES_W_PER_M2K,
    ThermostatSettings,
)
from solver.controller import ThermostatState, bang_bang_power_w

AIR_RHO_C_J_PER_M3K = AIR_DENSITY_KG_PER_M3 * AIR_SPECIFIC_HEAT_J_PER_KGK


@dataclass(frozen=True)
class BuoyancyParams:
    """Simplified buoyancy-driven convection: a single fixed-shape circulation roll
    (from a streamfunction that has exactly zero normal velocity on all four walls,
    so it never needs a separate boundary treatment) whose *strength* scales
    nonlinearly with the instantaneous temperature difference between the
    heat-source cell and the room average — this is what makes the system
    nonlinear, per the buoyancy-feedback decision in the project plan.
    """

    strength_per_kelvin: float = 0.02  # m/s of circulation speed per degree C of driving delta-T
    max_speed_m_s: float = 0.3


def _streamfunction_velocity(
    centers_m: np.ndarray, width_m: float, height_m: float
) -> tuple[np.ndarray, np.ndarray]:
    """Unit-strength velocity field from psi(x,y) = sin(pi x/W) sin(pi y/H).
    u = d(psi)/dy, v = -d(psi)/dx — analytically divergence-free and exactly zero
    normal component on every wall (no air mass crosses a wall)."""
    x = centers_m[:, 0]
    y = centers_m[:, 1]
    u = np.sin(math.pi * x / width_m) * (math.pi / height_m) * np.cos(math.pi * y / height_m)
    v = -(math.pi / width_m) * np.cos(math.pi * x / width_m) * np.sin(math.pi * y / height_m)
    return u, v


def buoyancy_velocity(
    room_mesh: RoomMesh,
    width_m: float,
    height_m: float,
    temperature_c: np.ndarray,
    params: BuoyancyParams,
) -> tuple[np.ndarray, np.ndarray]:
    """Velocity field (u, v) in m/s at each cell center for the current temperature
    field. Nonlinear: the driving delta-T is recomputed from `temperature_c`."""
    centers = room_mesh.mesh.cell_centers_m()
    u_unit, v_unit = _streamfunction_velocity(centers, width_m, height_m)

    room_avg = float(np.mean(temperature_c))
    delta_t = float(temperature_c[room_mesh.heat_source_cell]) - room_avg
    speed_scale = min(max(params.strength_per_kelvin * max(delta_t, 0.0), 0.0), params.max_speed_m_s)

    return speed_scale * u_unit, speed_scale * v_unit


def _interior_faces(mesh: Mesh) -> Iterator[tuple[int, int, int]]:
    """Yields (cell_i, cell_j, axis) for each interior face; axis 0 = x-direction
    (east-west neighbors), axis 1 = y-direction (north-south neighbors)."""
    nx, ny = mesh.shape
    for j in range(ny):
        for i in range(nx - 1):
            yield mesh.cell_index((i, j)), mesh.cell_index((i + 1, j)), 0
    for j in range(ny - 1):
        for i in range(nx):
            yield mesh.cell_index((i, j)), mesh.cell_index((i, j + 1)), 1


def assemble_operator(
    room_mesh: RoomMesh,
    u: np.ndarray,
    v: np.ndarray,
    outdoor_temp_c: float,
    u_values_w_per_m2k: dict[WallElementType, float] = DEFAULT_U_VALUES_W_PER_M2K,
) -> tuple[sp.csr_matrix, np.ndarray]:
    """Assemble K and b such that the cell energy balance reads `b - K @ T`."""
    mesh = room_mesh.mesh
    n = mesh.n_cells
    dx, dy = mesh.spacing_m
    depth = room_mesh.depth_m
    k = AIR_THERMAL_CONDUCTIVITY_W_PER_MK

    rows: list[int] = []
    cols: list[int] = []
    data: list[float] = []
    b = np.zeros(n)

    def add(i: int, j: int, val: float) -> None:
        rows.append(i)
        cols.append(j)
        data.append(val)

    for i, j, axis in _interior_faces(mesh):
        if axis == 0:
            face_area = dy * depth
            dist = dx
            u_n = 0.5 * (u[i] + u[j])
        else:
            face_area = dx * depth
            dist = dy
            u_n = 0.5 * (v[i] + v[j])

        cond = k * face_area / dist
        add(i, i, cond)
        add(i, j, -cond)
        add(j, j, cond)
        add(j, i, -cond)

        adv_coeff = AIR_RHO_C_J_PER_M3K * face_area
        u_n_pos = max(u_n, 0.0)
        u_n_neg = min(u_n, 0.0)
        add(i, i, adv_coeff * u_n_pos)
        add(i, j, adv_coeff * u_n_neg)
        add(j, j, -adv_coeff * u_n_neg)
        add(j, i, -adv_coeff * u_n_pos)

    for face in room_mesh.boundary_faces:
        h = u_values_w_per_m2k[face.element_type]
        cond = h * face.face_area_m2
        add(face.cell_index, face.cell_index, cond)
        b[face.cell_index] += cond * outdoor_temp_c

    K = sp.coo_matrix((data, (rows, cols)), shape=(n, n)).tocsr()
    return K, b


def backward_euler_step(
    room: Room,
    room_mesh: RoomMesh,
    temperature_prev_c: np.ndarray,
    dt_s: float,
    outdoor_temp_c: float,
    heater_power_w: float,
    buoyancy_params: BuoyancyParams,
    picard_iterations: int = 4,
) -> np.ndarray:
    """One implicit (backward Euler) timestep. The buoyancy velocity field depends
    on the unknown new temperature, so a short Picard fixed-point iteration re-derives
    the velocity from the latest temperature guess and re-solves the resulting
    linear system a handful of times — cheap here since each linear solve is small."""
    mesh = room_mesh.mesh
    n = mesh.n_cells
    cell_volume_m3 = mesh.cell_measure_m2 * room_mesh.depth_m
    m_over_dt = np.full(n, AIR_RHO_C_J_PER_M3K * cell_volume_m3 / dt_s)

    temperature_guess = temperature_prev_c.copy()
    for _ in range(picard_iterations):
        u, v = buoyancy_velocity(room_mesh, room.width_m, room.height_m, temperature_guess, buoyancy_params)
        K, b = assemble_operator(room_mesh, u, v, outdoor_temp_c)
        b = b.copy()
        b[room_mesh.heat_source_cell] += heater_power_w

        A = sp.diags(m_over_dt) + K
        rhs = m_over_dt * temperature_prev_c + b
        temperature_guess = spla.spsolve(A.tocsc(), rhs)

    return temperature_guess


@dataclass
class DayResult:
    hours: np.ndarray
    room_avg_temp_c: np.ndarray
    heater_power_w: np.ndarray
    temperature_fields_c: np.ndarray  # shape (n_steps, n_cells)
    room_mesh: RoomMesh = field(repr=False)


def simulate_representative_day(
    room: Room,
    heat_source: HeatSource,
    climate: ClimatePreset,
    thermostat: ThermostatSettings,
    nx: int = 20,
    ny: int = 15,
    dt_s: float = 300.0,
    initial_temp_c: float = 18.0,
    buoyancy_params: BuoyancyParams = BuoyancyParams(),
) -> DayResult:
    """Run the full nonlinear buoyancy-coupled FVM for one simulated day, with a
    bang-bang thermostat driving the heat source. This is the "short representative
    window" the project plan reserves for the rich, physically-complete solve — the
    monthly energy estimate instead uses a linearized reduced model (see mor.py)."""
    room_mesh = build_room_mesh(room, heat_source, nx, ny)
    n_steps = int(round(24 * 3600 / dt_s))

    temperature_c = np.full(room_mesh.mesh.n_cells, initial_temp_c, dtype=float)
    thermostat_state = ThermostatState()

    hours = np.zeros(n_steps)
    room_avg_temp_c = np.zeros(n_steps)
    heater_power_w = np.zeros(n_steps)
    fields = np.zeros((n_steps, room_mesh.mesh.n_cells))

    for step in range(n_steps):
        hour = (step * dt_s) / 3600.0
        outdoor_temp_c = climate.outdoor_temp_c(hour)
        power_w = bang_bang_power_w(
            float(np.mean(temperature_c)), hour, thermostat, heat_source.max_power_w, thermostat_state
        )

        temperature_c = backward_euler_step(
            room, room_mesh, temperature_c, dt_s, outdoor_temp_c, power_w, buoyancy_params
        )

        hours[step] = hour
        room_avg_temp_c[step] = float(np.mean(temperature_c))
        heater_power_w[step] = power_w
        fields[step] = temperature_c

    return DayResult(
        hours=hours,
        room_avg_temp_c=room_avg_temp_c,
        heater_power_w=heater_power_w,
        temperature_fields_c=fields,
        room_mesh=room_mesh,
    )
