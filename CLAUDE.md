# CLAUDE.md

## Purpose
This repo is an open-source demo of applying finite-volume simulation and model-order
reduction (MOR) to a real engineering problem — 2D building heat flow — as a portfolio
piece for surrogate/reduced-order modeling work. Code should read as a clear, correct
reference implementation, not a rushed demo.

## Priorities (in order)
1. **Simplicity, maintainability, reusability** — this explicitly outranks
   implementation speed. Do not choose a shortcut because it's faster to build; choose
   it because it's the simplest correct design. Do not estimate or optimize for
   time-to-ship.
2. **Physical/numerical correctness** — conservation laws, consistent SI units, and
   documented modeling assumptions (e.g. why buoyancy is linearized for MOR) take
   priority over polish.
3. **Extensibility to 3D** — geometry, mesh, and solver code must stay generic over
   dimensionality; do not hardcode 2D assumptions into interfaces even though only 2D
   ships first.

## Tech stack
- Frontend: Next.js (App Router), TypeScript, Three.js (WebGL heatmap), SVG/D3
  (geometry editor), a charting library (Observable Plot or visx — pick one early and
  stick with it).
- Backend: Python, SciPy/NumPy, deployed as a Vercel Python Function.
- Testing: pytest (Python), Playwright (browser e2e).

## Testing philosophy
- **Prefer e2e and integration tests over unit tests.** Test through real interfaces —
  the actual `/api/simulate` endpoint, the actual solver end-to-end, the actual rendered
  page — rather than mocking internals or testing isolated helper functions alone. A
  test that mocks the FVM assembly to check a controller function in isolation is lower
  value here than one that runs a real small simulation and checks its output.
- Numerical correctness checks (energy conservation, MOR-vs-full-FVM agreement) should
  run as integration tests against the real solver with real (small) inputs, not mocked
  matrices.
- Unit tests are acceptable only for pure, non-obvious math (e.g. a specific eigenmode
  truncation formula) where an integration test can't isolate a wrong result to its
  cause.

## Implementation constraints
- Solver must be usable independent of any HTTP/Vercel wrapper — `/api/simulate.py`
  should be a thin adapter over `solver/`, importable and testable directly.
- All physical quantities carry explicit units in variable names or docstrings (e.g.
  `u_value_w_per_m2k`); no bare unlabeled magic numbers for physical constants — put
  them in `materials.py` with a comment on their source/typical range.
- No ML/black-box surrogates for anything derivable from the physics — the whole point
  of this repo is transparent, physically-grounded model reduction.
- Don't add configuration options, abstractions, or generality beyond what 3D
  extensibility and the stated feature set actually require.
- Reduced-vs-full agreement is far more sensitive to the **timestep** than to the mesh.
  On a mild summer day, dt=1800s puts the two models 1.81 kWh apart, dt=900s 0.30 kWh,
  dt=300s 0.24 kWh — at coarse dt neither the PI controller nor backward Euler is well
  resolved, so the disagreement is temporal discretisation, not the reduction. Validate
  the ROM at the timestep the annual estimate actually uses; a "fast" coarse setting
  measures the wrong thing and will produce alarming-looking numbers.
- Pick the ROM's linearisation point by **heating-degree-day-weighted** mean outdoor
  temperature, not the plain annual mean. In a hot climate the annual mean sits above
  the thermostat target, anchoring the model where no heating runs — measured at -54%
  annual error for Phoenix, versus +1.2% with the weighted anchor. See
  `ClimateLocation.linearization_day_of_year`.
- There is no `vercel.json` on purpose: as of Vercel CLI 58.4.0, `vercel dev`'s Python
  builder throws (`builder.build()` must not contain \`maxDuration\`/\`memory\`) if
  `functions` config is set for `api/simulate.py`, even though the platform accepts
  those fields for real deployments. Platform defaults (300s timeout, 2GB memory) are
  already generous for this solver's grid sizes. If you need to reintroduce
  per-function config, verify it against the then-current CLI/builder version first —
  don't assume the local `vercel dev` failure mode has been fixed.

## Suggested skills & agents for building this
- `dataviz` — for styling the temperature-vs-time, heater power, and monthly energy
  charts consistently.
- `frontend-design` — for the overall visual design pass on the app, not just charts.
- `superpowers:test-driven-development` — pairs naturally with the "integration tests
  first" philosophy above.
- `superpowers:systematic-debugging` — for when the nonlinear buoyancy solver or MOR
  validation produces unexpected numbers; avoids guessing at fixes.
- `superpowers:writing-plans` / `superpowers:executing-plans` — for breaking the solver,
  MOR, and frontend into reviewable implementation chunks.
- `superpowers:requesting-code-review` / `code-review:code-review` — periodic PR-style
  review passes, worth it since this is a public/portfolio repo.
- `vercel:vercel-functions` — Python runtime specifics for the `/api/simulate` function.
- `vercel:nextjs` — App Router patterns for the frontend.
- `chrome-devtools-mcp` or the Playwright MCP tools — for driving real e2e browser
  checks of the WebGL heatmap and editor, consistent with the e2e-first testing
  philosophy.
- **Worth authoring** (via `skill-creator`) once the solver's core structure exists: a
  project-specific "physics review" checklist skill — energy conservation, unit
  consistency, ROM-vs-full-FVM agreement — since generic code review won't catch a
  plausible-looking but physically wrong solver change.

## Reference
Full design rationale (physical model, ROM approach, repo layout) lives in the original
planning doc; see git history / project docs for details if this file needs updating.
