// Shared contract between the frontend and the Python solver (/api/simulate).
// Keep this in sync with solver/geometry.py and solver/materials.py — it is the
// single source of truth for the JSON shape crossing that boundary.

export type WallElementType = "wall" | "window" | "door";
export type WallSide = "north" | "east" | "south" | "west";

export interface WallElement {
  type: WallElementType;
  /** Position along the wall, in meters from the wall's start corner. */
  offsetM: number;
  /** Extent along the wall, in meters. */
  lengthM: number;
}

export interface Room {
  widthM: number;
  heightM: number;
  /** Elements placed on each of the room's four walls (north/east/south/west). */
  walls: Record<WallSide, WallElement[]>;
}

export interface HeatSource {
  /** Position within the room, in meters from the room's southwest corner. */
  xM: number;
  yM: number;
  maxPowerW: number;
}

export interface ClimatePreset {
  id: string;
  label: string;
  meanOutdoorTempC: number;
  diurnalAmplitudeC: number;
  peakHour: number;
}

export interface ThermostatSettings {
  dayTargetC: number;
  nightTargetC: number;
  dayStartHour: number;
  nightStartHour: number;
}

export interface SimulationRequest {
  room: Room;
  heatSource: HeatSource;
  climate: ClimatePreset;
  thermostat: ThermostatSettings;
}

export interface SimulationFrame {
  hour: number;
  /** Flattened row-major temperature field, degrees C. */
  temperatureC: number[];
  heaterPowerW: number;
}

export interface SimulationResult {
  grid: { nx: number; ny: number };
  representativeDay: SimulationFrame[];
  monthlyEnergyKWh: number;
}
