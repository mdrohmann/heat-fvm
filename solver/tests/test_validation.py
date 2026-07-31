"""Regression tests pinning the reduced model's accuracy.

The point of these is to fail loudly if a change to the solver, the reduction, or the
linearisation-point heuristic quietly degrades surrogate accuracy -- the failure mode
that is otherwise invisible, because a wrong-but-plausible number still renders fine.
"""

import pytest

from solver.climate import climate_locations, get_climate
from solver.geometry import HeatSource, Room, WallElement, WallElementType
from solver.materials import DEFAULT_THERMOSTAT, suggested_heater_power_w
from solver.validation import load_baked_validation, validate_across_days


def _reference_room() -> Room:
    return Room(
        width_m=4.0,
        height_m=3.0,
        walls={
            "north": [],
            "east": [WallElement(WallElementType.WINDOW, offset_m=0.9, length_m=1.2)],
            "south": [WallElement(WallElementType.DOOR, offset_m=1.5, length_m=0.9)],
            "west": [],
        },
    )


# Reduced-vs-full agreement turns out to be far more sensitive to the timestep than
# to the mesh: on a summer day, dt=1800s puts the two models 1.81 kWh apart, dt=900s
# 0.30 kWh, and dt=300s 0.24 kWh -- because at a coarse dt neither the PI controller
# nor the full model's backward-Euler steps are well resolved, so the disagreement is
# temporal discretisation rather than the reduction. These tests therefore run at the
# timestep the annual estimate actually uses; a "fast" coarser setting would measure
# the wrong thing.
VALIDATION_NX, VALIDATION_NY, VALIDATION_DT_S = 12, 9, 900.0


def _berlin_case():
    room = _reference_room()
    climate = get_climate("berlin")
    heat_source = HeatSource(
        x_m=0.4, y_m=1.5, max_power_w=suggested_heater_power_w(room, climate, DEFAULT_THERMOSTAT)
    )
    return room, heat_source, climate


def test_reduced_model_tracks_full_model_across_seasons():
    # A live validation rather than a check of the baked file: winter, spring and
    # summer days against the full nonlinear solver.
    room, heat_source, climate = _berlin_case()

    report = validate_across_days(
        room, heat_source, climate, DEFAULT_THERMOSTAT,
        sample_days=[14, 104, 195],
        linearization_day_of_year=climate.linearization_day_of_year(DEFAULT_THERMOSTAT.day_target_c),
        nx=VALIDATION_NX, ny=VALIDATION_NY, dt_s=VALIDATION_DT_S,
    )

    assert len(report.points) == 3
    # Total energy is the headline quantity and the one that must stay trustworthy.
    assert abs(report.annual_energy_relative_error) < 0.10
    # Errors should be small in absolute terms on every day, including mild ones
    # where the relative figure is meaningless.
    assert report.max_abs_error_kwh < 0.6


def test_reduced_model_is_most_accurate_on_high_demand_days():
    # The property that makes a single linearisation defensible: error concentrates
    # on mild, low-energy days, not on the cold days that dominate annual usage.
    room, heat_source, climate = _berlin_case()

    report = validate_across_days(
        room, heat_source, climate, DEFAULT_THERMOSTAT,
        sample_days=[14, 195],
        linearization_day_of_year=climate.linearization_day_of_year(DEFAULT_THERMOSTAT.day_target_c),
        nx=VALIDATION_NX, ny=VALIDATION_NY, dt_s=VALIDATION_DT_S,
    )
    winter, summer = report.points[0], report.points[1]

    assert winter.full_energy_kwh > summer.full_energy_kwh
    assert abs(winter.absolute_error_kwh) < abs(summer.absolute_error_kwh) or (
        abs(winter.relative_error) < abs(summer.relative_error)
    )
    assert abs(winter.relative_error) < 0.15


def test_relative_error_is_zero_when_no_heating_is_required():
    from solver.validation import ValidationPoint

    point = ValidationPoint(
        day_of_year=195, mean_outdoor_temp_c=25.0, full_energy_kwh=0.0, reduced_energy_kwh=0.0
    )
    assert point.relative_error == 0.0


def test_baked_validation_covers_every_climate_and_stays_within_bounds():
    baked = load_baked_validation()["locations"]
    assert set(baked) == set(climate_locations())

    for location_id, entry in baked.items():
        assert entry["points"], f"{location_id}: no validation points recorded"
        assert abs(entry["total_energy_relative_error"]) < 0.15, (
            f"{location_id}: baked annual energy error exceeds 15%"
        )


def test_baked_validation_matches_current_linearization_heuristic():
    # Guards against the baked study silently going stale relative to the code that
    # picks the linearisation day.
    baked = load_baked_validation()["locations"]
    for location_id, entry in baked.items():
        expected = get_climate(location_id).linearization_day_of_year(DEFAULT_THERMOSTAT.day_target_c)
        assert entry["linearization_day_of_year"] == expected, (
            f"{location_id}: baked validation is stale -- re-run scripts/run_rom_validation.py"
        )
