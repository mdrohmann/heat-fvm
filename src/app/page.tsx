"use client";

import { useState } from "react";
import { RoomEditor } from "@/components/editor/RoomEditor";
import { HeatmapView } from "@/components/heatmap/HeatmapView";
import { ColorBar } from "@/components/heatmap/ColorBar";
import { DayCharts } from "@/components/charts/DayCharts";
import { AnnualCharts } from "@/components/charts/AnnualCharts";
import { ValidationPanel } from "@/components/charts/ValidationPanel";
import { runSimulation } from "@/lib/api";
import {
  CLIMATE_OPTIONS,
  DEFAULT_CLIMATE_ID,
  DEFAULT_HEAT_SOURCE,
  DEFAULT_ROOM,
  DEFAULT_THERMOSTAT,
  MONTH_NAMES,
} from "@/lib/defaults";
import { targetAnchoredDomain } from "@/lib/colormap";
import type { HeatSource, Room, SimulationResult, ThermostatSettings } from "@/lib/types";

export default function Home() {
  const [room, setRoom] = useState<Room>(DEFAULT_ROOM);
  const [heatSource, setHeatSource] = useState<HeatSource>(DEFAULT_HEAT_SOURCE);
  const [climateId, setClimateId] = useState<string>(DEFAULT_CLIMATE_ID);
  const [thermostat, setThermostat] = useState<ThermostatSettings>(DEFAULT_THERMOSTAT);
  const [viewMonthIndex, setViewMonthIndex] = useState(0);

  const [result, setResult] = useState<SimulationResult | null>(null);
  const [hourIndex, setHourIndex] = useState(0);
  const [status, setStatus] = useState<"idle" | "running" | "error">("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function handleRun(monthIndex = viewMonthIndex) {
    setStatus("running");
    setErrorMessage(null);
    try {
      const simResult = await runSimulation({
        room,
        heatSource,
        climateId,
        viewMonthIndex: monthIndex,
        thermostat,
      });
      setResult(simResult);
      setHourIndex(0);
      setStatus("idle");
    } catch (err) {
      setStatus("error");
      setErrorMessage(err instanceof Error ? err.message : String(err));
    }
  }

  const currentFrame = result?.viewDay.frames[hourIndex];
  const isRunning = status === "running";
  // Fixed for the whole day's animation, anchored on the day target -- white means
  // "at target", not "warmest pixel this frame", and the scale no longer jumps
  // between frames, months, or climates.
  const heatmapDomain = result
    ? targetAnchoredDomain(result.viewDay.frames.flatMap((f) => f.temperatureC), thermostat.dayTargetC)
    : null;

  return (
    <div className="flex flex-1 flex-col bg-zinc-50 font-sans dark:bg-black">
      <main className="mx-auto flex w-full max-w-6xl flex-col gap-8 px-6 py-10">
        <header className="flex flex-col gap-3">
          <h1 className="text-2xl font-semibold">heat-fvm</h1>
          <p className="text-lg font-medium text-zinc-800 dark:text-zinc-200">
            Simulate how heater positions, insulation, and climate affect heating costs.
          </p>
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            A 2D finite-volume heat-flow simulator. Place windows, doors, and a heat source, pick a
            climate, and get a full year of heating simulated day by day — each day against ~86
            years of ERA5 climate normals for that location. A reduced-order model makes the annual
            run take seconds instead of the half-hour the full solver would need.
          </p>
          <p className="rounded border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
            This is a simplified theoretical model built for demonstration purposes. It has not been
            validated against real-world measurements — treat the numbers as illustrative, not
            predictive.
          </p>
        </header>

        <div className="grid grid-cols-1 gap-8 lg:grid-cols-2">
          <section className="flex flex-col gap-4">
            <h2 className="text-lg font-medium">Room</h2>
            <RoomEditor
              room={room}
              heatSource={heatSource}
              onChangeRoom={setRoom}
              onChangeHeatSource={setHeatSource}
            />

            <div className="grid grid-cols-2 gap-3 text-sm">
              <label className="flex flex-col gap-1">
                Width (m)
                <input
                  type="number"
                  step={0.1}
                  min={1}
                  value={room.widthM}
                  onChange={(e) => setRoom({ ...room, widthM: Number(e.target.value) })}
                  className="rounded border px-2 py-1"
                />
              </label>
              <label className="flex flex-col gap-1">
                Height (m)
                <input
                  type="number"
                  step={0.1}
                  min={1}
                  value={room.heightM}
                  onChange={(e) => setRoom({ ...room, heightM: Number(e.target.value) })}
                  className="rounded border px-2 py-1"
                />
              </label>
              <label className="flex flex-col gap-1">
                Heater max power (W)
                <input
                  type="number"
                  step={25}
                  min={50}
                  value={heatSource.maxPowerW}
                  onChange={(e) => setHeatSource({ ...heatSource, maxPowerW: Number(e.target.value) })}
                  className="rounded border px-2 py-1"
                />
              </label>
              <label className="flex flex-col gap-1">
                Location
                <select
                  value={climateId}
                  onChange={(e) => setClimateId(e.target.value)}
                  className="rounded border px-2 py-1"
                >
                  {CLIMATE_OPTIONS.map((option) => (
                    <option key={option.id} value={option.id}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1">
                Day target (°C)
                <input
                  type="number"
                  step={0.5}
                  value={thermostat.dayTargetC}
                  onChange={(e) => setThermostat({ ...thermostat, dayTargetC: Number(e.target.value) })}
                  className="rounded border px-2 py-1"
                />
              </label>
              <label className="flex flex-col gap-1">
                Night target (°C)
                <input
                  type="number"
                  step={0.5}
                  value={thermostat.nightTargetC}
                  onChange={(e) =>
                    setThermostat({ ...thermostat, nightTargetC: Number(e.target.value) })
                  }
                  className="rounded border px-2 py-1"
                />
              </label>
            </div>

            <label className="flex flex-col gap-1 text-sm">
              Month to visualise
              <select
                value={viewMonthIndex}
                onChange={(e) => {
                  const monthIndex = Number(e.target.value);
                  setViewMonthIndex(monthIndex);
                  if (result) handleRun(monthIndex);
                }}
                className="rounded border px-2 py-1"
              >
                {MONTH_NAMES.map((name, index) => (
                  <option key={name} value={index}>
                    {name}
                  </option>
                ))}
              </select>
            </label>

            <button
              type="button"
              onClick={() => handleRun()}
              disabled={isRunning}
              className="w-fit rounded bg-foreground px-4 py-2 text-sm font-medium text-background disabled:opacity-50"
            >
              {isRunning ? "Simulating…" : "Run simulation"}
            </button>
            {status === "error" && <p className="text-sm text-red-600">{errorMessage}</p>}
            {isRunning && (
              <p className="text-xs text-zinc-500">
                Running one full nonlinear day plus a reduced-order year. First run may take longer
                while the Python function cold-starts.
              </p>
            )}
          </section>

          <section className="flex flex-col gap-4">
            <h2 className="text-lg font-medium">Result</h2>
            {!result && (
              <p className="text-sm text-zinc-500">
                Run the simulation to see the temperature field, the annual heating energy, and how
                accurate the reduced model is.
              </p>
            )}
            {result && currentFrame && heatmapDomain && (
              <>
                <div className="rounded border p-3">
                  <div className="text-xs uppercase tracking-wide text-zinc-500">
                    Estimated annual heating energy
                  </div>
                  <div className="text-2xl font-semibold">
                    {result.annual.totalKWh.toFixed(0)} kWh
                  </div>
                  <div className="mt-1 text-xs text-zinc-500">
                    {result.climate.label} · annual mean {result.climate.annualMeanTempC.toFixed(1)} °C
                    · design temperature {result.climate.designOutdoorTempC.toFixed(1)} °C
                  </div>
                </div>

                <div>
                  <div className="mb-2 text-sm">
                    <span className="font-medium">{result.viewDay.monthName}</span>{" "}
                    <span className="text-zinc-500">
                      (day {result.viewDay.dayOfYear + 1}, mean outdoor{" "}
                      {result.viewDay.meanOutdoorTempC.toFixed(1)} °C)
                    </span>
                  </div>
                  <HeatmapView
                    nx={result.grid.nx}
                    ny={result.grid.ny}
                    temperatureC={currentFrame.temperatureC}
                    widthM={room.widthM}
                    heightM={room.heightM}
                    domain={heatmapDomain}
                  />
                  <div className="mt-1">
                    <ColorBar domain={heatmapDomain} targetC={thermostat.dayTargetC} />
                  </div>
                  <label className="mt-2 flex flex-col gap-1 text-sm">
                    Hour: {currentFrame.hour.toFixed(1)}
                    <input
                      type="range"
                      min={0}
                      max={result.viewDay.frames.length - 1}
                      value={hourIndex}
                      onChange={(e) => setHourIndex(Number(e.target.value))}
                    />
                  </label>
                </div>

                <DayCharts frames={result.viewDay.frames} thermostat={thermostat} />
              </>
            )}
          </section>
        </div>

        {result && (
          <>
            <section className="flex flex-col gap-3">
              <h2 className="text-lg font-medium">The year</h2>
              <AnnualCharts annual={result.annual} selectedMonthIndex={result.viewDay.monthIndex} />
            </section>

            {result.validation && <ValidationPanel validation={result.validation} />}

            <p className="text-xs text-zinc-500">
              Climate data: {result.climateDataMeta.source} ({result.climateDataMeta.period}).{" "}
              {result.climateDataMeta.method}
            </p>
          </>
        )}

        <footer className="mt-4 border-t pt-6 text-sm text-zinc-600 dark:text-zinc-400">
          <h2 className="text-base font-medium text-zinc-800 dark:text-zinc-200">Roadmap</h2>
          <ul className="mt-2 list-disc space-y-1 pl-5">
            <li>3D simulations</li>
            <li>Heat pump vs. static heating elements</li>
            <li>More complex (multi-room) geometries</li>
            <li>More flexibility in climate input</li>
          </ul>
          <a
            href="https://github.com/mdrohmann/heat-fvm"
            target="_blank"
            rel="noopener noreferrer"
            className="mt-3 inline-block underline"
          >
            View source on GitHub →
          </a>
        </footer>
      </main>
    </div>
  );
}
