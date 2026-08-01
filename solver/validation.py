"""Quantify where the reduced model is trustworthy.

Two reductions live in `solver/mor.py`: a frozen single-point baseline, and an
adaptive greedy-RB model that recomputes the buoyancy nonlinearity every step. The
adaptive model exists because it measurably beats the baseline -- this module is what
measures that, rather than asserting it. Building a surrogate is the easy half;
knowing its validity envelope (and proving the fancier one actually earns its keep)
is the half that decides whether you can trust the answer.

Each sample runs the full nonlinear FVM once per day and compares both reductions
against that same run, from the same initial condition, with the same controller.
Full-FVM days are expensive, so this is meant for offline studies
(`scripts/run_rom_validation.py`) and regression tests, not per-request work.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from solver.climate import ClimateLocation
from solver.fvm import DayResult, simulate_representative_day
from solver.geometry import HeatSource, Room
from solver.materials import ThermostatSettings
from solver.mor import (
    AdaptiveReducedModel,
    ReducedModel,
    build_adaptive_model,
    build_reduced_model_from_day,
    simulate_reduced_days,
)


_BAKED_PATH = Path(__file__).resolve().parent / "data" / "rom_validation.json"


@lru_cache(maxsize=1)
def load_baked_validation() -> dict:
    """Validation results measured offline by `scripts/run_rom_validation.py`.

    Baked rather than computed per request because each point needs a full-FVM day.
    These characterise the reference room, so they describe the method rather than
    the user's current geometry -- the UI must say so."""
    return json.loads(_BAKED_PATH.read_text())


@dataclass(frozen=True)
class ValidationPoint:
    day_of_year: int
    mean_outdoor_temp_c: float
    full_energy_kwh: float
    reduced_energy_kwh: float

    @property
    def absolute_error_kwh(self) -> float:
        return self.reduced_energy_kwh - self.full_energy_kwh

    @property
    def relative_error(self) -> float:
        """Signed relative error. Returns 0.0 when the full model uses no heat at all
        (a warm summer day), where a ratio would be meaningless rather than large."""
        if self.full_energy_kwh <= 1e-9:
            return 0.0
        return self.absolute_error_kwh / self.full_energy_kwh


@dataclass
class ValidationReport:
    model_label: str  # "baseline" or "adaptive" -- which reduction these points are for
    linearization_day_of_year: int
    points: list[ValidationPoint]

    def significant_points(self, fraction_of_peak: float = 0.1) -> list[ValidationPoint]:
        """Days carrying real heating demand.

        Relative error is unstable to the point of meaninglessness on days that need
        almost no heat -- 0.01 kWh predicted against 0.005 kWh actual is a "100%
        error" that represents watt-hours. Relative-error statistics are therefore
        reported over days above a fraction of the peak daily demand; every day still
        counts toward the total-energy error below.
        """
        if not self.points:
            return []
        peak_kwh = max(p.full_energy_kwh for p in self.points)
        threshold_kwh = peak_kwh * fraction_of_peak
        return [p for p in self.points if p.full_energy_kwh >= threshold_kwh]

    @property
    def max_abs_relative_error(self) -> float:
        return max((abs(p.relative_error) for p in self.significant_points()), default=0.0)

    @property
    def mean_abs_relative_error(self) -> float:
        errors = [abs(p.relative_error) for p in self.significant_points()]
        return float(np.mean(errors)) if errors else 0.0

    @property
    def max_abs_error_kwh(self) -> float:
        """Worst single-day error in absolute terms -- meaningful on every day,
        including the near-zero-demand ones."""
        return max((abs(p.absolute_error_kwh) for p in self.points), default=0.0)

    @property
    def annual_energy_relative_error(self) -> float:
        """Error in the quantity that actually matters -- total energy across all
        sampled days. The reduction is most accurate on cold, high-demand days and
        worst on mild, low-demand ones, so errors are small exactly where the energy
        is: this is typically far below the worst single-day error."""
        full_total = sum(p.full_energy_kwh for p in self.points)
        if full_total <= 1e-9:
            return 0.0
        return (sum(p.reduced_energy_kwh for p in self.points) - full_total) / full_total


def _reduced_day_energy_kwh(
    reduced_model: ReducedModel | AdaptiveReducedModel,
    heat_source: HeatSource,
    climate: ClimateLocation,
    thermostat: ThermostatSettings,
    day_of_year: int,
    initial_temp_c: float,
    dt_s: float,
) -> float:
    day = simulate_reduced_days(
        reduced_model,
        heat_source,
        climate,
        thermostat,
        initial_temp_c=initial_temp_c,
        dt_s=dt_s,
        n_days=1,
        start_day_of_year=day_of_year,
    )[0]
    return day.energy_kwh(dt_s)


