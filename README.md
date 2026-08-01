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
  different problem, so a year needs 365 distinct solves. The buoyancy velocity is
  always one spatial pattern scaled by a single scalar, and because upwind advection
  scales linearly with a non-negative scalar, the FVM operator is *exactly affine* in
  that scalar. A greedy reduced-basis model is trained by sampling it directly (no
  full-solver day needed at all) and recomputes the buoyancy nonlinearity every
  timestep instead of freezing it — the app also keeps the simpler frozen single-point
  baseline it replaced, so the accuracy gain is measured, not just claimed.
- **A measured validity envelope**, not just a claim: both reductions are checked
  against the full solver across the seasons, and the app shows where each can be
  trusted.
- **Interactive frontend**: an SVG room/window/door/heat-source editor, a Three.js WebGL
  heatmap with an hour scrubber, per-month and per-day energy charts, and the accuracy
  panel.

## How well does the reduction work?

The app ships two reductions and measures both against the full nonlinear solver, on
the same days, from the same initial condition — not just the one it uses live:

- **Baseline**: freeze the buoyancy velocity at the pattern from one representative
  day, reduce by modal truncation. Simple, but the frozen velocity is the dominant
  error source, and it's wrong even on the day it was fitted to (the driving delta-T
  swings ~7x across a single day).
- **Adaptive** (what the app actually uses): a greedy reduced-basis model trained by
  sampling the circulation strength directly, recomputing it every timestep via
  under-relaxed Picard iteration.

Annual energy error against the full solver, reference room, four climates:

| Location | Baseline | Adaptive |
|---|---|---|
| Berlin | +5.4% | **+1.1%** |
| Chicago | +5.6% | **+0.4%** |
| Phoenix | +1.2% | **+0.2%** |
| Reykjavík | +3.5% | **+0.9%** |

Worst single high-demand day: Berlin 24.0% → 6.9%, Chicago 29.0% → 4.7%, Phoenix
16.7% → 3.6%, Reykjavík 12.4% → 3.5%. The adaptive model wins on every climate, on
both metrics.

Findings that shaped the design, recorded in detail in `CLAUDE.md`:

- **The FVM operator is exactly affine in the buoyancy strength** (`A(s) = A0 + s·A1`,
  verified to ~1e-13) — the property that makes training the adaptive basis cheap and
  makes recomputing the nonlinearity every step affordable.
- **Naive fixed-point iteration on that nonlinearity doesn't converge — it cycles.**
  Traced directly: undamped iteration settles into an exact period-2 limit cycle. Under-
  relaxation fixes it; this was caught only by baking full validation runs, not by
  small hand-picked spot checks.
- **Pick the linearization point (baseline path) by heating-degree-day-weighted mean,
  not the calendar mean.** In Phoenix the annual mean sits *above* the thermostat
  target, anchoring the model where no heating ever runs — that produced a −54% annual
  error, versus +1.2% with the weighted anchor.
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
solver/rb.py            affine operator decomposition + greedy reduced-basis training
solver/mor.py           both reductions (frozen baseline, adaptive greedy-RB), annual energy estimate
solver/validation.py    reduced-vs-full accuracy measurement, both models, paired comparison
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
