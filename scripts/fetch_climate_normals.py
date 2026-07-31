"""Fetch daily climate normals from ERA5 and bake them into solver/data/climate_normals.json.

This is an offline, run-once-and-commit script -- the simulation itself never hits the
network. Re-run it to refresh the dataset (e.g. to extend the period by a year).

Data source: ERA5 reanalysis, served by the Open-Meteo Historical Weather API.
  https://open-meteo.com/en/docs/historical-weather-api
ERA5 is produced by the Copernicus Climate Change Service (C3S) and covers 1940-present,
so the normals here are an ~86-year climatology -- not the WMO-standard 30-year normal,
and not a literal 100-year record (which exists only for a handful of long-record
stations).

Method: for each calendar day, average the daily mean temperature and the daily
(max - min) range across all available years, then apply a 15-day circular moving
average to suppress sampling noise. Feb 29 is excluded so every year is 365 days.

Usage:  .venv/bin/python scripts/fetch_climate_normals.py
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

import numpy as np

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
START_DATE = "1940-01-01"
END_DATE = "2025-12-31"
SMOOTHING_WINDOW_DAYS = 15

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "solver" / "data" / "climate_normals.json"

# Deliberately spans a wide climatic range so the seasonal/heating-demand contrast is
# visible: maritime-temperate, cold-continental, hot-desert, and subarctic.
LOCATIONS = [
    {"id": "berlin", "label": "Berlin, Germany", "latitude": 52.52, "longitude": 13.41, "timezone": "Europe/Berlin"},
    {"id": "chicago", "label": "Chicago, USA", "latitude": 41.88, "longitude": -87.63, "timezone": "America/Chicago"},
    {"id": "phoenix", "label": "Phoenix, USA", "latitude": 33.45, "longitude": -112.07, "timezone": "America/Phoenix"},
    {"id": "reykjavik", "label": "Reykjavik, Iceland", "latitude": 64.15, "longitude": -21.94, "timezone": "Atlantic/Reykjavik"},
]


def fetch_daily_record(location: dict, max_attempts: int = 6) -> dict:
    """Fetch one location's full daily record. An 86-year request is heavy and the
    free API rate-limits it, so back off and retry on 429 rather than failing."""
    query = urllib.parse.urlencode(
        {
            "latitude": location["latitude"],
            "longitude": location["longitude"],
            "start_date": START_DATE,
            "end_date": END_DATE,
            "daily": "temperature_2m_mean,temperature_2m_max,temperature_2m_min",
            "timezone": location["timezone"],
        }
    )
    url = f"{ARCHIVE_URL}?{query}"

    for attempt in range(max_attempts):
        try:
            with urllib.request.urlopen(url, timeout=240) as response:
                return json.load(response)["daily"]
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt == max_attempts - 1:
                raise
            backoff_s = 60 * (attempt + 1)
            print(f"  rate limited; retrying in {backoff_s}s", flush=True)
            time.sleep(backoff_s)

    raise RuntimeError("unreachable")


def _circular_moving_average(values: np.ndarray, window: int) -> np.ndarray:
    """Smooth a day-of-year series, wrapping Dec->Jan so the seasonal cycle stays
    continuous across the year boundary."""
    pad = window // 2
    padded = np.concatenate([values[-pad:], values, values[:pad]])
    kernel = np.ones(window) / window
    return np.convolve(padded, kernel, mode="same")[pad:-pad]


def build_normals(daily: dict) -> tuple[list[float], list[float], int]:
    mean_samples: dict[tuple[int, int], list[float]] = defaultdict(list)
    amplitude_samples: dict[tuple[int, int], list[float]] = defaultdict(list)

    for date, mean_c, max_c, min_c in zip(
        daily["time"],
        daily["temperature_2m_mean"],
        daily["temperature_2m_max"],
        daily["temperature_2m_min"],
    ):
        if mean_c is None or max_c is None or min_c is None:
            continue  # ERA5's back-extension starts mid-day on 1940-01-01
        month, day = int(date[5:7]), int(date[8:10])
        if (month, day) == (2, 29):
            continue
        mean_samples[(month, day)].append(mean_c)
        amplitude_samples[(month, day)].append(max_c - min_c)

    calendar_days = sorted(mean_samples)
    if len(calendar_days) != 365:
        raise ValueError(f"expected 365 calendar days, got {len(calendar_days)}")

    mean_c = _circular_moving_average(
        np.array([np.mean(mean_samples[d]) for d in calendar_days]), SMOOTHING_WINDOW_DAYS
    )
    amplitude_c = _circular_moving_average(
        np.array([np.mean(amplitude_samples[d]) for d in calendar_days]), SMOOTHING_WINDOW_DAYS
    )
    fewest_samples = min(len(mean_samples[d]) for d in calendar_days)

    return [round(v, 2) for v in mean_c], [round(v, 2) for v in amplitude_c], fewest_samples


def main() -> None:
    locations_out = {}
    for location in LOCATIONS:
        print(f"fetching {location['label']} ...", flush=True)
        daily = fetch_daily_record(location)
        mean_c, amplitude_c, fewest_samples = build_normals(daily)
        print(
            f"  {len(daily['time'])} days -> 365 normals "
            f"(>= {fewest_samples} years/day, {min(mean_c):.1f}C .. {max(mean_c):.1f}C)"
        )
        locations_out[location["id"]] = {
            "label": location["label"],
            "latitude": location["latitude"],
            "longitude": location["longitude"],
            "timezone": location["timezone"],
            "mean_temp_c": mean_c,
            "diurnal_amplitude_c": amplitude_c,
        }
        time.sleep(1)  # be polite to a free public API

    payload = {
        "_meta": {
            "source": "ERA5 reanalysis (Copernicus C3S), retrieved via the Open-Meteo Historical Weather API",
            "source_url": "https://open-meteo.com/en/docs/historical-weather-api",
            "attribution": "Open-Meteo data is licensed CC-BY-4.0; ERA5 is produced by the Copernicus Climate Change Service.",
            "period": f"{START_DATE} to {END_DATE}",
            "method": (
                "Per-calendar-day average of daily mean temperature and daily (max-min) range "
                f"across all years, then a {SMOOTHING_WINDOW_DAYS}-day circular moving average. "
                "Feb 29 excluded, so a year is 365 days."
            ),
            "generated_by": "scripts/fetch_climate_normals.py",
        },
        "locations": locations_out,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=1) + "\n")
    print(f"wrote {OUTPUT_PATH} ({OUTPUT_PATH.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
