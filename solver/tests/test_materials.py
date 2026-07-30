import pytest

from solver.materials import CLIMATE_PRESETS, DEFAULT_THERMOSTAT, ThermostatSettings


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
