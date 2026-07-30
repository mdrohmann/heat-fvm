"use client";

import { useEffect, useRef } from "react";
import * as Plot from "@observablehq/plot";
import type { SimulationFrame, ThermostatSettings } from "@/lib/types";

interface DayChartsProps {
  frames: SimulationFrame[];
  thermostat: ThermostatSettings;
}

function targetTempC(hour: number, thermostat: ThermostatSettings): number {
  const h = hour % 24;
  const isDay = thermostat.dayStartHour <= h && h < thermostat.nightStartHour;
  return isDay ? thermostat.dayTargetC : thermostat.nightTargetC;
}

export function DayCharts({ frames, thermostat }: DayChartsProps) {
  const tempRef = useRef<HTMLDivElement | null>(null);
  const powerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const container = tempRef.current;
    if (!container) return;

    const roomAvg = frames.map((f) => ({
      hour: f.hour,
      value: f.temperatureC.reduce((a, b) => a + b, 0) / f.temperatureC.length,
      series: "room average",
    }));
    const target = frames.map((f) => ({ hour: f.hour, value: targetTempC(f.hour, thermostat), series: "target" }));

    const plot = Plot.plot({
      width: container.clientWidth || 500,
      height: 220,
      x: { label: "hour of day" },
      y: { label: "°C" },
      color: { legend: true, domain: ["room average", "target"], range: ["#2166ac", "#b2182b"] },
      marks: [
        Plot.lineY(target, { x: "hour", y: "value", stroke: "series", strokeDasharray: "4,2" }),
        Plot.lineY(roomAvg, { x: "hour", y: "value", stroke: "series" }),
      ],
    });
    container.replaceChildren(plot);
    return () => plot.remove();
  }, [frames, thermostat]);

  useEffect(() => {
    const container = powerRef.current;
    if (!container) return;

    const power = frames.map((f) => ({ hour: f.hour, value: f.heaterPowerW }));

    const plot = Plot.plot({
      width: container.clientWidth || 500,
      height: 160,
      x: { label: "hour of day" },
      y: { label: "heater power (W)" },
      marks: [
        Plot.areaY(power, { x: "hour", y: "value", fill: "#e07b39", fillOpacity: 0.4 }),
        Plot.lineY(power, { x: "hour", y: "value", stroke: "#e07b39" }),
      ],
    });
    container.replaceChildren(plot);
    return () => plot.remove();
  }, [frames]);

  return (
    <div className="flex flex-col gap-4">
      <div ref={tempRef} />
      <div ref={powerRef} />
    </div>
  );
}
