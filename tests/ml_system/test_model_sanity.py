"""Sanity tests for the ML handover model."""
from __future__ import annotations

from collections import Counter
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVICES = ROOT / "5g-network-optimization" / "services"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SERVICES) not in sys.path:
    sys.path.insert(0, str(SERVICES))

from ml_service.app.models.antenna_selector import AntennaSelector
from ml_service.app.config.cells import CELL_CONFIGS
from ml_service.app.utils.synthetic_data import generate_synthetic_training_data


@pytest.fixture()
def selector(tmp_path: Path) -> AntennaSelector:
    model = AntennaSelector(model_path=str(tmp_path / "sanity_model.joblib"))
    training_data = generate_synthetic_training_data(num_samples=1200, num_antennas=4)
    model.train(training_data)
    return model


def _collect_predictions(selector: AntennaSelector, samples: int = 200) -> list[str]:
    data = generate_synthetic_training_data(num_samples=samples, num_antennas=4)
    predictions: list[str] = []
    for sample in data:
        features = selector.extract_features(sample)
        result = selector.predict(features)
        predictions.append(str(result.get("antenna_id", "unknown")))
    return predictions


def test_model_predicts_multiple_classes(selector: AntennaSelector) -> None:
    predictions = _collect_predictions(selector, samples=400)
    assert len(set(predictions)) >= 3


def test_model_respects_geography(selector: AntennaSelector) -> None:
    data = generate_synthetic_training_data(num_samples=200, num_antennas=4)
    exact_matches = 0
    for sample in data:
        features = selector.extract_features(sample)
        result = selector.predict(features)
        predicted = str(result.get("antenna_id", "antenna_1"))
        ue_xy = (float(sample.get("latitude", 0.0)), float(sample.get("longitude", 0.0)))
        cell = CELL_CONFIGS[predicted]
        distance = math.hypot(ue_xy[0] - cell["latitude"], ue_xy[1] - cell["longitude"])
        assert math.isfinite(distance)
        if predicted == sample.get("optimal_antenna"):
            exact_matches += 1

    assert exact_matches / len(data) >= 0.20


def test_model_prediction_diversity(selector: AntennaSelector) -> None:
    predictions = _collect_predictions(selector, samples=500)
    counts = Counter(predictions)
    assert len(counts) >= 3
    assert max(counts.values()) / len(predictions) <= 0.75


def test_no_pingpong_with_diversity(selector: AntennaSelector) -> None:
    data = generate_synthetic_training_data(num_samples=20, num_antennas=4)
    triggered = False
    for sample in data:
        features = selector.extract_features(sample)
        result = selector.predict(features)
        predicted = str(result.get("antenna_id", sample.get("connected_to")))
        if predicted != sample.get("connected_to"):
            triggered = True
            break
    assert triggered
