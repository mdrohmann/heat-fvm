"use client";

import { useEffect, useRef } from "react";
import * as Plot from "@observablehq/plot";
import type { ValidationSummary } from "@/lib/types";

interface ValidationPanelProps {
  validation: ValidationSummary;
}

function formatSignedPercent(fraction: number): string {
  return `${fraction >= 0 ? "+" : ""}${(fraction * 100).toFixed(1)}%`;
}

export function ValidationPanel({ validation }: ValidationPanelProps) {
  const chartRef = useRef<HTMLDivElement | null>(null);
  const { baseline, adaptive } = validation;

  useEffect(() => {
    const container = chartRef.current;
    if (!container) return;

    const data = [
      ...adaptive.points.map((point) => ({
        temp: point.meanOutdoorTempC,
        kwh: point.fullEnergyKWh,
        model: "full FVM",
      })),
      ...baseline.points.map((point) => ({
        temp: point.meanOutdoorTempC,
        kwh: point.reducedEnergyKWh,
        model: "baseline (frozen)",
      })),
      ...adaptive.points.map((point) => ({
        temp: point.meanOutdoorTempC,
        kwh: point.reducedEnergyKWh,
        model: "adaptive (this app)",
      })),
    ];

    const plot = Plot.plot({
      width: container.clientWidth || 500,
      height: 240,
      x: { label: "daily mean outdoor temperature (°C)" },
      y: { label: "heater energy (kWh/day)", grid: true },
      color: {
        legend: true,
        domain: ["full FVM", "baseline (frozen)", "adaptive (this app)"],
        range: ["#2166ac", "#999999", "#e07b39"],
      },
      marks: [
        Plot.ruleY([0]),
        Plot.line(data, { x: "temp", y: "kwh", stroke: "model", sort: "temp" }),
        Plot.dot(data, { x: "temp", y: "kwh", fill: "model", r: 3.5, sort: "temp" }),
        Plot.ruleX([validation.linearization_mean_temp_c], {
          stroke: "#888",
          strokeDasharray: "3,3",
        }),
      ],
    });

    container.replaceChildren(plot);
    return () => plot.remove();
  }, [validation, baseline, adaptive]);

  return (
    <section className="flex flex-col gap-3 rounded border p-4">
      <div>
        <h2 className="text-base font-medium">How accurate is the reduced model?</h2>
        <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
          This app uses an <strong>adaptive</strong> reduced-basis model: the buoyancy convection
          strength is recomputed every timestep instead of frozen at one operating point. Shown
          below against the <strong>baseline</strong> it replaced (single-point modal truncation) —
          each point runs the full nonlinear solver once and checks both reductions against that
          same run, so the comparison is paired and fair.
        </p>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[420px] text-sm">
          <thead>
            <tr className="text-left text-xs text-zinc-500">
              <th className="pb-1 font-normal"></th>
              <th className="pb-1 font-normal">Annual energy error</th>
              <th className="pb-1 font-normal">Worst high-demand day</th>
              <th className="pb-1 font-normal">Worst day, absolute</th>
            </tr>
          </thead>
          <tbody>
            <tr className="border-t text-zinc-500">
              <td className="py-1.5">baseline (frozen)</td>
              <td className="py-1.5">{formatSignedPercent(baseline.total_energy_relative_error)}</td>
              <td className="py-1.5">{(baseline.max_abs_relative_error * 100).toFixed(1)}%</td>
              <td className="py-1.5">{baseline.max_abs_error_kwh.toFixed(2)} kWh</td>
            </tr>
            <tr className="border-t font-medium">
              <td className="py-1.5">adaptive (this app)</td>
              <td className="py-1.5">{formatSignedPercent(adaptive.total_energy_relative_error)}</td>
              <td className="py-1.5">{(adaptive.max_abs_relative_error * 100).toFixed(1)}%</td>
              <td className="py-1.5">{adaptive.max_abs_error_kwh.toFixed(2)} kWh</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div ref={chartRef} />

      <p className="text-xs text-zinc-500">
        The dashed line marks the operating point the baseline was linearized about
        ({validation.linearization_mean_temp_c.toFixed(1)} °C) — the adaptive model has no such
        single point, since it re-derives the operator every step. Both reductions are most
        accurate on cold, high-demand days and least accurate on mild ones — but mild days need
        little heat, so the error lands where the energy isn&rsquo;t, which is why each annual
        total stays far below its own worst single-day error.
      </p>
      <p className="text-xs text-zinc-500">
        Measured offline on a reference 4.0 × 3.0 m room, so these figures characterize the method
        rather than the exact geometry you have dialed in above.
      </p>
    </section>
  );
}
