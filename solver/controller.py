"""Thermostat control logic and energy accounting."""

from __future__ import annotations

from dataclasses import dataclass

from solver.materials import ThermostatSettings


@dataclass
class ThermostatState:
    heater_on: bool = False


def bang_bang_power_w(
    room_avg_temp_c: float,
    hour: float,
    settings: ThermostatSettings,
    max_power_w: float,
    state: ThermostatState,
) -> float:
    """Hysteresis (bang-bang) thermostat: switch on below target - hysteresis/2,
    switch off above target + hysteresis/2, hold the previous state in between."""
    target_c = settings.target_temp_c(hour)
    lower_c = target_c - settings.hysteresis_c / 2.0
    upper_c = target_c + settings.hysteresis_c / 2.0

    if room_avg_temp_c < lower_c:
        state.heater_on = True
    elif room_avg_temp_c > upper_c:
        state.heater_on = False

    return max_power_w if state.heater_on else 0.0
