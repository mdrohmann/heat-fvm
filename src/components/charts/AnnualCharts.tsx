"use client";

import { useEffect, useRef } from "react";
import * as Plot from "@observablehq/plot";
import { MONTH_NAMES } from "@/lib/defaults";
import type { AnnualEnergy } from "@/lib/types";

interface AnnualChartsProps {
  annual: AnnualEnergy;
  selectedMonthIndex: number;
}

export function AnnualCharts({ annual, selectedMonthIndex }: AnnualChartsProps) {
  const monthlyRef = useRef<HTMLDivElement | null>(null);
  const dailyRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const container = monthlyRef.current;
    if (!container) return;

    const data = annual.monthlyKWh.map((kwh, index) => ({
      month: MONTH_NAMES[index].slice(0, 3),
      index,
      kwh,
    }));

    const plot = Plot.plot({
      width: container.clientWidth || 500,
      height: 200,
      marginBottom: 34,
      x: { label: null, domain: data.map((d) => d.month) },
      y: { label: "kWh / month", grid: true },
      marks: [
        Plot.barY(data, {
          x: "month",
          y: "kwh",
          fill: (d: { index: number }) => (d.index === selectedMonthIndex ? "#b2182b" : "#e07b39"),
          title: (d: { index: number; kwh: number }) =>
            `${MONTH_NAMES[d.index]}: ${d.kwh.toFixed(1)} kWh`,
        }),
        Plot.ruleY([0]),
      ],
    });

    container.replaceChildren(plot);
    return () => plot.remove();
  }, [annual, selectedMonthIndex]);

  useEffect(() => {
    const container = dailyRef.current;
    if (!container) return;

    const data = annual.dailyKWh.map((kwh, dayOfYear) => ({
      dayOfYear,
      kwh,
      outdoorC: annual.dailyMeanOutdoorC[dayOfYear],
    }));

    const plot = Plot.plot({
      width: container.clientWidth || 500,
      height: 210,
      x: { label: "day of year" },
      y: { label: "kWh / day", grid: true },
      marks: [
        Plot.areaY(data, { x: "dayOfYear", y: "kwh", fill: "#e07b39", fillOpacity: 0.35 }),
        Plot.lineY(data, { x: "dayOfYear", y: "kwh", stroke: "#e07b39" }),
        Plot.ruleY([0]),
      ],
    });

    container.replaceChildren(plot);
    return () => plot.remove();
  }, [annual]);

  return (
    <div className="flex flex-col gap-5">
      <div>
        <h3 className="mb-2 text-sm font-medium">Energy by month</h3>
        <div ref={monthlyRef} />
      </div>
      <div>
        <h3 className="mb-1 text-sm font-medium">Energy by day</h3>
        <p className="mb-2 text-xs text-zinc-500">
          365 individually simulated days — each sees its own climatological outdoor temperature.
        </p>
        <div ref={dailyRef} />
      </div>
    </div>
  );
}
