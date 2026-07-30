import type { ClimatePreset, HeatSource, Room, SimulationRequest, ThermostatSettings } from "./types";

// Mirrors solver/materials.py CLIMATE_PRESETS -- keep in sync.
export const CLIMATE_PRESETS: ClimatePreset[] = [
  {
    id: "temperate_winter",
    label: "Temperate winter (e.g. Berlin, Jan)",
    meanOutdoorTempC: 2.0,
    diurnalAmplitudeC: 5.0,
    peakHour: 15,
  },
  {
    id: "continental_winter",
    label: "Continental winter (e.g. Chicago, Jan)",
    meanOutdoorTempC: -6.0,
    diurnalAmplitudeC: 8.0,
    peakHour: 15,
  },
  {
    id: "mild_spring",
    label: "Mild spring (e.g. Berlin, Apr)",
    meanOutdoorTempC: 10.0,
    diurnalAmplitudeC: 6.0,
    peakHour: 15,
  },
  {
    id: "hot_summer",
    label: "Hot summer (e.g. Phoenix, Jul)",
    meanOutdoorTempC: 33.0,
    diurnalAmplitudeC: 10.0,
    peakHour: 15,
  },
];

// Mirrors solver/materials.py ThermostatSettings defaults.
export const DEFAULT_THERMOSTAT: ThermostatSettings = {
  dayTargetC: 20.5,
  nightTargetC: 17.0,
  dayStartHour: 6,
  nightStartHour: 22,
};

export const DEFAULT_ROOM: Room = {
  widthM: 4.0,
  heightM: 3.0,
  walls: {
    north: [],
    east: [{ type: "window", offsetM: 0.9, lengthM: 1.2 }],
    south: [{ type: "door", offsetM: 1.5, lengthM: 0.9 }],
    west: [],
  },
};

// Computed via solver.materials.suggested_heater_power_w(DEFAULT_ROOM, CLIMATE_PRESETS[0],
// DEFAULT_THERMOSTAT) -- sized from the room's own UA and worst-case delta-T rather than a
// flat guess. A flat 1500W default massively overshot the day target with bang-bang control
// (see solver/tests/test_materials.py::test_suggested_heater_power_for_default_demo_room_is_realistic
// for the regression pin on this number staying in a sane range).
export const DEFAULT_HEAT_SOURCE: HeatSource = {
  xM: 0.4,
  yM: 1.5,
  maxPowerW: 473,
};

export function defaultSimulationRequest(): SimulationRequest {
  return {
    room: DEFAULT_ROOM,
    heatSource: DEFAULT_HEAT_SOURCE,
    climate: CLIMATE_PRESETS[0],
    thermostat: DEFAULT_THERMOSTAT,
  };
}
