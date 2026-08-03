"""Interactive walkthrough of the reduced-basis (RB) investigation findings.

Setup:  .venv/bin/pip install -e ".[dev,explore]"   (adds matplotlib for the plots;
        everything runs and prints fine without it too, just without the figures)

Open this file in VS Code with the Python extension and the repo's `.venv`
interpreter selected, then run cells one at a time with "Run Cell" / Shift+Enter
(the `# %%` markers below are VS Code's interactive-cell convention). Each cell
builds on state from the ones above it, so run them in order the first time.

What this walks through, in order:
  1. The buoyancy circulation strength `s` and how much it actually varies
  2. Why the FVM operator being *affine* in `s` matters
  3. A real bug: naive (undamped) iteration on `s` doesn't converge -- it cycles
  4. The fix: under-relaxation
  5. Training the greedy reduced basis, and watching it converge
  6. Baseline vs adaptive, measured against the full nonlinear solver
  7. The same comparison across all four climates (instant -- reads baked data)

The prose version of these findings lives in CLAUDE.md and README.md; this file
is for stepping through the actual numbers and plots that back them up. Nothing
here is reimplemented -- every cell calls straight into `solver/`, so this can't
drift from what the app actually does.
"""

# %% [markdown]
# ## 0. Setup

# %%
import numpy as np

from solver.climate import get_climate
from solver.fvm import (
    BuoyancyParams,
    assemble_operator,
    buoyancy_speed_scale_from_field,
    simulate_representative_day,
    unit_buoyancy_velocity,
)
from solver.geometry import HeatSource, Room, WallElement, WallElementType, build_room_mesh
from solver.materials import DEFAULT_THERMOSTAT, suggested_heater_power_w
from solver.mor import _step_modal_state, build_adaptive_model
from solver.rb import build_affine_operator, greedy_basis
from solver.validation import compare_models_across_days, load_baked_validation

try:
    import matplotlib.pyplot as plt

    HAVE_MPL = True
except ImportError:
    HAVE_MPL = False
    print("matplotlib not installed (pip install matplotlib) -- plots will be skipped, prints still work")

# The same reference room used throughout solver/tests/ and scripts/run_rom_validation.py.
ROOM = Room(
    width_m=4.0,
    height_m=3.0,
    walls={
        "north": [],
        "east": [WallElement(WallElementType.WINDOW, offset_m=0.9, length_m=1.2)],
        "south": [WallElement(WallElementType.DOOR, offset_m=1.5, length_m=0.9)],
        "west": [],
    },
)
CLIMATE = get_climate("berlin")
HEAT_SOURCE = HeatSource(
    x_m=0.4, y_m=1.5, max_power_w=suggested_heater_power_w(ROOM, CLIMATE, DEFAULT_THERMOSTAT)
)
print(f"heater sized to {HEAT_SOURCE.max_power_w:.0f} W for {CLIMATE.label}")


# %% [markdown]
# ## 1. The buoyancy parameter `s`
#
# The convection model is a single fixed spatial pattern -- a streamfunction-derived
# circulation roll -- scaled by one scalar `s`. `s` is derived from two temperatures:
# the heat-source cell and the room average (`buoyancy_speed_scale` in `solver/fvm.py`).
#
# The original ("baseline") reduced model freezes `s` at a single value taken from one
# representative day. How much does the *true* `s` actually move? This cell runs the
# full nonlinear solver for one January day (~5-10s) and evaluates `s` at every step.

# %%
day = simulate_representative_day(
    ROOM, HEAT_SOURCE, CLIMATE, DEFAULT_THERMOSTAT, day_of_year=14, nx=12, ny=9, dt_s=300.0
)
s_over_day = [
    buoyancy_speed_scale_from_field(day.room_mesh, field, BuoyancyParams())
    for field in day.temperature_fields_c
]
print(
    f"Jan 14: s ranges {min(s_over_day):.4f} .. {max(s_over_day):.4f} within a single day "
    f"({max(s_over_day) / max(min(s_over_day), 1e-9):.1f}x)"
)

