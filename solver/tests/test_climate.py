import pytest

from solver.climate import (
    DAYS_PER_YEAR,
    DEFAULT_CLIMATE_ID,
    climate_locations,
    dataset_metadata,
    get_climate,
    month_day_range,
    month_of_day,
)


def test_all_locations_have_full_year_climatologies():
    locations = climate_locations()
    assert locations, "expected at least one baked climate location"
    for location in locations.values():
        assert len(location.mean_temp_c) == DAYS_PER_YEAR
        assert len(location.diurnal_amplitude_c) == DAYS_PER_YEAR
        assert all(amplitude > 0 for amplitude in location.diurnal_amplitude_c)


def test_default_climate_is_available():
    assert get_climate(DEFAULT_CLIMATE_ID)


def test_unknown_location_raises():
    with pytest.raises(ValueError, match="unknown climate location"):
        get_climate("atlantis")


def test_northern_hemisphere_locations_are_colder_in_january_than_july():
    # All four baked locations are northern-hemisphere, so this is a real check that
    # the day-of-year indexing is not off by a season.
    for location in climate_locations().values():
        january = location.mean_temp_c[14]
        july = location.mean_temp_c[195]
        assert january < july, f"{location.label}: Jan {january} not below Jul {july}"


def test_outdoor_temp_varies_within_a_day_and_across_the_year():
    location = get_climate("berlin")
    jan_day_hours = [14 * 24.0 + h for h in range(24)]
    jul_day_hours = [195 * 24.0 + h for h in range(24)]

    jan_temps = [location.outdoor_temp_c(h) for h in jan_day_hours]
    jul_temps = [location.outdoor_temp_c(h) for h in jul_day_hours]

    assert max(jan_temps) > min(jan_temps), "expected a diurnal swing"
    assert sum(jul_temps) / 24 > sum(jan_temps) / 24, "expected summer warmer than winter"


def test_outdoor_temp_is_continuous_across_midnight_and_year_end():
    location = get_climate("berlin")
    # Crossing into a new day, and wrapping Dec 31 -> Jan 1, must not step.
    for boundary_hours in (50 * 24.0, DAYS_PER_YEAR * 24.0):
        before = location.outdoor_temp_c(boundary_hours - 1e-4)
        after = location.outdoor_temp_c(boundary_hours + 1e-4)
        assert abs(after - before) < 0.01


def test_month_helpers_tile_the_year_exactly():
    covered = 0
    for month_index in range(12):
        start, end = month_day_range(month_index)
        assert start == covered
        covered = end
        assert month_of_day(start) == month_index
        assert month_of_day(end - 1) == month_index
    assert covered == DAYS_PER_YEAR


def test_design_temperature_is_below_annual_mean():
    for location in climate_locations().values():
        assert location.design_outdoor_temp_c < location.annual_mean_temp_c


def test_linearization_day_is_a_day_that_actually_needs_heating():
    # Regression test for the Phoenix failure: anchoring on the plain annual mean put
    # the linearisation point above the thermostat target, where no heating occurs,
    # and produced a -54% annual energy error.
    base_temp_c = 20.5
    for location in climate_locations().values():
        day = location.linearization_day_of_year(base_temp_c)
        assert 0 <= day < DAYS_PER_YEAR
        assert location.mean_temp_c[day] < base_temp_c, (
            f"{location.label}: linearisation day is warmer than the heating base temperature"
        )


def test_dataset_metadata_records_provenance():
    meta = dataset_metadata()
    for key in ("source", "period", "method"):
        assert meta.get(key), f"climate dataset metadata missing {key!r}"
