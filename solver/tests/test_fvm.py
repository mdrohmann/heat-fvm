import numpy as np
import pytest
import scipy.sparse.linalg as spla

from solver.fvm import BuoyancyParams, assemble_operator, backward_euler_step, simulate_representative_day
from solver.geometry import HeatSource, Room, build_room_mesh
from solver.climate import get_climate
from solver.materials import (
    DEFAULT_THERMOSTAT,
    DEFAULT_U_VALUES_W_PER_M2K,
    suggested_heater_power_w,
)


def _default_room_and_source() -> tuple[Room, HeatSource]:
    room = Room(width_m=4.0, height_m=3.0)
    heat_source = HeatSource(x_m=2.0, y_m=1.5, max_power_w=1500.0)
    return room, heat_source


def test_steady_state_energy_balance_holds_for_arbitrary_velocity_field():
    # This is the core regression test for the flux assembly: whatever the
    # velocity field looks like (even a non-physical, non-divergence-free one),
    # interior fluxes must cancel exactly in pairs, so at steady state total
    # boundary heat loss must equal the injected heater power exactly.
    room, heat_source = _default_room_and_source()
    room_mesh = build_room_mesh(room, heat_source, nx=6, ny=5)

    rng = np.random.default_rng(0)
    u = rng.uniform(-0.1, 0.1, room_mesh.mesh.n_cells)
    v = rng.uniform(-0.1, 0.1, room_mesh.mesh.n_cells)

    outdoor_temp_c = 5.0
    K, b = assemble_operator(room_mesh, u, v, outdoor_temp_c)
    b = b.copy()
    b[room_mesh.heat_source_cell] += heat_source.max_power_w

    T = spla.spsolve(K.tocsc(), b)

    boundary_loss_w = sum(
        DEFAULT_U_VALUES_W_PER_M2K[face.element_type]
        * face.face_area_m2
        * (T[face.cell_index] - outdoor_temp_c)
        for face in room_mesh.boundary_faces
    )
    assert boundary_loss_w == pytest.approx(heat_source.max_power_w, rel=1e-6)


def test_room_warms_up_toward_a_plausible_temperature():
    # heat_source.max_power_w (1500W) is sized for a thermostatically-cycled heater,
    # not continuous full power -- held on forever it would cook the room (this
    # room's UA is small enough that steady-state would be ~170C above outdoor,
    # which is correct physics, just not "plausible room temperature"). Use a
    # modest constant power here instead, matched to give a sane steady rise.
    room, heat_source = _default_room_and_source()
    room_mesh = build_room_mesh(room, heat_source, nx=8, ny=6)
    dt_s = 300.0
    constant_power_w = 200.0

    temperature_c = np.full(room_mesh.mesh.n_cells, 10.0)
    avg_history = []
    for _ in range(60):
        temperature_c = backward_euler_step(
            room, room_mesh, temperature_c, dt_s,
            outdoor_temp_c=2.0, heater_power_w=constant_power_w, buoyancy_params=BuoyancyParams(),
        )
        avg_history.append(float(np.mean(temperature_c)))

    assert np.all(np.isfinite(avg_history))
    assert avg_history[-1] > avg_history[0]
    assert 10.0 < avg_history[-1] < 30.0


def test_buoyancy_convection_reduces_spatial_temperature_spread():
    room, heat_source = _default_room_and_source()
    room_mesh = build_room_mesh(room, heat_source, nx=10, ny=8)
    dt_s = 300.0
    n_steps = 40

    def run(buoyancy_params: BuoyancyParams) -> np.ndarray:
        temperature_c = np.full(room_mesh.mesh.n_cells, 10.0)
        for _ in range(n_steps):
            temperature_c = backward_euler_step(
                room, room_mesh, temperature_c, dt_s,
                outdoor_temp_c=2.0, heater_power_w=1500.0, buoyancy_params=buoyancy_params,
            )
        return temperature_c

    temperature_no_convection = run(BuoyancyParams(strength_per_kelvin=0.0, max_speed_m_s=0.0))
    temperature_with_convection = run(BuoyancyParams())

    assert np.std(temperature_with_convection) < np.std(temperature_no_convection)


def test_pi_thermostat_cycles_heater_over_a_representative_day():
    room, heat_source = _default_room_and_source()
    climate = get_climate("berlin")

    result = simulate_representative_day(
        room, heat_source, climate, DEFAULT_THERMOSTAT,
        nx=8, ny=6, dt_s=900.0, initial_temp_c=10.0,
    )

    assert np.all(np.isfinite(result.room_avg_temp_c))
    assert result.heater_power_w.max() == pytest.approx(heat_source.max_power_w)
    assert result.heater_power_w.min() == 0.0
    assert 0 < np.count_nonzero(result.heater_power_w) < len(result.heater_power_w)


def test_pi_thermostat_tracks_target_tightly_with_a_right_sized_heater():
    # This is the regression test for the overshoot problem a flat, oversized
    # heater default caused with bang-bang control: with a heater sized from the
    # room's own physics and a PI controller, the room should settle close to
    # the day target rather than swinging several degrees past it.
    room = Room(width_m=4.0, height_m=3.0)
    climate = get_climate("berlin")
    heat_source = HeatSource(x_m=2.0, y_m=1.5, max_power_w=suggested_heater_power_w(room, climate, DEFAULT_THERMOSTAT))

    result = simulate_representative_day(
        room, heat_source, climate, DEFAULT_THERMOSTAT,
        nx=8, ny=6, dt_s=300.0, initial_temp_c=10.0,
    )

    # Ignore the first half of the day: starting 10.5C below target, the
    # controller saturates to full power to catch up, which is correct
    # behavior, not overshoot.
    settled = result.room_avg_temp_c[len(result.room_avg_temp_c) // 2 :]
    assert settled.max() < DEFAULT_THERMOSTAT.day_target_c + 1.0
