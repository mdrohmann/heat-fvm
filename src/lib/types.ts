// Shared contract between the frontend and the Python solver (/api/simulate).
// Keep this in sync with api/simulate.py — it is the single source of truth for the
// JSON shape crossing that boundary.

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

export interface ClimateOption {
  id: string;
  label: string;
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
  climateId: string;
  /** 0 = January. Selects which month's mid-point day the heatmap animates. */
  viewMonthIndex: number;
  thermostat: ThermostatSettings;
}

export interface SimulationFrame {
  hour: number;
  /** Flattened row-major temperature field, degrees C. */
  temperatureC: number[];
  heaterPowerW: number;
}

export interface ViewDay {
  dayOfYear: number;
  monthIndex: number;
  monthName: string;
  meanOutdoorTempC: number;
  frames: SimulationFrame[];
}

export interface AnnualEnergy {
  totalKWh: number;
  /** 12 entries, January first. */
  monthlyKWh: number[];
  /** 365 entries. */
  dailyKWh: number[];
  dailyMeanIndoorC: number[];
  dailyMeanOutdoorC: number[];
}

export interface ClimateSummary {
  id: string;
  label: string;
  annualMeanTempC: number;
  designOutdoorTempC: number;
  /** The day the reduced model is linearized about — a property of the climate, not
   * of which month is being viewed, so the annual number stays stable while browsing. */
  linearizationDayOfYear: number;
  linearizationMeanTempC: number;
}

export interface ValidationPoint {
  dayOfYear: number;
  meanOutdoorTempC: number;
  fullEnergyKWh: number;
  reducedEnergyKWh: number;
  relativeError: number;
}

export interface ValidationSummary {
  label: string;
  linearization_day_of_year: number;
  linearization_mean_temp_c: number;
  total_energy_relative_error: number;
  max_abs_relative_error: number;
  mean_abs_relative_error: number;
  max_abs_error_kwh: number;
  points: ValidationPoint[];
}

export interface ClimateDataMeta {
  source: string;
  source_url?: string;
  attribution?: string;
  period: string;
  method: string;
}

export interface SimulationResult {
  grid: { nx: number; ny: number };
  viewDay: ViewDay;
  annual: AnnualEnergy;
  climate: ClimateSummary;
  validation: ValidationSummary | null;
  climateDataMeta: ClimateDataMeta;
}
