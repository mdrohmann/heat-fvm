import pytest

from solver.climate import get_climate
from solver.geometry import Room, WallElement, WallElementType
from solver.materials import (
    DEFAULT_THERMOSTAT,
    ThermostatSettings,
    room_ua_w_per_k,
    suggested_heater_power_w,
)


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


def test_room_ua_grows_with_area_and_with_openings():
    plain = Room(width_m=4.0, height_m=3.0)
    bigger = Room(width_m=8.0, height_m=6.0)
    with_window = Room(
        width_m=4.0,
        height_m=3.0,
        walls={
            "north": [],
            "east": [WallElement(WallElementType.WINDOW, 0.9, 1.2)],
            "south": [],
            "west": [],
        },
    )

    assert room_ua_w_per_k(bigger) > room_ua_w_per_k(plain)
    # A window is a much worse insulator than the wall it replaces.
    assert room_ua_w_per_k(with_window) > room_ua_w_per_k(plain)


def test_suggested_heater_power_scales_with_room_loss_coefficient():
    small_room = Room(width_m=3.0, height_m=3.0)
    large_room = Room(width_m=8.0, height_m=6.0)
    climate = get_climate("berlin")

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
    climate = get_climate("berlin")

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
    climate = get_climate("berlin")

    power_w = suggested_heater_power_w(room, climate, DEFAULT_THERMOSTAT)
    assert 300.0 < power_w < 700.0
