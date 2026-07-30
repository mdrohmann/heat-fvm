"""Smoke test: the solver package and its modules import cleanly."""

import solver.controller
import solver.fvm
import solver.geometry
import solver.materials
import solver.mor


def test_modules_import():
    assert solver.geometry
    assert solver.materials
    assert solver.fvm
    assert solver.controller
    assert solver.mor
