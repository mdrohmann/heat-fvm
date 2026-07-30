"""Vercel Python Function: thin HTTP adapter over the `solver` package.

Keep this file free of physics/numerics — it only translates the HTTP request into
calls against `solver`, so `solver` stays independently importable and testable.
Request/response shapes here must stay in sync with src/lib/types.ts.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler
from typing import Any

from solver.fvm import simulate_representative_day
from solver.geometry import HeatSource, Room, WallElement, WallElementType
from solver.materials import ClimatePreset, ThermostatSettings
from solver.mor import estimate_monthly_energy_from_day

DEFAULT_NX = 20
DEFAULT_NY = 15

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


def _parse_climate(payload: dict[str, Any]) -> ClimatePreset:
    return ClimatePreset(
        id=payload["id"],
        label=payload["label"],
        mean_outdoor_temp_c=float(payload["meanOutdoorTempC"]),
        diurnal_amplitude_c=float(payload["diurnalAmplitudeC"]),
        peak_hour=float(payload.get("peakHour", 15.0)),
    )


def _parse_thermostat(payload: dict[str, Any]) -> ThermostatSettings:
    return ThermostatSettings(
        day_target_c=float(payload["dayTargetC"]),
        night_target_c=float(payload["nightTargetC"]),
        day_start_hour=float(payload["dayStartHour"]),
        night_start_hour=float(payload["nightStartHour"]),
        hysteresis_c=float(payload.get("hysteresisC", 0.5)),
    )


def simulate_from_request(
    payload: dict[str, Any], nx: int = DEFAULT_NX, ny: int = DEFAULT_NY
) -> dict[str, Any]:
    """Translate a SimulationRequest JSON payload into solver calls and back into
    a SimulationResult JSON payload (see src/lib/types.ts for both shapes)."""
    room = _parse_room(payload["room"])
    heat_source = _parse_heat_source(payload["heatSource"])
    climate = _parse_climate(payload["climate"])
    thermostat = _parse_thermostat(payload["thermostat"])

    representative = simulate_representative_day(room, heat_source, climate, thermostat, nx=nx, ny=ny)
    monthly_energy_kwh = estimate_monthly_energy_from_day(
        representative, room, heat_source, climate, thermostat
    )

    frames = [
        {
            "hour": float(representative.hours[step]),
            "temperatureC": representative.temperature_fields_c[step].tolist(),
            "heaterPowerW": float(representative.heater_power_w[step]),
        }
        for step in range(len(representative.hours))
    ]

    nx_actual, ny_actual = representative.room_mesh.mesh.shape
    return {
        "grid": {"nx": nx_actual, "ny": ny_actual},
        "representativeDay": frames,
        "monthlyEnergyKWh": monthly_energy_kwh,
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
