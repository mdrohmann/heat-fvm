"""Vercel Python Function: thin HTTP adapter over the `solver` package.

Keep this file free of physics/numerics — it only translates the HTTP request into
calls against `solver`, so `solver` stays independently importable and testable.
Request/response shapes here must stay in sync with src/lib/types.ts.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler
from typing import Any

from solver.climate import (
    DEFAULT_CLIMATE_ID,
    MONTH_NAMES,
    ClimateLocation,
    climate_locations,
    dataset_metadata,
    get_climate,
    month_day_range,
)
from solver.fvm import simulate_representative_day
from solver.geometry import HeatSource, Room, WallElement, WallElementType
from solver.materials import ThermostatSettings
from solver.mor import estimate_annual_energy
from solver.validation import load_baked_validation

# The visualisation solve is fine-grained because its temperature field is what the
# user actually looks at. The linearisation solve only has to produce a smooth
# velocity pattern, so it runs on a coarser mesh and costs a fraction as much.
VIEW_NX, VIEW_NY = 20, 15
LINEARIZATION_NX, LINEARIZATION_NY = 12, 9

# 288 steps/day at dt=300s is far more temporal detail than a scrubber needs; sending
# every third frame keeps 15-minute resolution at a third of the payload.
FRAME_STRIDE = 3

_WALL_SIDES = ("north", "east", "south", "west")


def _parse_wall_elements(entries: list[dict[str, Any]]) -> list[WallElement]:
    # "wall" entries represent plain background wall, which is implicit in the
    # solver's Room model (see geometry.py) -- only openings are passed through.
    return [
        WallElement(
            type=WallElementType(entry["type"]),
            offset_m=float(entry["offsetM"]),
            length_m=float(entry["lengthM"]),
        )
        for entry in entries
        if entry["type"] != "wall"
    ]


def _parse_room(payload: dict[str, Any]) -> Room:
    walls = payload["walls"]
    return Room(
        width_m=float(payload["widthM"]),
        height_m=float(payload["heightM"]),
        walls={side: _parse_wall_elements(walls.get(side, [])) for side in _WALL_SIDES},
    )


def _parse_heat_source(payload: dict[str, Any]) -> HeatSource:
    return HeatSource(
        x_m=float(payload["xM"]),
        y_m=float(payload["yM"]),
        max_power_w=float(payload["maxPowerW"]),
    )


def _parse_thermostat(payload: dict[str, Any]) -> ThermostatSettings:
    return ThermostatSettings(
        day_target_c=float(payload["dayTargetC"]),
        night_target_c=float(payload["nightTargetC"]),
        day_start_hour=float(payload["dayStartHour"]),
        night_start_hour=float(payload["nightStartHour"]),
    )


def _mid_month_day(month_index: int) -> int:
    start, end = month_day_range(month_index)
    return (start + end) // 2


def _climate_summary(climate: ClimateLocation, linearization_day: int) -> dict[str, Any]:
    return {
        "id": climate.id,
        "label": climate.label,
        "annualMeanTempC": round(climate.annual_mean_temp_c, 2),
        "designOutdoorTempC": round(climate.design_outdoor_temp_c, 2),
        "linearizationDayOfYear": linearization_day,
        "linearizationMeanTempC": round(climate.mean_temp_c[linearization_day], 2),
    }


def available_climates() -> list[dict[str, str]]:
    return [
        {"id": location.id, "label": location.label}
        for location in sorted(climate_locations().values(), key=lambda c: c.label)
    ]


def simulate_from_request(
    payload: dict[str, Any],
    view_nx: int = VIEW_NX,
    view_ny: int = VIEW_NY,
    linearization_nx: int = LINEARIZATION_NX,
    linearization_ny: int = LINEARIZATION_NY,
) -> dict[str, Any]:
    """Translate a SimulationRequest JSON payload into solver calls and back into
    a SimulationResult JSON payload (see src/lib/types.ts for both shapes)."""
    room = _parse_room(payload["room"])
    heat_source = _parse_heat_source(payload["heatSource"])
    thermostat = _parse_thermostat(payload["thermostat"])
    climate = get_climate(payload.get("climateId", DEFAULT_CLIMATE_ID))

    month_index = int(payload.get("viewMonthIndex", 0))
    if not 0 <= month_index < 12:
        raise ValueError(f"viewMonthIndex must be in 0..11, got {month_index}")
    view_day = _mid_month_day(month_index)

    # The day the reduction is linearised about is a property of the climate, not of
    # whatever month the user happens to be looking at -- otherwise the annual energy
    # number would drift as they browse. See ClimateLocation.linearization_day_of_year.
    linearization_day = climate.linearization_day_of_year(thermostat.day_target_c)

    view_solve = simulate_representative_day(
        room, heat_source, climate, thermostat,
        day_of_year=view_day, nx=view_nx, ny=view_ny,
    )
    linearization_solve = simulate_representative_day(
        room, heat_source, climate, thermostat,
        day_of_year=linearization_day, nx=linearization_nx, ny=linearization_ny,
    )
    annual = estimate_annual_energy(
        linearization_solve, room, heat_source, climate, thermostat
    )

    frames = [
        {
            "hour": float(view_solve.hours[step]),
            "temperatureC": [round(t, 3) for t in view_solve.temperature_fields_c[step].tolist()],
            "heaterPowerW": round(float(view_solve.heater_power_w[step]), 2),
        }
        for step in range(0, len(view_solve.hours), FRAME_STRIDE)
    ]

    nx_actual, ny_actual = view_solve.room_mesh.mesh.shape
    baked_validation = load_baked_validation()["locations"].get(climate.id)

    return {
        "grid": {"nx": nx_actual, "ny": ny_actual},
        "viewDay": {
            "dayOfYear": view_day,
            "monthIndex": month_index,
            "monthName": MONTH_NAMES[month_index],
            "meanOutdoorTempC": round(climate.mean_temp_c[view_day], 2),
            "frames": frames,
        },
        "annual": {
            "totalKWh": round(annual.total_kwh, 1),
            "monthlyKWh": [round(v, 1) for v in annual.monthly_kwh],
            "dailyKWh": [round(v, 3) for v in annual.daily_kwh],
            "dailyMeanIndoorC": [round(v, 2) for v in annual.daily_mean_indoor_c],
            "dailyMeanOutdoorC": [round(v, 2) for v in annual.daily_mean_outdoor_c],
        },
        "climate": _climate_summary(climate, linearization_day),
        "validation": baked_validation,
        "climateDataMeta": dataset_metadata(),
    }


class handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        try:
            payload = json.loads(body)
            result = simulate_from_request(payload)
        except Exception as exc:  # noqa: BLE001 -- any failure becomes a 400, not a crash
            self._send_json({"error": str(exc)}, status=400)
            return

        self._send_json(result, status=200)

    def _send_json(self, data: dict[str, Any], status: int) -> None:
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)