def _build_report(
    model_label: str,
    linearization_day_of_year: int,
    model: ReducedModel | AdaptiveReducedModel,
    heat_source: HeatSource,
    climate: ClimateLocation,
    thermostat: ThermostatSettings,
    fom_days: dict[int, DayResult],
    initial_temp_c: float,
    dt_s: float,
) -> ValidationReport:
    points: list[ValidationPoint] = []
    for day_of_year, full_day in fom_days.items():
        full_energy_kwh = float(np.sum(full_day.heater_power_w) * dt_s / 3600.0 / 1000.0)
        reduced_energy_kwh = _reduced_day_energy_kwh(
            model, heat_source, climate, thermostat, day_of_year, initial_temp_c, dt_s
        )
        mean_outdoor_temp_c = float(
            np.mean([climate.outdoor_temp_c(day_of_year * 24.0 + h) for h in full_day.hours])
        )
        points.append(
            ValidationPoint(
                day_of_year=day_of_year,
                mean_outdoor_temp_c=mean_outdoor_temp_c,
                full_energy_kwh=full_energy_kwh,
                reduced_energy_kwh=reduced_energy_kwh,
            )
        )
    return ValidationReport(
        model_label=model_label, linearization_day_of_year=linearization_day_of_year, points=points
    )


def validate_across_days(
    room: Room,
    heat_source: HeatSource,
    climate: ClimateLocation,
    thermostat: ThermostatSettings,
    sample_days: list[int],
    linearization_day_of_year: int = 14,
    nx: int = 12,
    ny: int = 9,
    dt_s: float = 900.0,
    initial_temp_c: float = 18.0,
    n_modes: int = 10,
    linearization_day: DayResult | None = None,
) -> ValidationReport:
    """Compare the frozen single-point baseline against the full solver across
    `sample_days`, with the reduction linearized about `linearization_day_of_year`."""
    if linearization_day is None:
        linearization_day = simulate_representative_day(
            room, heat_source, climate, thermostat,
            day_of_year=linearization_day_of_year, nx=nx, ny=ny, dt_s=dt_s,
            initial_temp_c=initial_temp_c,
        )
    reduced_model = build_reduced_model_from_day(linearization_day, room, n_modes)

    fom_days = {
        day_of_year: simulate_representative_day(
            room, heat_source, climate, thermostat,
            day_of_year=day_of_year, nx=nx, ny=ny, dt_s=dt_s, initial_temp_c=initial_temp_c,
        )
        for day_of_year in sample_days
    }
    return _build_report(
        "baseline", linearization_day_of_year, reduced_model,
        heat_source, climate, thermostat, fom_days, initial_temp_c, dt_s,
    )


def compare_models_across_days(
    room: Room,
    heat_source: HeatSource,
    climate: ClimateLocation,
    thermostat: ThermostatSettings,
    sample_days: list[int],
    linearization_day_of_year: int,
    nx: int = 12,
    ny: int = 9,
    dt_s: float = 900.0,
    initial_temp_c: float = 18.0,
    n_modes: int = 10,
) -> tuple[ValidationReport, ValidationReport]:
    """Compare both reductions -- frozen baseline and adaptive greedy-RB -- against
    the full solver on the same days, running the (expensive) full solver only once
    per day rather than once per model. Returns `(baseline_report, adaptive_report)`.
    """
    linearization_day = simulate_representative_day(
        room, heat_source, climate, thermostat,
        day_of_year=linearization_day_of_year, nx=nx, ny=ny, dt_s=dt_s,
        initial_temp_c=initial_temp_c,
    )
    baseline = build_reduced_model_from_day(linearization_day, room, n_modes)
    adaptive, _ = build_adaptive_model(room, heat_source, nx=nx, ny=ny)

    fom_days = {
        day_of_year: (
            linearization_day
            if day_of_year == linearization_day_of_year
            else simulate_representative_day(
                room, heat_source, climate, thermostat,
                day_of_year=day_of_year, nx=nx, ny=ny, dt_s=dt_s, initial_temp_c=initial_temp_c,
            )
        )
        for day_of_year in sample_days
    }

    baseline_report = _build_report(
        "baseline", linearization_day_of_year, baseline,
        heat_source, climate, thermostat, fom_days, initial_temp_c, dt_s,
    )
    adaptive_report = _build_report(
        "adaptive", linearization_day_of_year, adaptive,
        heat_source, climate, thermostat, fom_days, initial_temp_c, dt_s,
    )
    return baseline_report, adaptive_report
