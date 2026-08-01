import numpy as np
import pytest

from solver.climate import get_climate
from solver.fvm import BuoyancyParams
from solver.geometry import HeatSource, Room, WallElement, WallElementType, build_room_mesh
from solver.materials import DEFAULT_THERMOSTAT, suggested_heater_power_w
from solver.rb import build_affine_operator, greedy_basis, projection_error, snapshots_at


def _reference_room_source_climate():
    room = Room(
        width_m=4.0,
        height_m=3.0,
        walls={
            "north": [],
            "east": [WallElement(WallElementType.WINDOW, offset_m=0.9, length_m=1.2)],
            "south": [WallElement(WallElementType.DOOR, offset_m=1.5, length_m=0.9)],
            "west": [],
        },
    )
    climate = get_climate("berlin")
    heat_source = HeatSource(
        x_m=0.4, y_m=1.5, max_power_w=suggested_heater_power_w(room, climate, DEFAULT_THERMOSTAT)
    )
    return room, heat_source, climate


def test_operator_is_affine_in_the_circulation_strength():
    # The entire RB design rests on this. A(s) = a0 + s*a1 exactly (not
    # approximately) because upwind advection scales linearly with a non-negative
    # scalar speed -- verified here to floating-point precision, not just "close".
    room, heat_source, _ = _reference_room_source_climate()
    room_mesh = build_room_mesh(room, heat_source, 10, 8)
    operator = build_affine_operator(room_mesh, room)

    for s in (0.001, 0.02, 0.05, 0.13, 0.3):
        predicted = operator.a0 + s * operator.a1
        assert np.abs(operator.at(s) - predicted).max() < 1e-9


def test_greedy_basis_is_orthonormal():
    room, heat_source, _ = _reference_room_source_climate()
    room_mesh = build_room_mesh(room, heat_source, 10, 8)
    operator = build_affine_operator(room_mesh, room)

    trained = greedy_basis(operator, s_max=0.3, tol=1e-5, max_basis_size=30)

    gram = trained.basis.T @ trained.basis
    assert np.allclose(gram, np.eye(trained.size), atol=1e-8)


def test_greedy_error_decreases_monotonically():
    room, heat_source, _ = _reference_room_source_climate()
    room_mesh = build_room_mesh(room, heat_source, 10, 8)
    operator = build_affine_operator(room_mesh, room)

    trained = greedy_basis(operator, s_max=0.3, tol=1e-6, max_basis_size=30)

    assert len(trained.error_history) >= 2
    diffs = np.diff(trained.error_history)
    assert np.all(diffs <= 1e-9), "greedy error history must be non-increasing"


def test_greedy_basis_generalizes_out_of_sample():
    # The basis is trained on a discrete set of s values; it must still represent
    # s values it never saw, since the online model evaluates s continuously.
    room, heat_source, _ = _reference_room_source_climate()
    room_mesh = build_room_mesh(room, heat_source, 10, 8)
    operator = build_affine_operator(room_mesh, room)

    trained = greedy_basis(operator, s_max=0.3, tol=1e-5, max_basis_size=30)
    trained_s = set(trained.training_s)

    out_of_sample = [s for s in (0.003, 0.017, 0.042, 0.071, 0.15) if s not in trained_s]
    assert out_of_sample
    for s in out_of_sample:
        assert projection_error(trained.basis, snapshots_at(operator, s)) < 1e-2


def test_projection_error_of_empty_basis_is_worst_case():
    room, heat_source, _ = _reference_room_source_climate()
    room_mesh = build_room_mesh(room, heat_source, 8, 6)
    operator = build_affine_operator(room_mesh, room)

    empty_basis = np.zeros((operator.n_cells, 0))
    assert projection_error(empty_basis, snapshots_at(operator, 0.05)) == pytest.approx(1.0)


def test_undamped_picard_iteration_on_s_does_not_converge():
    # Regression pin for a real bug: `s` closes a negative-feedback loop (more
    # circulation mixes away the delta-T driving it) steep enough that plain
    # fixed-point iteration (relaxation=1.0) settles into an exact period-2 limit
    # cycle instead of converging. This is *why* AdaptiveReducedModel.step uses
    # under-relaxation -- if this test ever starts failing (i.e. undamped iteration
    # converges), the relaxation logic may have become unnecessary and worth
    # revisiting, not just deleting.
    from solver.mor import _step_modal_state, build_adaptive_model

    room, heat_source, _ = _reference_room_source_climate()
    model, _ = build_adaptive_model(room, heat_source, nx=12, ny=9)

    z0 = model.project(np.full(model.room_mesh.mesh.n_cells, 12.0))  # cold room
    outdoor_temp_c, heater_power_w, dt_s = -2.0, heat_source.max_power_w, 900.0
    rhs = (model.forcing_boundary_r * outdoor_temp_c + model.forcing_heater_r * heater_power_w).astype(complex)
    z_complex = z0.astype(complex)

    def solve_with_s(s: float) -> np.ndarray:
        eigenvalues, eigenvectors, eigenvectors_inv = model._eigen_for_bin(model._bin_index(s))
        z_modal = _step_modal_state(eigenvectors_inv @ z_complex, eigenvalues, eigenvectors_inv @ rhs, dt_s)
        return np.real(eigenvectors @ z_modal)

    s_values = [model.speed_scale(z0)]
    z = z0
    for _ in range(10):
        z = solve_with_s(s_values[-1])
        s_values.append(model.speed_scale(z))

    # A converged iteration would have the last few values nearly equal; a period-2
    # cycle instead has s[i] far from s[i+1] but close to s[i+2].
    tail = s_values[-4:]
    assert abs(tail[0] - tail[2]) < 1e-3
    assert abs(tail[1] - tail[3]) < 1e-3
    assert abs(tail[0] - tail[1]) > 0.05, "expected the undamped iteration to still be cycling, not converged"


def test_relaxed_picard_iteration_converges_where_undamped_does_not():
    from solver.mor import build_adaptive_model

    room, heat_source, _ = _reference_room_source_climate()
    model, _ = build_adaptive_model(room, heat_source, nx=12, ny=9, picard_relaxation=0.5)

    z0 = model.project(np.full(model.room_mesh.mesh.n_cells, 12.0))
    z1 = model.step(z0, outdoor_temp_c=-2.0, heater_power_w=heat_source.max_power_w, dt_s=900.0)
    z2 = model.step(z0, outdoor_temp_c=-2.0, heater_power_w=heat_source.max_power_w, dt_s=900.0)

    # Deterministic: solving the same step twice from the same state must agree.
    assert np.allclose(z1, z2)

    # And it should have actually settled near the fixed point found by direct
    # relaxed iteration (~0.116, per the investigation behind this fix), not be
    # sitting on one side of the undamped cycle (~0.048 or ~0.287).
    assert 0.08 < model.speed_scale(z1) < 0.16
