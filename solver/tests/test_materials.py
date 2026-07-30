import pytest

from solver.geometry import Room, WallElement, WallElementType
from solver.materials import (
    CLIMATE_PRESETS,
    DEFAULT_THERMOSTAT,
    ThermostatSettings,
    suggested_heater_power_w,
)


def test_climate_preset_outdoor_temp_peaks_and_troughs_correctly():
    preset = CLIMATE_PRESETS["temperate_winter"]
    peak_temp = preset.outdoor_temp_c(preset.peak_hour)
    trough_temp = preset.outdoor_temp_c(preset.peak_hour + 12.0)

    assert peak_temp == pytest.approx(
        preset.mean_outdoor_temp_c + preset.diurnal_amplitude_c / 2.0
    )
    assert trough_temp == pytest.approx(
        preset.mean_outdoor_temp_c - preset.diurnal_amplitude_c / 2.0
    )


def test_climate_preset_mean_over_full_day_matches_mean_outdoor_temp():
    preset = CLIMATE_PRESETS["hot_summer"]
    hours = [h for h in range(0, 24)]
    avg = sum(preset.outdoor_temp_c(h) for h in hours) / len(hours)
    assert avg == pytest.approx(preset.mean_outdoor_temp_c, abs=1e-2)


def test_thermostat_switches_between_day_and_night_targets():
    settings = ThermostatSettings(
        day_target_c=21.0, night_target_c=17.0, day_start_hour=6.0, night_start_hour=22.0
    )
    assert settings.target_temp_c(6.0) == pytest.approx(21.0)
    assert settings.target_temp_c(13.0) == pytest.approx(21.0)
    assert settings.target_temp_c(21.9) == pytest.approx(21.0)
    assert settings.target_temp_c(22.0) == pytest.approx(17.0)
    assert settings.target_temp_c(2.0) == pytest.approx(17.0)


def test_default_thermostat_has_lower_night_target_than_day():
    assert DEFAULT_THERMOSTAT.night_target_c < DEFAULT_THERMOSTAT.day_target_c


def test_suggested_heater_power_scales_with_room_loss_coefficient():
    small_room = Room(width_m=3.0, height_m=3.0)
    large_room = Room(width_m=8.0, height_m=6.0)
    climate = CLIMATE_PRESETS["temperate_winter"]

    small = suggested_heater_power_w(small_room, climate, DEFAULT_THERMOSTAT)
    large = suggested_heater_power_w(large_room, climate, DEFAULT_THERMOSTAT)

    assert 0 < small < large


def test_suggested_heater_power_accounts_for_worse_insulation():
    room = Room(
        width_m=4.0,
        height_m=3.0,
        walls={
            "north": [],
            "east": [WallElement(WallElementType.WINDOW, 0.9, 1.2)],
            "south": [WallElement(WallElementType.DOOR, 1.5, 0.9)],
            "west": [],
        },
    )
    climate = CLIMATE_PRESETS["temperate_winter"]

    well_insulated = suggested_heater_power_w(room, climate, DEFAULT_THERMOSTAT)
    poorly_insulated = suggested_heater_power_w(
        room,
        climate,
        DEFAULT_THERMOSTAT,
        u_values_w_per_m2k={
            WallElementType.WALL: 2.0,
            WallElementType.WINDOW: 5.0,
            WallElementType.DOOR: 3.0,
        },
    )

    assert poorly_insulated > well_insulated


def test_suggested_heater_power_for_default_demo_room_is_realistic():
    # Regression pin for the flat-1500W-was-way-oversized bug: the default demo
    # room/climate/thermostat combo should suggest a heater sized in the
    # low-hundreds of watts, not kilowatts.
    room = Room(
        width_m=4.0,
        height_m=3.0,
        walls={
            "north": [],
            "east": [WallElement(WallElementType.WINDOW, 0.9, 1.2)],
            "south": [WallElement(WallElementType.DOOR, 1.5, 0.9)],
            "west": [],
        },
    )
    climate = CLIMATE_PRESETS["temperate_winter"]

    power_w = suggested_heater_power_w(room, climate, DEFAULT_THERMOSTAT)
    assert 300.0 < power_w < 700.0
