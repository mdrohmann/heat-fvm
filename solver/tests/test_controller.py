from solver.controller import ThermostatState, bang_bang_power_w
from solver.materials import ThermostatSettings


def test_turns_on_below_lower_bound():
    settings = ThermostatSettings(day_target_c=20.0, hysteresis_c=1.0)
    state = ThermostatState(heater_on=False)
    power = bang_bang_power_w(19.0, hour=12.0, settings=settings, max_power_w=1000.0, state=state)
    assert power == 1000.0
    assert state.heater_on is True


def test_turns_off_above_upper_bound():
    settings = ThermostatSettings(day_target_c=20.0, hysteresis_c=1.0)
    state = ThermostatState(heater_on=True)
    power = bang_bang_power_w(21.0, hour=12.0, settings=settings, max_power_w=1000.0, state=state)
    assert power == 0.0
    assert state.heater_on is False


def test_holds_previous_state_inside_deadband():
    settings = ThermostatSettings(day_target_c=20.0, hysteresis_c=1.0)

    state_on = ThermostatState(heater_on=True)
    assert bang_bang_power_w(20.0, 12.0, settings, 1000.0, state_on) == 1000.0
    assert state_on.heater_on is True

    state_off = ThermostatState(heater_on=False)
    assert bang_bang_power_w(20.0, 12.0, settings, 1000.0, state_off) == 0.0
    assert state_off.heater_on is False
