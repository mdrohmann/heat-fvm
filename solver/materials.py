"""Default physical parameters: U-values, air properties, climate presets, setpoints."""

from __future__ import annotations

import math
from dataclasses import dataclass

from solver.geometry import Room, WallElement, WallElementType

# Air properties at ~20C, sea level (standard reference values).
AIR_DENSITY_KG_PER_M3 = 1.2
AIR_SPECIFIC_HEAT_J_PER_KGK = 1005.0
AIR_THERMAL_CONDUCTIVITY_W_PER_MK = 0.026

# Default U-values (W/m^2K), the midpoint of each typical range documented in the
# project plan:
#   wall (insulated):     0.2 - 0.3
#   window (double-glaze): 1.2 - 2.8
#   door:                  1.5 - 3.0
DEFAULT_U_VALUES_W_PER_M2K: dict[WallElementType, float] = {
    WallElementType.WALL: 0.25,
    WallElementType.WINDOW: 1.8,
    WallElementType.DOOR: 2.0,
}


@dataclass(frozen=True)
class ClimatePreset:
    id: str
    label: str
    mean_outdoor_temp_c: float
    diurnal_amplitude_c: float
    peak_hour: float = 15.0  # outdoor temp peaks mid-afternoon by default

    def outdoor_temp_c(self, hour: float) -> float:
        """T_out(t) = T_mean + (amplitude/2) * cos(2*pi*(t - t_peak)/24), so the
        temperature is at its maximum exactly at `peak_hour`."""
        phase = 2 * math.pi * (hour - self.peak_hour) / 24.0
        return self.mean_outdoor_temp_c + (self.diurnal_amplitude_c / 2.0) * math.cos(phase)


CLIMATE_PRESETS: dict[str, ClimatePreset] = {
    preset.id: preset
    for preset in (
        ClimatePreset("temperate_winter", "Temperate winter (e.g. Berlin, Jan)", 2.0, 5.0),
        ClimatePreset("continental_winter", "Continental winter (e.g. Chicago, Jan)", -6.0, 8.0),
        ClimatePreset("mild_spring", "Mild spring (e.g. Berlin, Apr)", 10.0, 6.0),
        ClimatePreset("hot_summer", "Hot summer (e.g. Phoenix, Jul)", 33.0, 10.0),
    )
}


@dataclass(frozen=True)
class ThermostatSettings:
    day_target_c: float = 20.5
    night_target_c: float = 17.0
    day_start_hour: float = 6.0
    night_start_hour: float = 22.0

    def target_temp_c(self, hour: float) -> float:
        h = hour % 24.0
        is_day = self.day_start_hour <= h < self.night_start_hour
        return self.day_target_c if is_day else self.night_target_c


DEFAULT_THERMOSTAT = ThermostatSettings()


def _side_ua_w_per_k(
    elements: list[WallElement],
    wall_length_m: float,
    u_values_w_per_m2k: dict[WallElementType, float],
    depth_m: float,
) -> float:
    opening_length_m = sum(el.length_m for el in elements)
    opening_ua_w_per_k = sum(
        el.length_m * depth_m * u_values_w_per_m2k[el.type] for el in elements
    )
    plain_wall_length_m = wall_length_m - opening_length_m
    plain_wall_ua_w_per_k = plain_wall_length_m * depth_m * u_values_w_per_m2k[WallElementType.WALL]
    return opening_ua_w_per_k + plain_wall_ua_w_per_k


def suggested_heater_power_w(
    room: Room,
    climate: ClimatePreset,
    thermostat: ThermostatSettings,
    u_values_w_per_m2k: dict[WallElementType, float] = DEFAULT_U_VALUES_W_PER_M2K,
    depth_m: float = 2.5,
    safety_factor: float = 1.3,
) -> float:
    """Size a heater from the room's own physics instead of a flat guess: the
    room's total steady-state loss coefficient (UA, summed the same way the FVM
    boundary faces are -- see geometry.build_room_mesh) times the worst-case
    (coldest-hour) indoor/outdoor delta-T, times a safety margin for recovering
    from the night setback before the next day-target deadline."""
    ua_w_per_k = (
        _side_ua_w_per_k(room.walls["north"], room.width_m, u_values_w_per_m2k, depth_m)
        + _side_ua_w_per_k(room.walls["south"], room.width_m, u_values_w_per_m2k, depth_m)
        + _side_ua_w_per_k(room.walls["east"], room.height_m, u_values_w_per_m2k, depth_m)
        + _side_ua_w_per_k(room.walls["west"], room.height_m, u_values_w_per_m2k, depth_m)
    )
    coldest_outdoor_c = climate.mean_outdoor_temp_c - climate.diurnal_amplitude_c / 2.0
    worst_case_delta_t_c = thermostat.day_target_c - coldest_outdoor_c
    return ua_w_per_k * worst_case_delta_t_c * safety_factor
