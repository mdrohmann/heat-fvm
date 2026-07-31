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

  useEffect(() => {
    const container = chartRef.current;
    if (!container) return;

    const data = validation.points.flatMap((point) => [
      { temp: point.meanOutdoorTempC, kwh: point.fullEnergyKWh, model: "full FVM" },
      { temp: point.meanOutdoorTempC, kwh: point.reducedEnergyKWh, model: "reduced model" },
    ]);

    const plot = Plot.plot({
      width: container.clientWidth || 500,
      height: 230,
      x: { label: "daily mean outdoor temperature (°C)" },
      y: { label: "heater energy (kWh/day)", grid: true },
      color: {
        legend: true,
        domain: ["full FVM", "reduced model"],
        range: ["#2166ac", "#e07b39"],
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
  }, [validation]);

  return (
    <section className="flex flex-col gap-3 rounded border p-4">
      <div>
        <h2 className="text-base font-medium">How accurate is the reduced model?</h2>
        <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
          Building a surrogate is the easy half; knowing where it can be trusted is the half that
          decides whether you can use the answer. Each point below runs <em>both</em> the full
          nonlinear solver and the reduced model over the same day and compares heater energy.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
        <div className="rounded bg-zinc-100 p-2 dark:bg-zinc-900">
          <div className="text-xs text-zinc-500">Annual energy error</div>
          <div className="text-lg font-medium">
            {formatSignedPercent(validation.total_energy_relative_error)}
          </div>
        </div>
        <div className="rounded bg-zinc-100 p-2 dark:bg-zinc-900">
          <div className="text-xs text-zinc-500">Worst high-demand day</div>
          <div className="text-lg font-medium">
            {(validation.max_abs_relative_error * 100).toFixed(1)}%
          </div>
        </div>
        <div className="rounded bg-zinc-100 p-2 dark:bg-zinc-900">
          <div className="text-xs text-zinc-500">Worst day, absolute</div>
          <div className="text-lg font-medium">{validation.max_abs_error_kwh.toFixed(2)} kWh</div>
        </div>
      </div>

      <div ref={chartRef} />

      <p className="text-xs text-zinc-500">
        The dashed line marks the operating point the model was linearized about
        ({validation.linearization_mean_temp_c.toFixed(1)} °C). Accuracy is best near it and
        degrades on mild days — but those days need little heat, so the error lands where the
        energy isn&rsquo;t. That is why the annual total stays within a few percent even though a
        single mild day can be off by more.
      </p>
      <p className="text-xs text-zinc-500">
        Measured offline on a reference 4.0 × 3.0 m room, so these figures characterize the method
        rather than the exact geometry you have dialed in above.
      </p>
    </section>
  );
}