if HAVE_MPL:
    plt.figure(figsize=(8, 3))
    plt.plot(day.hours, s_over_day)
    plt.xlabel("hour of day")
    plt.ylabel("s  (circulation speed, m/s)")
    plt.title("Circulation strength swings a lot within a single day")
    plt.tight_layout()
    plt.show()

# %%
# Now across the year: the day-averaged ("frozen") s for six representative days.
frozen_s_by_month = {}
for day_of_year, label in [(14, "Jan"), (73, "Mar"), (134, "May"), (195, "Jul"), (256, "Sep"), (317, "Nov")]:
    d = simulate_representative_day(
        ROOM, HEAT_SOURCE, CLIMATE, DEFAULT_THERMOSTAT, day_of_year=day_of_year, nx=12, ny=9, dt_s=300.0
    )
    mean_field = d.temperature_fields_c.mean(axis=0)
    frozen_s_by_month[label] = buoyancy_speed_scale_from_field(d.room_mesh, mean_field, BuoyancyParams())
    print(f"{label}: frozen (day-averaged) s = {frozen_s_by_month[label]:.4f}")

s_values = list(frozen_s_by_month.values())
print(
    f"\nAcross the year: s ranges {min(s_values):.4f} .. {max(s_values):.4f} "
    f"({max(s_values) / max(min(s_values), 1e-9):.1f}x)"
)
print(
    "\n-> the baseline model freezes s at ONE of these values. Both the within-day and\n"
    "   across-year swings are the same order of magnitude -- freezing is wrong even on\n"
    "   the day it was fitted to, not just on 'far away' days."
)


# %% [markdown]
# ## 2. The FVM operator is exactly affine in `s`
#
# Because upwind advection scales *linearly* with a non-negative scalar speed, the
# whole discretized operator depends on `s` as `A(s) = A0 + s*A1` -- not
# approximately, to floating-point precision. This is the property that makes a cheap,
# well-founded reduced-basis model possible: instead of re-running the full solver to
# "see" different `s` values, the operator can be sampled directly by evaluating it at
# `s=0` and `s=1` and differencing.

# %%
room_mesh = build_room_mesh(ROOM, HEAT_SOURCE, 12, 9)
u_unit, v_unit = unit_buoyancy_velocity(room_mesh, ROOM.width_m, ROOM.height_m)
zero = np.zeros_like(u_unit)

K0, _ = assemble_operator(room_mesh, zero, zero, outdoor_temp_c=1.0)
K1, _ = assemble_operator(room_mesh, u_unit, v_unit, outdoor_temp_c=1.0)
A0 = K0.toarray()
A1 = (K1 - K0).toarray()

print(f"{'s':>8}  {'max |A(s) - (A0 + s*A1)|':>28}")
for s in (0.001, 0.02, 0.05, 0.13, 0.3):
    K_s, _ = assemble_operator(room_mesh, s * u_unit, s * v_unit, outdoor_temp_c=1.0)
    predicted = A0 + s * A1
    print(f"{s:8.3f}  {np.abs(K_s.toarray() - predicted).max():28.2e}")

print("\n-> agreement is at machine precision (~1e-13), for every s tested. This is exact,")
print("   not a curve fit -- see build_affine_operator() in solver/rb.py.")


# %% [markdown]
# ## 3. Naive (undamped) iteration on `s` does not converge -- it cycles
#
# Each timestep, the reduced model needs a *self-consistent* `s`: solve for the new
# state, recompute `s` from it, and if that doesn't match what was assumed, redo the
# solve. This mirrors what the full solver already does (`backward_euler_step`'s
# Picard iteration).
#
# `s` closes a **negative feedback loop**: more circulation mixes the heater's hot spot
# into the room faster, which *lowers* the very delta-T driving that circulation. Trace
# the plain iteration (no damping) at a stress case -- a cold room, heater near full
# power -- and watch what happens.

# %%
adaptive, trained = build_adaptive_model(ROOM, HEAT_SOURCE, nx=12, ny=9)
print(f"greedy basis size: {trained.size}")

