import pytest

from solver.controller import ControllerState, PIControllerParams, pi_power_w
from solver.materials import ThermostatSettings


def test_saturates_to_max_power_far_below_target():
    settings = ThermostatSettings(day_target_c=20.0)
    params = PIControllerParams(proportional_band_c=2.0)
    state = ControllerState()

    # 10C below target is far outside the 2C proportional band -> full power.
    power = pi_power_w(10.0, hour=12.0, settings=settings, max_power_w=1000.0, dt_s=60.0, state=state, params=params)
    assert power == 1000.0


def test_saturates_to_zero_above_target():
    settings = ThermostatSettings(day_target_c=20.0)
    state = ControllerState()

    power = pi_power_w(25.0, hour=12.0, settings=settings, max_power_w=1000.0, dt_s=60.0, state=state)
    assert power == 0.0


def test_throttles_proportionally_within_the_band_before_any_integral_accumulates():
    settings = ThermostatSettings(day_target_c=20.0)
    params = PIControllerParams(proportional_band_c=2.0, integral_time_s=1_000_000.0)
    state = ControllerState()

    # 1C error, half the 2C proportional band -> roughly half power on the very
    # first call (integral term negligible given the huge integral_time_s).
    power = pi_power_w(19.0, hour=12.0, settings=settings, max_power_w=1000.0, dt_s=60.0, state=state, params=params)
    assert power == pytest.approx(500.0, rel=0.05)


def test_anti_windup_freezes_integral_while_saturated():
    settings = ThermostatSettings(day_target_c=20.0)
    state = ControllerState()

    # Deeply saturated (far below target): repeated calls should NOT accumulate
    # integral, since the output is clamped at max_power_w regardless.
    for _ in range(20):
        power = pi_power_w(0.0, hour=12.0, settings=settings, max_power_w=1000.0, dt_s=300.0, state=state)
        assert power == 1000.0
    assert state.integral_c_s == 0.0


def test_integral_term_eliminates_steady_state_error_over_time():
    # A small, constant positive error should never saturate but should still
    # accumulate integral action, pushing power up over repeated calls.
    settings = ThermostatSettings(day_target_c=20.0)
    params = PIControllerParams(proportional_band_c=2.0, integral_time_s=600.0)
    state = ControllerState()

    first = pi_power_w(19.9, hour=12.0, settings=settings, max_power_w=1000.0, dt_s=60.0, state=state, params=params)
    for _ in range(10):
        latest = pi_power_w(
            19.9, hour=12.0, settings=settings, max_power_w=1000.0, dt_s=60.0, state=state, params=params
        )
    assert latest > first
