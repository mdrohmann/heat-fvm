import numpy as np
import pytest

from solver.fvm import BuoyancyParams, buoyancy_velocity, simulate_representative_day
from solver.geometry import HeatSource, Room
from solver.materials import CLIMATE_PRESETS, DEFAULT_THERMOSTAT
from solver.mor import (
    _select_mode_indices,
    build_reduced_model,
    estimate_monthly_energy_kwh,
    simulate_reduced_days,
)


def _default_room_and_source() -> tuple[Room, HeatSource]:
    room = Room(width_m=4.0, height_m=3.0)
    heat_source = HeatSource(x_m=2.0, y_m=1.5, max_power_w=1500.0)
    return room, heat_source


def test_select_mode_indices_keeps_conjugate_pairs_whole():
    eigenvalues = np.array([0.1, 0.2 + 1.0j, 0.2 - 1.0j, 0.5, 0.9])
    # Requesting 2 modes would otherwise split the 0.2+-1j conjugate pair (both
    # tied for 2nd/3rd-smallest real part) -- selection must expand to keep both.
    selected = _select_mode_indices(eigenvalues, n_modes=2)
    selected_values = set(eigenvalues[selected])
    assert eigenvalues[0] in selected_values
    assert (0.2 + 1.0j) in selected_values
    assert (0.2 - 1.0j) in selected_values


def test_reduced_model_stays_numerically_sane_over_a_day():
    room, heat_source = _default_room_and_source()
    climate = CLIMATE_PRESETS["temperate_winter"]

    representative = simulate_representative_day(
        room, heat_source, climate, DEFAULT_THERMOSTAT, nx=8, ny=6, initial_temp_c=15.0
    )
    mean_field_c = representative.temperature_fields_c.mean(axis=0)
    u_frozen, v_frozen = buoyancy_velocity(
        representative.room_mesh, room.width_m, room.height_m, mean_field_c, BuoyancyParams()
    )
    reduced_model = build_reduced_model(representative.room_mesh, u_frozen, v_frozen, n_modes=10)

    day_results = simulate_reduced_days(
        reduced_model, heat_source, climate, DEFAULT_THERMOSTAT,
        initial_temp_c=float(mean_field_c.mean()), dt_s=900.0, n_days=1,
    )
    assert np.all(np.isfinite(day_results[0].room_avg_temp_c))


def test_reduced_model_daily_energy_matches_full_fvm_within_tolerance():
    # Core MOR validation per the project plan: the linearized/modally-truncated
    # model's daily energy should land in the same ballpark as the full nonlinear
    # FVM's, since it was linearized about that same day's conditions.
    room, heat_source = _default_room_and_source()
    climate = CLIMATE_PRESETS["temperate_winter"]
    dt_s = 900.0

    full_day = simulate_representative_day(
        room, heat_source, climate, DEFAULT_THERMOSTAT, nx=8, ny=6, dt_s=dt_s, initial_temp_c=15.0
    )
    full_day_energy_kwh = float(np.sum(full_day.heater_power_w) * dt_s / 3600.0 / 1000.0)

    mean_field_c = full_day.temperature_fields_c.mean(axis=0)
    u_frozen, v_frozen = buoyancy_velocity(
        full_day.room_mesh, room.width_m, room.height_m, mean_field_c, BuoyancyParams()
    )
    reduced_model = build_reduced_model(full_day.room_mesh, u_frozen, v_frozen, n_modes=10)
    reduced_day = simulate_reduced_days(
        reduced_model, heat_source, climate, DEFAULT_THERMOSTAT,
        initial_temp_c=15.0, dt_s=dt_s, n_days=1,
    )[0]
    reduced_day_energy_kwh = float(np.sum(reduced_day.heater_power_w) * dt_s / 3600.0 / 1000.0)

    assert full_day_energy_kwh > 0
    assert reduced_day_energy_kwh == pytest.approx(full_day_energy_kwh, rel=0.3)


def test_estimate_monthly_energy_kwh_is_positive_and_plausible():
    room, heat_source = _default_room_and_source()
    climate = CLIMATE_PRESETS["temperate_winter"]

    monthly_kwh = estimate_monthly_energy_kwh(
        room, heat_source, climate, DEFAULT_THERMOSTAT, nx=8, ny=6, n_modes=10,
    )

    assert monthly_kwh > 0
    max_possible_kwh = heat_source.max_power_w * 24 * 30 / 1000.0
    assert monthly_kwh < max_possible_kwh
