"""Tests covering LightGBM selector training safeguards."""
from __future__ import annotations

from copy import deepcopy

import pytest

from ml_service.app.models.lightgbm_selector import LightGBMSelector
from ml_service.app.utils.synthetic_data import generate_synthetic_training_data
from ml_service.app.utils.exception_handler import ModelError


@pytest.fixture(scope="module")
def balanced_training_data():
    return generate_synthetic_training_data(
        num_samples=400,
        num_antennas=4,
        balance_classes=True,
        edge_case_ratio=0.2,
        seed=20251109,
    )


def _train(selector: LightGBMSelector, data, *, validation_split=0.2):
    return selector.train(
        data,
        validation_split=validation_split,
        early_stopping_rounds=10,
    )


def test_class_weights_recorded(balanced_training_data):
    selector = LightGBMSelector(
        neighbor_count=4,
        n_estimators=50,
        max_depth=8,
        learning_rate=0.1,
    )
    metrics = _train(selector, balanced_training_data)

    weights = metrics.get("class_weights")
    assert weights, "Expected class weight map in training metrics"
    assert all(abs(weight - 1.0) < 0.05 for weight in weights.values())
    assert metrics.get("imbalance_ratio", 0.0) <= 1.5
    assert metrics.get("unique_predictions", 0) >= 3


def test_collapse_guard_raises_model_error(balanced_training_data):
    collapsed = deepcopy(balanced_training_data)
    for sample in collapsed:
        sample["optimal_antenna"] = "antenna_1"

    selector = LightGBMSelector(
        neighbor_count=1,
        n_estimators=25,
        max_depth=4,
        learning_rate=0.1,
    )

    with pytest.raises(ModelError):
        _train(selector, collapsed, validation_split=0.0)


def test_confidence_calibration_enabled(balanced_training_data):
    selector = LightGBMSelector(
        neighbor_count=4,
        n_estimators=60,
        max_depth=10,
        learning_rate=0.1,
    )
    metrics = _train(selector, balanced_training_data, validation_split=0.25)

    assert metrics.get("confidence_calibrated") is True
    assert metrics.get("calibration_method") == selector.calibration_method
    assert metrics.get("val_accuracy", 0.0) >= 0.8
    assert metrics.get("val_f1", 0.0) >= 0.8
