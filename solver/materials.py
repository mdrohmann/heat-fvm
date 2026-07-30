"""Default physical parameters: U-values, air properties, climate presets, setpoints."""

from __future__ import annotations

import math
from dataclasses import dataclass

from solver.geometry import WallElementType

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
    hysteresis_c: float = 0.5

    def target_temp_c(self, hour: float) -> float:
        h = hour % 24.0
        is_day = self.day_start_hour <= h < self.night_start_hour
        return self.day_target_c if is_day else self.night_target_c


DEFAULT_THERMOSTAT = ThermostatSettings()
