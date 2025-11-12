"""Tests for geographic validation and diversity monitoring."""
from __future__ import annotations

from copy import deepcopy

import numpy as np

from ml_service.app.models.lightgbm_selector import LightGBMSelector
from ml_service.app.monitoring import metrics


class _ConstantModel:
    """Simple helper returning a fixed class probability distribution."""

    def __init__(self, classes, probabilities):
        self.classes_ = np.array(classes)
        self._probabilities = np.array([probabilities], dtype=float)

    def predict_proba(self, _):
        return self._probabilities


def _build_selector():
    selector = LightGBMSelector(neighbor_count=4)
    selector.model = _ConstantModel(["antenna_1", "antenna_4"], [0.05, 0.95])
    selector.calibrated_model = None
    selector.scaler = None
    selector._prediction_history = []
    return selector


def test_geographic_override_applies():
    selector = _build_selector()

    before = metrics.GEOGRAPHIC_OVERRIDES._value.get()

    features = {
        "ue_id": "ue_geo",
        "latitude": 10.0,
        "longitude": 10.0,
        "connected_to": "antenna_1",
    }

    result = selector.predict(features)

    after = metrics.GEOGRAPHIC_OVERRIDES._value.get()

    assert result["antenna_id"] == "antenna_1"
    assert result.get("fallback_reason") == "geographic_override"
    assert result.get("ml_prediction") == "antenna_4"
    assert after == before + 1


def test_low_diversity_warning_triggers_once():
    selector = LightGBMSelector(neighbor_count=1)
    selector.model = _ConstantModel(["antenna_1"], [1.0])
    selector.calibrated_model = None
    selector.scaler = None
    selector._prediction_history = []

    before = metrics.LOW_DIVERSITY_WARNINGS._value.get()

    features = {
        "ue_id": "ue_low_diversity",
        "latitude": 0.0,
        "longitude": 0.0,
        "connected_to": "antenna_1",
    }

    for _ in range(50):
        selector.predict(deepcopy(features))

    after = metrics.LOW_DIVERSITY_WARNINGS._value.get()

    assert after == before + 1
    assert selector._prediction_history
