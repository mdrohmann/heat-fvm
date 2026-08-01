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
- The buoyancy circulation strength `s` is a **single scalar** the whole velocity field
  scales by (`fvm.buoyancy_speed_scale`), and because upwind advection scales linearly
  with a non-negative scalar, the FVM operator is **exactly affine** in it:
  `A(s) = A0 + s*A1`, verified to ~1e-13 (`test_rb.py`). This is what makes a proper
  reduced-basis model cheap: the basis is trained by sampling `s` directly (a few small
  dense solves), needing no full-solver trajectory at all, and online the reduced
  operator for any `s` is just a scalar combination of two small precomputed matrices —
  cheap enough to re-evaluate every timestep. See `solver/rb.py`.
- **Un-damped Picard iteration on `s` does not converge — it cycles.** `s` closes a
  negative-feedback loop (more circulation mixes away the delta-T driving it), and the
  loop gain is steep enough that plain fixed-point iteration settles into an exact
  period-2 limit cycle (traced directly: alternates ~0.048 and ~0.287, forever). Fixed
  iteration counts then sample different phases of that cycle, which produced a
  confusing sign-alternating few-percent annual bias across every climate before this
  was diagnosed by baking and comparing *full* validation runs — small hand-picked spot
  checks looked fine on their own. Standard under-relaxation (blend new/old estimate,
  `picard_relaxation=0.5`) fixes it, converging in ~4-5 iterations. If you touch
  `AdaptiveReducedModel.step`, re-run `scripts/run_rom_validation.py` before trusting
  the result — a plausible-looking single-day check is not enough here.
- An "optimization" that breaks early when an eigen-bin looks unchanged is **not**
  equivalent to running the fixed iteration count: the bin can match while the
  underlying continuous `s` is still drifting within it, silently falling back to a
  single start-of-step solve exactly where iteration was needed. Don't add early-exit
  convergence checks to the Picard loop without re-validating against the full solver.
- Pick the ROM's linearisation point by **heating-degree-day-weighted** mean outdoor
  temperature, not the plain annual mean (this still matters for the frozen baseline,
  kept as a comparison point). In a hot climate the annual mean sits above the
  thermostat target, anchoring the model where no heating runs — measured at -54%
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
