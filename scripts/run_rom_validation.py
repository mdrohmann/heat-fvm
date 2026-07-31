"""Measure the reduced model's accuracy against the full solver and bake the result.

Run offline and commit the output; the web request never pays for this. Full-FVM days
are the expensive part (~1s each at the validation grid), and a full sweep across four
climates takes a couple of minutes.

The numbers this produces characterise the *reference room* under each climate. They
describe the method's validity envelope, not a live check of whatever geometry a user
has dialled in -- which is exactly why they belong in a study rather than in the
request path.

Usage:  .venv/bin/python scripts/run_rom_validation.py
"""

from __future__ import annotations

import json
from pathlib import Path

from solver.climate import climate_locations, get_climate
from solver.geometry import HeatSource, Room, WallElement, WallElementType
from solver.materials import DEFAULT_THERMOSTAT, suggested_heater_power_w
from solver.validation import validate_across_days

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "solver" / "data" / "rom_validation.json"

# Mid-month sample days (0-indexed day-of-year), one per month.
SAMPLE_DAYS = [14, 45, 73, 104, 134, 165, 195, 226, 257, 287, 318, 348]

REFERENCE_ROOM = Room(
    width_m=4.0,
    height_m=3.0,
    walls={
        "north": [],
        "east": [WallElement(WallElementType.WINDOW, offset_m=0.9, length_m=1.2)],
        "south": [WallElement(WallElementType.DOOR, offset_m=1.5, length_m=0.9)],
        "west": [],
    },
)


def main() -> None:
    results = {}
    for location_id in climate_locations():
        climate = get_climate(location_id)
        heat_source = HeatSource(
            x_m=0.4,
            y_m=1.5,
            max_power_w=suggested_heater_power_w(REFERENCE_ROOM, climate, DEFAULT_THERMOSTAT),
        )
        linearization_day = climate.linearization_day_of_year(DEFAULT_THERMOSTAT.day_target_c)

        print(f"validating {climate.label} (linearized on day {linearization_day}) ...", flush=True)
        report = validate_across_days(
            REFERENCE_ROOM,
            heat_source,
            climate,
            DEFAULT_THERMOSTAT,
            sample_days=SAMPLE_DAYS,
            linearization_day_of_year=linearization_day,
        )
        print(
            f"  total-energy error {report.annual_energy_relative_error * 100:+.1f}% | "
            f"worst significant day {report.max_abs_relative_error * 100:.1f}% | "
            f"worst absolute {report.max_abs_error_kwh:.2f} kWh"
        )

        results[location_id] = {
            "label": climate.label,
            "linearization_day_of_year": linearization_day,
            "linearization_mean_temp_c": climate.mean_temp_c[linearization_day],
            "total_energy_relative_error": report.annual_energy_relative_error,
            "max_abs_relative_error": report.max_abs_relative_error,
            "mean_abs_relative_error": report.mean_abs_relative_error,
            "max_abs_error_kwh": report.max_abs_error_kwh,
            "points": [
                {
                    "dayOfYear": p.day_of_year,
                    "meanOutdoorTempC": round(p.mean_outdoor_temp_c, 2),
                    "fullEnergyKWh": round(p.full_energy_kwh, 4),
                    "reducedEnergyKWh": round(p.reduced_energy_kwh, 4),
                    "relativeError": round(p.relative_error, 4),
                }
                for p in report.points
            ],
        }

    payload = {
        "_meta": {
            "description": (
                "Reduced-order model accuracy against the full nonlinear FVM solver, "
                "measured on the reference room (4.0 x 3.0 m, one window, one door) for "
                "each climate. Each sample runs both models over the same day from the "
                "same initial condition and compares heater energy."
            ),
            "reference_room": {"width_m": REFERENCE_ROOM.width_m, "height_m": REFERENCE_ROOM.height_m},
            "sample_days": SAMPLE_DAYS,
            "generated_by": "scripts/run_rom_validation.py",
        },
        "locations": results,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=1) + "\n")
    print(f"wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
