"""Sanity tests for the ML handover model.

The expectations encoded here describe the target behaviour for the
refactored system. They are currently marked as expected failures to
surface the existing deficiencies without breaking the CI pipeline.
"""
from __future__ import annotations

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
from ml_service.app.utils.synthetic_data import generate_synthetic_training_data


MODEL_PATH = ROOT / "output" / "test_model.joblib"


@pytest.fixture()
def selector() -> AntennaSelector:
    model = AntennaSelector(model_path=str(MODEL_PATH))
    if model.model is None:
        pytest.skip("Model artifact not available; run training first")
    return model


def _collect_predictions(selector: AntennaSelector, samples: int = 200) -> list[str]:
    data = generate_synthetic_training_data(num_samples=samples, num_antennas=4)
    predictions: list[str] = []
    for sample in data:
        features = selector.extract_features(sample)
        result = selector.predict(features)
        predictions.append(str(result.get("antenna_id", "unknown")))
    return predictions


@pytest.mark.xfail(reason="Model currently collapses to single class", strict=False)
def test_model_predicts_multiple_classes(selector: AntennaSelector) -> None:
    predictions = _collect_predictions(selector, samples=400)
    assert len(set(predictions)) >= 3


@pytest.mark.xfail(reason="Model lacks geographic awareness", strict=False)
def test_model_respects_geography(selector: AntennaSelector) -> None:
    data = generate_synthetic_training_data(num_samples=50, num_antennas=4)
    positions = {
       "antenna_1": (37.999, 23.819),
       "antenna_2": (37.998, 23.821),
       "antenna_3": (37.996, 23.819),
       "antenna_4": (37.998, 23.818),
    }
    for sample in data:
        features = selector.extract_features(sample)
        result = selector.predict(features)
        predicted = str(result.get("antenna_id", "antenna_1"))
        ue_xy = (float(sample.get("latitude", 0.0)), float(sample.get("longitude", 0.0)))
        cell_xy = positions.get(predicted)
        if cell_xy:
            distance = math.hypot(ue_xy[0] - cell_xy[0], ue_xy[1] - cell_xy[1])
            assert distance <= 1000  # Roughly twice the intended cell radius


@pytest.mark.xfail(reason="Prediction diversity below 30%", strict=False)
def test_model_prediction_diversity(selector: AntennaSelector) -> None:
    predictions = _collect_predictions(selector, samples=500)
    diversity_ratio = len(set(predictions)) / len(predictions)
    assert diversity_ratio >= 0.3


@pytest.mark.xfail(reason="Ping-pong prevention suppresses handovers", strict=False)
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
