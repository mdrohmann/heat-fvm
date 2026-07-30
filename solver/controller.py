"""Thermostat control logic and energy accounting.

A bang-bang (hysteresis) controller only samples the room temperature once per
`dt_s`; if the heater is strong enough to move the room several degrees within a
single step (as a realistically-sized heater is, relative to a room's air
thermal mass), the room overshoots the deadband by a lot before the controller
next gets a chance to react. A proportional-integral (PI) controller instead
throttles heater power continuously as the room approaches target, which is
what actually bounds the overshoot -- see the project's CLAUDE.md-adjacent
design discussion for the numbers behind this.
"""

from __future__ import annotations

from dataclasses import dataclass

from solver.materials import ThermostatSettings


@dataclass(frozen=True)
class PIControllerParams:
    """Gains are expressed in physically legible units rather than raw W/K, W/K/s
    numbers: `proportional_band_c` is "how many degrees of error saturates the
    heater to full power", `integral_time_s` is "how long the integral term
    takes to fully cancel a steady-state offset of that same size"."""

    proportional_band_c: float = 2.0
    integral_time_s: float = 1800.0


@dataclass
class ControllerState:
    integral_c_s: float = 0.0


def pi_power_w(
    room_avg_temp_c: float,
    hour: float,
    settings: ThermostatSettings,
    max_power_w: float,
    dt_s: float,
    state: ControllerState,
    params: PIControllerParams = PIControllerParams(),
) -> float:
    """Proportional-integral thermostat, clamped to [0, max_power_w] with
    anti-windup (the integral term only accumulates while the output isn't
    saturated, so it can't wind up during a long cold start and then overshoot
    once it finally has authority to turn off)."""
    target_c = settings.target_temp_c(hour)
    error_c = target_c - room_avg_temp_c

    kp_w_per_c = max_power_w / params.proportional_band_c
    ki_w_per_c_s = kp_w_per_c / params.integral_time_s

    candidate_integral_c_s = state.integral_c_s + error_c * dt_s
    unclamped_w = kp_w_per_c * error_c + ki_w_per_c_s * candidate_integral_c_s
    clamped_w = min(max(unclamped_w, 0.0), max_power_w)

    if clamped_w == unclamped_w:
        state.integral_c_s = candidate_integral_c_s

    return clamped_w
