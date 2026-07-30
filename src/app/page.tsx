"use client";

import { useState } from "react";
import { RoomEditor } from "@/components/editor/RoomEditor";
import { HeatmapView } from "@/components/heatmap/HeatmapView";
import { DayCharts } from "@/components/charts/DayCharts";
import { runSimulation } from "@/lib/api";
import { CLIMATE_PRESETS, DEFAULT_HEAT_SOURCE, DEFAULT_ROOM, DEFAULT_THERMOSTAT } from "@/lib/defaults";
import type { ClimatePreset, HeatSource, Room, SimulationResult, ThermostatSettings } from "@/lib/types";

export default function Home() {
  const [room, setRoom] = useState<Room>(DEFAULT_ROOM);
  const [heatSource, setHeatSource] = useState<HeatSource>(DEFAULT_HEAT_SOURCE);
  const [climate, setClimate] = useState<ClimatePreset>(CLIMATE_PRESETS[0]);
  const [thermostat, setThermostat] = useState<ThermostatSettings>(DEFAULT_THERMOSTAT);

  const [result, setResult] = useState<SimulationResult | null>(null);
  const [hourIndex, setHourIndex] = useState(0);
  const [status, setStatus] = useState<"idle" | "running" | "error">("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function handleRun() {
    setStatus("running");
    setErrorMessage(null);
    try {
      const simResult = await runSimulation({ room, heatSource, climate, thermostat });
      setResult(simResult);
      setHourIndex(0);
      setStatus("idle");
    } catch (err) {
      setStatus("error");
      setErrorMessage(err instanceof Error ? err.message : String(err));
    }
  }

  const currentFrame = result?.representativeDay[hourIndex];

  return (
    <div className="flex flex-1 flex-col bg-zinc-50 font-sans dark:bg-black">
      <main className="mx-auto flex w-full max-w-6xl flex-col gap-8 px-6 py-10">
        <header>
          <h1 className="text-2xl font-semibold">heat-fvm</h1>
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            2D room heat-flow simulation: place windows, doors, and a heat source, then see how the heater
            keeps the room at its target temperature — and what that costs per month.
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
                  step={50}
                  min={100}
                  value={heatSource.maxPowerW}
                  onChange={(e) => setHeatSource({ ...heatSource, maxPowerW: Number(e.target.value) })}
                  className="rounded border px-2 py-1"
                />
              </label>
              <label className="flex flex-col gap-1">
                Climate
                <select
                  value={climate.id}
                  onChange={(e) => setClimate(CLIMATE_PRESETS.find((c) => c.id === e.target.value) ?? climate)}
                  className="rounded border px-2 py-1"
                >
                  {CLIMATE_PRESETS.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.label}
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
                  onChange={(e) => setThermostat({ ...thermostat, nightTargetC: Number(e.target.value) })}
                  className="rounded border px-2 py-1"
                />
              </label>
            </div>

            <button
              type="button"
              onClick={handleRun}
              disabled={status === "running"}
              className="w-fit rounded bg-foreground px-4 py-2 text-sm font-medium text-background disabled:opacity-50"
            >
              {status === "running" ? "Simulating…" : "Run simulation"}
            </button>
            {status === "error" && <p className="text-sm text-red-600">{errorMessage}</p>}
          </section>

          <section className="flex flex-col gap-4">
            <h2 className="text-lg font-medium">Result</h2>
            {!result && (
              <p className="text-sm text-zinc-500">
                Run the simulation to see the temperature field, room temperature over the day, and monthly
                energy estimate.
              </p>
            )}
            {result && currentFrame && (
              <>
                <HeatmapView
                  nx={result.grid.nx}
                  ny={result.grid.ny}
                  temperatureC={currentFrame.temperatureC}
                  widthM={room.widthM}
                  heightM={room.heightM}
                />
                <label className="flex flex-col gap-1 text-sm">
                  Hour: {currentFrame.hour.toFixed(1)}
                  <input
                    type="range"
                    min={0}
                    max={result.representativeDay.length - 1}
                    value={hourIndex}
                    onChange={(e) => setHourIndex(Number(e.target.value))}
                  />
                </label>

                <div className="rounded border p-3 text-sm">
                  <span className="font-medium">Estimated monthly heater energy: </span>
                  {result.monthlyEnergyKWh.toFixed(0)} kWh
                </div>

                <DayCharts frames={result.representativeDay} thermostat={thermostat} />
              </>
            )}
          </section>
        </div>
      </main>
    </div>
  );
}
