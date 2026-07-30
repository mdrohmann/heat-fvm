# heat-fvm

**Simulate how heater positions, insulation, and climate affect heating costs.**

A 2D finite-volume heat-flow simulator for a single room: place windows, doors, and a
heat source, pick a climate and target temperature, and watch a proportional-integral
thermostat keep the room at temperature — with a monthly energy estimate computed via
model-order reduction instead of brute-force simulation.

> **Disclaimer:** this is a simplified theoretical model built for demonstration
> purposes. It has not been validated against real-world measurements — treat the
> numbers as illustrative, not predictive.

## What it does

- **2D nonlinear FVM solver** for room air temperature: conduction, Robin (convective)
  boundary conditions per wall/window/door with realistic default U-values, and a
  buoyancy-driven circulation whose strength feeds back from the temperature field
  (a single fixed-shape convective roll, derived from a streamfunction so it's
  automatically mass-conserving and has zero flow through every wall).
- **PI-controlled thermostat**, with anti-windup, driving a heat source sized from the
  room's own loss coefficient rather than a flat guess.
- **Model-order reduction for the monthly energy estimate**: rather than running the
  full nonlinear solver for 30 simulated days, the model is linearized about a
  representative day's (time-averaged) velocity field, reduced via modal truncation of
  the discretized operator, and time-stepped with an exact exponential integrator until
  its daily energy consumption settles into a repeating pattern.
- **Interactive frontend**: an SVG room/window/door/heat-source editor, a Three.js
  WebGL heatmap of the simulated temperature field with an hour scrubber, and
  temperature/power/energy charts.

## How it works

```
solver/geometry.py      room/window/door/heat-source model, Cartesian mesh + boundary tagging
solver/materials.py     default U-values, air properties, climate presets, heater sizing
solver/fvm.py           FVM operator assembly + nonlinear buoyancy-coupled time-stepping
solver/controller.py    PI thermostat controller
solver/mor.py           linearization, modal truncation, monthly energy estimate
api/simulate.py         thin HTTP adapter (Vercel Python Function) over solver/
src/                    Next.js frontend (editor, WebGL heatmap, charts)
```

See `CLAUDE.md` for the fuller design rationale (why buoyancy is linearized for MOR,
testing philosophy, etc).

## Tech stack

Next.js (App Router) + TypeScript + Three.js + Observable Plot on the frontend; Python
+ NumPy/SciPy on the backend, deployed as a Vercel Python Function; pytest and
Playwright for testing.

## Running locally

```bash
npm install
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"

# Requires `vercel login` + `vercel link` once, since the Python function needs
# Vercel's dev server to build/run (plain `next dev` won't serve /api/simulate.py):
vercel dev
```

## Testing

```bash
.venv/bin/pytest          # solver + API integration tests
npm run test:e2e          # Playwright e2e tests (editor interactions)
npm run lint && npx tsc --noEmit
```

## Roadmap

- 3D simulations
- Heat pump vs. static heating elements
- More complex (multi-room) geometries
- More flexibility in climate input

## License

MIT — see [LICENSE](./LICENSE).
