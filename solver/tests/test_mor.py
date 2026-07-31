import numpy as np
import pytest

from solver.climate import DAYS_PER_YEAR, get_climate
from solver.fvm import simulate_representative_day
from solver.geometry import HeatSource, Room
from solver.materials import DEFAULT_THERMOSTAT, suggested_heater_power_w
from solver.mor import (
    _select_mode_indices,
    build_reduced_model_from_day,
    estimate_annual_energy,
    simulate_reduced_days,
)


def _room_source_climate(climate_id: str = "berlin") -> tuple[Room, HeatSource, object]:
    room = Room(width_m=4.0, height_m=3.0)
    climate = get_climate(climate_id)
    heat_source = HeatSource(
        x_m=2.0, y_m=1.5, max_power_w=suggested_heater_power_w(room, climate, DEFAULT_THERMOSTAT)
    )
    return room, heat_source, climate


def test_select_mode_indices_keeps_conjugate_pairs_whole():
    eigenvalues = np.array([0.1, 0.2 + 1.0j, 0.2 - 1.0j, 0.5, 0.9])
    # Requesting 2 modes would otherwise split the 0.2+-1j conjugate pair (both
    # tied for 2nd/3rd-smallest real part) -- selection must expand to keep both.
    selected = _select_mode_indices(eigenvalues, n_modes=2)
    selected_values = set(eigenvalues[selected])
    assert eigenvalues[0] in selected_values
    assert (0.2 + 1.0j) in selected_values
    assert (0.2 - 1.0j) in selected_values


def test_reduced_operator_is_invariant_to_outdoor_temperature():
    # The property that lets a single linearisation serve every day of the year:
    # outdoor temperature enters only through the forcing, never the operator.
    from solver.fvm import BuoyancyParams, assemble_operator, buoyancy_velocity

    room, heat_source, climate = _room_source_climate()
    day = simulate_representative_day(
        room, heat_source, climate, DEFAULT_THERMOSTAT, nx=6, ny=5, dt_s=1800.0
    )
    u, v = buoyancy_velocity(
        day.room_mesh, room.width_m, room.height_m, day.temperature_fields_c.mean(axis=0), BuoyancyParams()
    )

    k_cold, b_cold = assemble_operator(day.room_mesh, u, v, outdoor_temp_c=-25.0)
    k_warm, b_warm = assemble_operator(day.room_mesh, u, v, outdoor_temp_c=35.0)

    assert abs((k_cold - k_warm)).max() == 0.0
    assert np.allclose(b_warm / 35.0, b_cold / -25.0)


def test_reduced_model_stays_numerically_sane_over_a_day():
    room, heat_source, climate = _room_source_climate()
    representative = simulate_representative_day(
        room, heat_source, climate, DEFAULT_THERMOSTAT, nx=8, ny=6, initial_temp_c=15.0
    )
    reduced_model = build_reduced_model_from_day(representative, room, n_modes=10)

    day_results = simulate_reduced_days(
        reduced_model, heat_source, climate, DEFAULT_THERMOSTAT,
        initial_temp_c=15.0, dt_s=900.0, n_days=1,
    )
    assert np.all(np.isfinite(day_results[0].room_avg_temp_c))


def test_reduced_days_track_the_calendar_and_see_different_weather():
    # The whole reason the reduction is worth having: consecutive days are genuinely
    # different problems, not the same day replayed.
    room, heat_source, climate = _room_source_climate()
    representative = simulate_representative_day(
        room, heat_source, climate, DEFAULT_THERMOSTAT, nx=6, ny=5, dt_s=1800.0
    )
    reduced_model = build_reduced_model_from_day(representative, room, n_modes=8)

    winter = simulate_reduced_days(
        reduced_model, heat_source, climate, DEFAULT_THERMOSTAT,
        initial_temp_c=18.0, dt_s=1800.0, n_days=3, start_day_of_year=10,
    )
    summer = simulate_reduced_days(
        reduced_model, heat_source, climate, DEFAULT_THERMOSTAT,
        initial_temp_c=18.0, dt_s=1800.0, n_days=3, start_day_of_year=190,
    )

    assert [d.day_of_year for d in winter] == [10, 11, 12]
    assert winter[0].energy_kwh(1800.0) > summer[0].energy_kwh(1800.0)


def test_reduced_days_wrap_around_the_year_boundary():
    room, heat_source, climate = _room_source_climate()
    representative = simulate_representative_day(
        room, heat_source, climate, DEFAULT_THERMOSTAT, nx=6, ny=5, dt_s=1800.0
    )
    reduced_model = build_reduced_model_from_day(representative, room, n_modes=8)

    days = simulate_reduced_days(
        reduced_model, heat_source, climate, DEFAULT_THERMOSTAT,
        initial_temp_c=18.0, dt_s=1800.0, n_days=3, start_day_of_year=DAYS_PER_YEAR - 2,
    )
    assert [d.day_of_year for d in days] == [DAYS_PER_YEAR - 2, DAYS_PER_YEAR - 1, 0]


def test_annual_energy_has_seasonal_structure():
    room, heat_source, climate = _room_source_climate()
    representative = simulate_representative_day(
        room, heat_source, climate, DEFAULT_THERMOSTAT, nx=8, ny=6, dt_s=1800.0
    )

    annual = estimate_annual_energy(
        representative, room, heat_source, climate, DEFAULT_THERMOSTAT, dt_s=1800.0
    )

    assert len(annual.monthly_kwh) == 12
    assert len(annual.daily_kwh) == DAYS_PER_YEAR
    assert annual.total_kwh == pytest.approx(sum(annual.daily_kwh), rel=1e-6)
    assert annual.total_kwh == pytest.approx(sum(annual.monthly_kwh), rel=1e-6)

    # Northern-hemisphere heating: January must cost far more than July.
    assert annual.monthly_kwh[0] > annual.monthly_kwh[6]
    # And the indoor temperature should stay near target year-round regardless.
    assert min(annual.daily_mean_indoor_c) > DEFAULT_THERMOSTAT.night_target_c - 3.0


def test_annual_energy_is_higher_in_a_colder_climate():
    room = Room(width_m=4.0, height_m=3.0)
    results = {}
    for climate_id in ("phoenix", "reykjavik"):
        climate = get_climate(climate_id)
        heat_source = HeatSource(
            x_m=2.0, y_m=1.5, max_power_w=suggested_heater_power_w(room, climate, DEFAULT_THERMOSTAT)
        )
        representative = simulate_representative_day(
            room, heat_source, climate, DEFAULT_THERMOSTAT, nx=6, ny=5, dt_s=1800.0
        )
        results[climate_id] = estimate_annual_energy(
            representative, room, heat_source, climate, DEFAULT_THERMOSTAT, dt_s=1800.0
        ).total_kwh

    assert results["reykjavik"] > results["phoenix"]
