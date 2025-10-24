"""Regression tests for QoS range validation wiring."""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

from mlops.feature_store.feature_repo import UE_METRIC_FEATURE_NAMES

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / (
    "5g-network-optimization/services/ml-service/ml_service/app/config/feature_specs.py"
)

spec = importlib.util.spec_from_file_location(
    "ml_service.app.config.feature_specs", MODULE_PATH
)
feature_specs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(feature_specs)

validate_feature_ranges = feature_specs.validate_feature_ranges


def test_feature_view_schema_includes_qos_metrics() -> None:
    """Feast schema should expose the QoS metrics for joins and retrieval."""

    qos_fields = {"latency_ms", "throughput_mbps", "packet_loss_rate"}

    assert qos_fields.issubset(UE_METRIC_FEATURE_NAMES)


def test_validate_feature_ranges_accepts_qos_metrics() -> None:
    """In-range QoS metrics should pass validation."""

    features = {
        "latency_ms": 120.0,
        "throughput_mbps": 500.0,
        "packet_loss_rate": 0.5,
    }

    # Should not raise
    validate_feature_ranges(features)


def test_validate_feature_ranges_rejects_out_of_range_qos_metrics() -> None:
    """Out-of-bound QoS metrics must fail fast."""

    features = {
        "latency_ms": -1.0,  # below minimum
        "throughput_mbps": 15000.0,  # above maximum
        "packet_loss_rate": 110.0,  # above maximum
    }

    with pytest.raises(ValueError) as exc:
        validate_feature_ranges(features)

    message = str(exc.value)
    assert "latency_ms<" in message
    assert "throughput_mbps>" in message
    assert "packet_loss_rate>" in message
