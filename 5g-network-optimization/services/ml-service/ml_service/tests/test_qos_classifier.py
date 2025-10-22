"""Unit tests for :mod:`ml_service.app.qos.classifier`."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ml_service.app.qos import QoSServiceClassifier


def write_config(tmp_path: Path) -> Path:
    config = {
        "qos_profiles": {
            "default": {
                "metrics": {
                    "latency": {"weight": 0.6, "objective": "min", "threshold": 20.0},
                    "throughput": {"weight": 0.4, "objective": "max", "threshold": 100.0},
                },
                "minimum_score": 0.7,
            },
            "embb": {
                "metrics": {
                    "latency": {"weight": 0.5, "objective": "min", "threshold": 15.0},
                    "throughput": {
                        "weight": 0.5,
                        "objective": "max",
                        "threshold": 150.0,
                    },
                },
            },
            "urllc": {
                "metrics": {
                    "latency": {"weight": 0.5, "objective": "min", "threshold": 10.0},
                    "reliability": {
                        "weight": 0.5,
                        "objective": "max",
                        "threshold": 99.9,
                        "tolerance": 0.05,
                    },
                },
                "minimum_score": 0.9,
            },
        }
    }
    path = tmp_path / "features.yaml"
    path.write_text(yaml.safe_dump(config))
    return path


def test_score_uses_weighted_normalization(tmp_path: Path) -> None:
    config_path = write_config(tmp_path)
    classifier = QoSServiceClassifier(config_path=str(config_path))

    score, breakdown = classifier.score(
        "embb", {"latency": 20.0, "throughput": 120.0}
    )

    # latency exceeds threshold -> normalized 15/20 = 0.75; throughput 120/150 = 0.8
    expected_score = 0.5 * 0.75 + 0.5 * 0.8
    assert pytest.approx(score) == expected_score
    assert breakdown["latency"]["normalized_score"] == pytest.approx(0.75)
    assert breakdown["throughput"]["normalized_score"] == pytest.approx(0.8)


def test_compliance_honors_tolerance_and_mandatory(tmp_path: Path) -> None:
    config_path = write_config(tmp_path)
    classifier = QoSServiceClassifier(config_path=str(config_path))

    metrics = {"latency": 9.0, "reliability": 99.86}
    compliant, details = classifier.evaluate_compliance("urllc", metrics)

    assert compliant
    assert details["reliability"]["compliant"] is True

    metrics = {"latency": 25.0, "reliability": 99.0}
    compliant, details = classifier.evaluate_compliance("urllc", metrics)
    assert not compliant
    assert details["latency"]["compliant"] is False
    assert details["reliability"]["compliant"] is False


def test_missing_metric_raises(tmp_path: Path) -> None:
    config_path = write_config(tmp_path)
    classifier = QoSServiceClassifier(config_path=str(config_path))

    with pytest.raises(ValueError):
        classifier.score("embb", {"latency": 10.0})

    with pytest.raises(ValueError):
        classifier.evaluate_compliance("embb", {"latency": 10.0})


def test_assess_combines_score_and_compliance(tmp_path: Path) -> None:
    config_path = write_config(tmp_path)
    classifier = QoSServiceClassifier(config_path=str(config_path))

    result = classifier.assess("default", {"latency": 18.0, "throughput": 80.0})

    assert "score" in result and "compliance_details" in result
    assert result["breakdown"]["latency"]["normalized_score"] == pytest.approx(1.0)
    assert not result["compliant"]
    assert result["compliance_details"]["_minimum_score"]["compliant"] is True

