import type { ClimateOption, HeatSource, Room, ThermostatSettings } from "./types";

// Mirrors the locations baked into solver/data/climate_normals.json by
// scripts/fetch_climate_normals.py -- keep in sync.
export const CLIMATE_OPTIONS: ClimateOption[] = [
  { id: "berlin", label: "Berlin, Germany" },
  { id: "chicago", label: "Chicago, USA" },
  { id: "phoenix", label: "Phoenix, USA" },
  { id: "reykjavik", label: "Reykjavik, Iceland" },
];

export const DEFAULT_CLIMATE_ID = "berlin";

export const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
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

// Sized from the room's own heat-loss coefficient and the climate's design
// temperature -- see solver.materials.suggested_heater_power_w. A flat 1500W default
// massively overshot the target before the controller could react.
export const DEFAULT_HEAT_SOURCE: HeatSource = {
  xM: 0.4,
  yM: 1.5,
  maxPowerW: 530,
};
