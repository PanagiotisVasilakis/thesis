"""Unit tests for path loss related models.

The previous version of this file generated several plots which slowed the test
suite considerably.  These tests focus purely on the numeric behaviour of the
models so that they run quickly.
"""
from math import log10
import numpy as np

from rf_models.path_loss import ABGPathLossModel, CloseInPathLossModel, FastFading


def test_abg_against_reference():
    """Validate ABG path loss calculation against a hand computed reference."""
    model = ABGPathLossModel()
    pl = model.calculate_path_loss(100, 3.5, include_shadowing=False)
    expected = 10 * model.alpha * log10(100) + model.beta + 10 * model.gamma * log10(3.5)
    assert abs(pl - expected) < 1e-6


def test_ci_against_reference():
    """Validate Close-In path loss calculation against a hand computed reference."""
    model = CloseInPathLossModel()
    pl = model.calculate_path_loss(100, 3.5, include_shadowing=False)
    expected = 32.4 + 10 * model.n * log10(100) + 20 * log10(3.5)
    assert abs(pl - expected) < 1e-6


def test_fast_fading_statistics():
    """Fast fading output should have zero mean and realistic variance."""
    ff = FastFading(carrier_frequency=3.5)
    samples = ff.generate_fading(5 / 3.6, duration=2.0, time_step=0.01)
    mean = float(np.mean(samples))
    std = float(np.std(samples))
    assert abs(mean) < 1e-6
    assert 8.0 <= std <= 11.0
