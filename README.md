# heat-fvm

**Simulate how heater positions, insulation, and climate affect heating costs.**

🔗 **Live demo:** [heat-fvm.vercel.app](https://heat-fvm.vercel.app)

A 2D finite-volume heat-flow simulator for a single room: place windows, doors, and a
heat source, pick a location, and get a **full year of heating simulated day by day** —
each day driven by ~86 years of ERA5 climate normals for that location. A reduced-order
model makes the annual run take **seconds instead of the ~38 minutes** the full
nonlinear solver would need.

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
  room's own loss coefficient and the local design temperature rather than a flat guess.
- **Real climate data**: daily normals for four locations (Berlin, Chicago, Phoenix,
  Reykjavík) derived from ERA5 reanalysis, 1940–2025, fetched offline and committed —
  the solver never touches the network.
- **Model-order reduction that earns its keep.** Every day of the year is a genuinely
  different problem, so a year needs 365 distinct solves. The model is linearized about
  one representative day, reduced by modal truncation of the discretized operator, and
  time-stepped with an exact exponential integrator. Because the operator is provably
  invariant to outdoor temperature (it enters only through the forcing), a *single*
  linearization serves the entire year.
- **A measured validity envelope**, not just a claim: the reduced model is checked
  against the full solver across the seasons, and the app shows where it can be trusted.
- **Interactive frontend**: an SVG room/window/door/heat-source editor, a Three.js WebGL
  heatmap with an hour scrubber, per-month and per-day energy charts, and the accuracy
  panel.

## How well does the reduction work?

Measured on the reference room, against the full nonlinear solver:

| Location | Annual energy error | Worst high-demand day |
|---|---|---|
| Berlin | +5.4% | 24.0% |
| Chicago | +5.6% | 29.0% |
| Phoenix | +1.2% | 16.7% |
| Reykjavík | +3.5% | 12.4% |

The interesting part is *where* the error goes. Accuracy is best near the linearization
point and degrades on mild days — but mild days need little heat, so the error lands
where the energy isn't, and the annual total stays within a few percent even though a
single mild day can be off by more.

Two findings that shaped the design, both recorded in `CLAUDE.md`:

- **Pick the linearization point by heating-degree-day-weighted mean, not the calendar
  mean.** In Phoenix the annual mean sits *above* the thermostat target, anchoring the
  model where no heating ever runs — that produced a −54% annual error, versus +1.2%
  with the weighted anchor.
- **Reduced-vs-full agreement is far more sensitive to the timestep than to the mesh.**
  On a mild day, dt=1800s puts the models 1.81 kWh apart; dt=300s, 0.24 kWh. Validating
  at a coarse "fast" timestep measures temporal discretization error, not the reduction.

## How it works

```
solver/geometry.py      room/window/door/heat-source model, Cartesian mesh + boundary tagging
solver/climate.py       day-of-year climate model backed by baked ERA5 normals
solver/materials.py     U-values, air properties, heater sizing
solver/fvm.py           FVM operator assembly + nonlinear buoyancy-coupled time-stepping
solver/controller.py    PI thermostat controller
solver/mor.py           linearization, modal truncation, annual energy estimate
solver/validation.py    reduced-vs-full accuracy measurement
solver/data/            committed ERA5 normals + baked validation results
scripts/                offline data-fetch and validation studies (run once, commit output)
api/simulate.py         thin HTTP adapter (Vercel Python Function) over solver/
src/                    Next.js frontend (editor, WebGL heatmap, charts)
```

See `CLAUDE.md` for the fuller design rationale (why buoyancy is linearized for MOR,
testing philosophy, etc).

## Regenerating the data

Both datasets are committed, so this is only needed to refresh them:

```bash
.venv/bin/python scripts/fetch_climate_normals.py   # ERA5 daily normals (hits Open-Meteo)
.venv/bin/python scripts/run_rom_validation.py      # reduced-vs-full accuracy study
```

Climate data: ERA5 reanalysis (Copernicus Climate Change Service), retrieved via the
[Open-Meteo Historical Weather API](https://open-meteo.com/) (CC-BY-4.0).

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
