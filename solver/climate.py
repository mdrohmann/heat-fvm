"""Day-of-year climate model backed by baked ERA5 daily normals.

Each location carries a 365-entry climatology (daily mean temperature and daily
diurnal amplitude) rather than a single winter/summer scalar, so outdoor conditions
genuinely change from one simulated day to the next. That is what makes a year-long
simulation worth reducing: the reduced model has to track 365 *different* days, not
replay one day 365 times.

The dataset is committed under `data/` and generated offline by
`scripts/fetch_climate_normals.py` -- the solver never touches the network.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DAYS_PER_YEAR = 365
HOURS_PER_DAY = 24.0

# The daily temperature peak sits in mid-afternoon. Pinning this to a constant is an
# approximation -- resolving the true per-location peak hour would need hourly rather
# than daily ERA5 aggregates, which is a far larger download for a second-order effect.
DEFAULT_PEAK_HOUR = 15.0

_DATA_PATH = Path(__file__).resolve().parent / "data" / "climate_normals.json"

# Calendar day counts for a non-leap year; Feb 29 is excluded from the normals so
# that every simulated year is exactly 365 days.
_MONTH_LENGTHS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


@dataclass(frozen=True)
class ClimateLocation:
    """A location's annual climatology. `mean_temp_c` and `diurnal_amplitude_c` are
    365-entry sequences indexed by day-of-year (0 = Jan 1)."""

    id: str
    label: str
    mean_temp_c: tuple[float, ...]
    diurnal_amplitude_c: tuple[float, ...]
    peak_hour: float = DEFAULT_PEAK_HOUR

    def __post_init__(self) -> None:
        if len(self.mean_temp_c) != DAYS_PER_YEAR or len(self.diurnal_amplitude_c) != DAYS_PER_YEAR:
            raise ValueError(f"climatology must have {DAYS_PER_YEAR} entries per series")

    def _interpolated_normals(self, day_position: float) -> tuple[float, float]:
        """Linearly interpolate the daily normals at a fractional day-of-year,
        wrapping Dec 31 -> Jan 1, so the forcing has no step discontinuity at
        midnight."""
        base = math.floor(day_position)
        fraction = day_position - base
        i0 = base % DAYS_PER_YEAR
        i1 = (base + 1) % DAYS_PER_YEAR
        mean_c = self.mean_temp_c[i0] * (1 - fraction) + self.mean_temp_c[i1] * fraction
        amplitude_c = (
            self.diurnal_amplitude_c[i0] * (1 - fraction) + self.diurnal_amplitude_c[i1] * fraction
        )
        return mean_c, amplitude_c

    def outdoor_temp_c(self, hours_since_year_start: float) -> float:
        """Outdoor temperature at an absolute time in the year: the day's climatological
        mean plus a diurnal sinusoid peaking at `peak_hour`."""
        day_position = hours_since_year_start / HOURS_PER_DAY
        hour_of_day = hours_since_year_start % HOURS_PER_DAY
        mean_c, amplitude_c = self._interpolated_normals(day_position)
        phase = 2 * math.pi * (hour_of_day - self.peak_hour) / HOURS_PER_DAY
        return mean_c + (amplitude_c / 2.0) * math.cos(phase)

    @property
    def annual_mean_temp_c(self) -> float:
        return sum(self.mean_temp_c) / DAYS_PER_YEAR

    @property
    def design_outdoor_temp_c(self) -> float:
        """Coldest normal condition of the year -- used to size the heater."""
        return min(
            mean_c - amplitude_c / 2.0
            for mean_c, amplitude_c in zip(self.mean_temp_c, self.diurnal_amplitude_c)
        )

    def heating_degree_days(self, base_temp_c: float) -> list[float]:
        """Per-day heating demand proxy: how far the day's mean sits below the
        temperature the room must be held at. Zero on days needing no heat."""
        return [max(0.0, base_temp_c - mean_c) for mean_c in self.mean_temp_c]

    def linearization_day_of_year(self, base_temp_c: float) -> int:
        """The day to linearize the reduced model about: the one whose climatological
        mean sits closest to the *heating-demand-weighted* mean outdoor temperature.

        Linearizing at a seasonal extreme makes the reduction accurate there and
        progressively worse everywhere else, so a mid-range anchor is better. But the
        plain annual mean is the wrong middle: in a hot climate like Phoenix it sits
        above the thermostat target, anchoring the model to conditions where no
        heating ever runs and wrecking the few days that do need heat (measured at
        -54% annual error). Weighting by heating degree-days ignores days that
        contribute no energy, which fixes that case and leaves temperate climates
        essentially unchanged.

        Deliberately independent of whichever day the user is viewing, so the annual
        energy number doesn't drift when they change the heatmap's month.
        """
        degree_days = self.heating_degree_days(base_temp_c)
        total_degree_days = sum(degree_days)

        if total_degree_days <= 1e-9:
            # Nowhere near needing heat all year; anchor on the coldest day so the
            # reduction is at least calibrated for whatever little demand exists.
            return min(range(DAYS_PER_YEAR), key=lambda d: self.mean_temp_c[d])

        weighted_mean_c = (
            sum(w * t for w, t in zip(degree_days, self.mean_temp_c)) / total_degree_days
        )
        # Restrict to days that actually demand heat, so the anchor is a real
        # heating-season day rather than a mild day that merely has a similar mean.
        heating_days = [d for d in range(DAYS_PER_YEAR) if degree_days[d] > 0.0]
        return min(heating_days, key=lambda d: abs(self.mean_temp_c[d] - weighted_mean_c))


def month_day_range(month_index: int) -> tuple[int, int]:
    """[start, end) day-of-year indices for a month (0 = January)."""
    if not 0 <= month_index < 12:
        raise ValueError(f"month_index must be in 0..11, got {month_index}")
    start = sum(_MONTH_LENGTHS[:month_index])
    return start, start + _MONTH_LENGTHS[month_index]


def month_of_day(day_index: int) -> int:
    """Month index (0 = January) containing a given day-of-year."""
    remaining = day_index % DAYS_PER_YEAR
    for month_index, length in enumerate(_MONTH_LENGTHS):
        if remaining < length:
            return month_index
        remaining -= length
    raise AssertionError("unreachable")


@lru_cache(maxsize=1)
def _load_dataset() -> dict:
    return json.loads(_DATA_PATH.read_text())


@lru_cache(maxsize=1)
def climate_locations() -> dict[str, ClimateLocation]:
    dataset = _load_dataset()
    return {
        location_id: ClimateLocation(
            id=location_id,
            label=entry["label"],
            mean_temp_c=tuple(entry["mean_temp_c"]),
            diurnal_amplitude_c=tuple(entry["diurnal_amplitude_c"]),
        )
        for location_id, entry in dataset["locations"].items()
    }


def get_climate(location_id: str) -> ClimateLocation:
    locations = climate_locations()
    if location_id not in locations:
        raise ValueError(f"unknown climate location {location_id!r}; have {sorted(locations)}")
    return locations[location_id]


def dataset_metadata() -> dict:
    """Provenance for the baked normals, surfaced in the UI so the data source and
    its limitations travel with the numbers."""
    return _load_dataset()["_meta"]


DEFAULT_CLIMATE_ID = "berlin"