z0 = adaptive.project(np.full(adaptive.room_mesh.mesh.n_cells, 12.0))  # a cold room
outdoor_temp_c, heater_power_w, dt_s = -2.0, HEAT_SOURCE.max_power_w, 900.0
rhs = (adaptive.forcing_boundary_r * outdoor_temp_c + adaptive.forcing_heater_r * heater_power_w).astype(
    complex
)
z_complex = z0.astype(complex)


def solve_with_s(s: float) -> np.ndarray:
    """One linear solve of the reduced model, for a GIVEN (not self-consistent) s."""
    eigenvalues, eigenvectors, eigenvectors_inv = adaptive._eigen_for_bin(adaptive._bin_index(s))
    z_modal = _step_modal_state(eigenvectors_inv @ z_complex, eigenvalues, eigenvectors_inv @ rhs, dt_s)
    return np.real(eigenvectors @ z_modal)


print("undamped iteration (relaxation = 1.0):")
s_guess = adaptive.speed_scale(z0)
undamped_trace = [s_guess]
for i in range(10):
    z_trial = solve_with_s(s_guess)
    s_guess = adaptive.speed_scale(z_trial)
    undamped_trace.append(s_guess)
    print(f"  iter {i}: s = {s_guess:.5f}")

print("\n-> s settles into an exact period-2 cycle (alternating ~0.05 / ~0.29) and never")
print("   stops. A fixed iteration count then just samples whichever phase it lands on --")
print("   which is exactly what produced a confusing sign-flipping bias across climates")
print("   before this was diagnosed.")

if HAVE_MPL:
    plt.figure(figsize=(8, 3))
    plt.plot(undamped_trace, "o-")
    plt.xlabel("iteration")
    plt.ylabel("s")
    plt.title("Undamped Picard iteration on s: a period-2 limit cycle, not convergence")
    plt.tight_layout()
    plt.show()


# %% [markdown]
# ## 4. Under-relaxation breaks the cycle
#
# Standard fix for an oscillating fixed-point iteration: blend the new estimate with
# the old one instead of replacing it outright --
# `s_new = relaxation * s_computed + (1 - relaxation) * s_old`. Try a few relaxation
# factors and watch what happens to convergence.

# %%
def relaxed_trace(relaxation: float, iterations: int = 8) -> list[float]:
    s = adaptive.speed_scale(z0)
    trace = [s]
    for _ in range(iterations):
        z_trial = solve_with_s(s)
        s_computed = adaptive.speed_scale(z_trial)
        s = relaxation * s_computed + (1 - relaxation) * s
        trace.append(s)
    return trace


for relax in (1.0, 0.7, 0.5, 0.3):
    trace = relaxed_trace(relax)
    print(f"relaxation={relax}: " + " -> ".join(f"{s:.4f}" for s in trace))

print(f"\n-> relaxation=0.5 (the default in AdaptiveReducedModel) converges cleanly in ~4-5")
print("   iterations. This was found by tracing the iteration directly, not guessed.")

if HAVE_MPL:
    plt.figure(figsize=(8, 3))
    for relax in (1.0, 0.7, 0.5, 0.3):
        plt.plot(relaxed_trace(relax), "o-", label=f"relaxation={relax}")
    plt.xlabel("iteration")
    plt.ylabel("s")
    plt.legend()
    plt.title("Under-relaxation converges; undamped (1.0) cycles forever")
    plt.tight_layout()
    plt.show()


# %% [markdown]
# ## 5. Training the greedy reduced basis
#
# The basis is trained by sampling `s` directly (frequency-domain snapshots at each
# candidate `s`) -- no full nonlinear solver run needed anywhere in this cell. Greedy
# selection repeatedly adds whichever candidate `s` the current basis represents worst,
# until the projection error is small enough.

# %%
operator = build_affine_operator(room_mesh, ROOM)
gb = greedy_basis(operator, s_max=BuoyancyParams().max_speed_m_s, tol=1e-4, max_basis_size=42)

print(f"final basis size: {gb.size}")
print(f"s values selected, in order: {[round(s, 4) for s in gb.selected_s]}")
print(f"error history: {[f'{e:.2e}' for e in gb.error_history]}")

