import type { SimulationRequest, SimulationResult } from "./types";

export async function runSimulation(request: SimulationRequest): Promise<SimulationResult> {
  const response = await fetch("/api/simulate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.error ?? `Simulation request failed (${response.status})`);
  }

  return response.json();
}
