"""Default physical parameters: U-values, air properties, climate presets, setpoints."""

from __future__ import annotations

from dataclasses import dataclass

from solver.climate import ClimateLocation
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


def room_ua_w_per_k(
    room: Room,
    u_values_w_per_m2k: dict[WallElementType, float] = DEFAULT_U_VALUES_W_PER_M2K,
    depth_m: float = 2.5,
) -> float:
    """The room's total steady-state heat-loss coefficient, summed the same way the
    FVM boundary faces are -- see geometry.build_room_mesh."""
    return (
        _side_ua_w_per_k(room.walls["north"], room.width_m, u_values_w_per_m2k, depth_m)
        + _side_ua_w_per_k(room.walls["south"], room.width_m, u_values_w_per_m2k, depth_m)
        + _side_ua_w_per_k(room.walls["east"], room.height_m, u_values_w_per_m2k, depth_m)
        + _side_ua_w_per_k(room.walls["west"], room.height_m, u_values_w_per_m2k, depth_m)
    )


def suggested_heater_power_w(
    room: Room,
    climate: ClimateLocation,
    thermostat: ThermostatSettings,
    u_values_w_per_m2k: dict[WallElementType, float] = DEFAULT_U_VALUES_W_PER_M2K,
    depth_m: float = 2.5,
    safety_factor: float = 1.3,
) -> float:
    """Size a heater from the room's own physics instead of a flat guess: the room's
    UA times the design (coldest normal condition of the year) indoor/outdoor
    delta-T, times a safety margin for recovering from the night setback before the
    next day-target deadline."""
    ua_w_per_k = room_ua_w_per_k(room, u_values_w_per_m2k, depth_m)
    worst_case_delta_t_c = thermostat.day_target_c - climate.design_outdoor_temp_c
    return ua_w_per_k * worst_case_delta_t_c * safety_factor