if HAVE_MPL:
    plt.figure(figsize=(8, 3))
    plt.semilogy(gb.error_history, "o-")
    plt.xlabel("greedy iteration")
    plt.ylabel("worst-case projection error (log scale)")
    plt.title("Greedy basis error decreases monotonically")
    plt.tight_layout()
    plt.show()


# %% [markdown]
# ## 6. Baseline vs adaptive, measured against the full solver
#
# This is the core empirical claim: does the adaptive model actually track the full
# nonlinear solver better than the frozen baseline? `compare_models_across_days` runs
# the expensive full solver **once** per sample day and checks both reductions against
# that same run -- a fair, paired comparison.
#
# This cell takes roughly a minute (six full nonlinear FVM day-solves).

# %%
linearization_day = CLIMATE.linearization_day_of_year(DEFAULT_THERMOSTAT.day_target_c)
baseline_report, adaptive_report = compare_models_across_days(
    ROOM,
    HEAT_SOURCE,
    CLIMATE,
    DEFAULT_THERMOSTAT,
    sample_days=[14, 73, 134, 195, 256, 317],
    linearization_day_of_year=linearization_day,
    nx=12,
    ny=9,
    dt_s=900.0,
)

print(f"{'day':>4} {'T_out':>7} {'FOM kWh':>9} {'baseline':>10} {'adaptive':>10}")
for b, a in zip(baseline_report.points, adaptive_report.points):
    print(
        f"{b.day_of_year:4d} {b.mean_outdoor_temp_c:7.1f} {b.full_energy_kwh:9.2f} "
        f"{b.reduced_energy_kwh:10.2f} {a.reduced_energy_kwh:10.2f}"
    )

print(
    f"\nannual energy error    baseline {baseline_report.annual_energy_relative_error * 100:+6.1f}%   "
    f"adaptive {adaptive_report.annual_energy_relative_error * 100:+6.1f}%"
)
print(
    f"worst high-demand day  baseline {baseline_report.max_abs_relative_error * 100:6.1f}%   "
    f"adaptive {adaptive_report.max_abs_relative_error * 100:6.1f}%"
)

if HAVE_MPL:
    plt.figure(figsize=(8, 4))
    temps = [p.mean_outdoor_temp_c for p in baseline_report.points]
    plt.plot(temps, [p.full_energy_kwh for p in baseline_report.points], "o-", label="full FVM", color="#2166ac")
    plt.plot(
        temps, [p.reduced_energy_kwh for p in baseline_report.points], "o-", label="baseline (frozen)", color="#999999"
    )
    plt.plot(
        temps, [p.reduced_energy_kwh for p in adaptive_report.points], "o-", label="adaptive", color="#e07b39"
    )
    plt.axvline(
        CLIMATE.mean_temp_c[linearization_day], color="#888", linestyle="--", label="baseline linearization point"
    )
    plt.xlabel("daily mean outdoor temperature (°C)")
    plt.ylabel("heater energy (kWh/day)")
    plt.legend()
    plt.title(f"{CLIMATE.label}: reduced models vs. full solver")
    plt.tight_layout()
    plt.show()


# %% [markdown]
# ## 7. All four climates (baked data -- instant)
#
# The full study behind `solver/data/rom_validation.json` (generated by
# `scripts/run_rom_validation.py`) repeats the section-6 comparison across all four
# baked climates with 12 sample days each. This just reads the committed result.

# %%
baked = load_baked_validation()["locations"]
print(f"{'location':20s} {'baseline':>10} {'adaptive':>10}   {'baseline worst':>15} {'adaptive worst':>15}")
for entry in baked.values():
    b, a = entry["baseline"], entry["adaptive"]
    print(
        f"{entry['label']:20s} "
        f"{b['total_energy_relative_error'] * 100:+9.1f}% {a['total_energy_relative_error'] * 100:+9.1f}%   "
        f"{b['max_abs_relative_error'] * 100:14.1f}% {a['max_abs_relative_error'] * 100:14.1f}%"
    )

print(
    "\nFor the full prose writeup of these findings -- including why the linearisation\n"
    "point matters (heating-degree-day weighting) and why validation must run at the\n"
    "production timestep -- see CLAUDE.md and README.md at the repo root."
)
