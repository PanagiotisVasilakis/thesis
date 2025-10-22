"""Integration tests for the MLOps NEF QoS collector."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

# Ensure the repository root is on ``sys.path`` when running in isolated CI
# environments where a third-party ``mlops`` namespace might take precedence.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mlops.data_pipeline.nef_collector import (
    NEFQoSCollector,
    NEFAPIError,
    QoSRequirements,
    QoSValidationError,
)


class DummyNEFClient:
    """Test double that simulates the NEF API client."""

    def __init__(self, responses: Dict[str, Any]) -> None:
        self._responses = responses

    def get_qos_requirements(self, ue_id: str) -> Dict[str, Any]:
        if isinstance(self._responses.get(ue_id), Exception):
            raise self._responses[ue_id]
        return self._responses[ue_id]


def test_qos_requirements_from_payload_variants() -> None:
    payload = {
        "serviceType": "URLLC ",
        "servicePriority": "3",
        "qosRequirements": {
            "latency_ms": "12.5",
            "throughput": 150,
            "reliabilityPct": 99.99,
            "jitterMs": "5",
        },
    }

    qos = QoSRequirements.from_payload("ue-1", payload)

    assert qos.service_type == "URLLC"
    assert qos.service_priority == 3
    assert qos.thresholds == {
        "latency_requirement_ms": pytest.approx(12.5),
        "throughput_requirement_mbps": pytest.approx(150.0),
        "reliability_pct": pytest.approx(99.99),
        "jitter_ms": pytest.approx(5.0),
    }


def test_qos_validation_requires_numeric_thresholds() -> None:
    payload = {"service_type": "EMBB"}

    with pytest.raises(QoSValidationError):
        QoSRequirements.from_payload("ue-7", payload)


def test_collector_returns_validated_records(caplog: pytest.LogCaptureFixture) -> None:
    client = DummyNEFClient(
        {
            "ue-1": {
                "service_type": "EMBB",
                "service_priority": 1,
                "requirements": {
                    "latencyRequirementMs": 20,
                    "throughputRequirementMbps": 75,
                },
            },
            "ue-2": {
                "serviceType": "URLLC",
                "qos_requirements": {
                    "latency": 5,
                    "reliability": 99.9,
                },
            },
        }
    )

    collector = NEFQoSCollector(client, logger=logging.getLogger("test"))

    records = collector.collect_for_ues(["ue-1", "ue-2"])

    assert len(records) == 2
    assert {record["ue_id"] for record in records} == {"ue-1", "ue-2"}

    first = next(record for record in records if record["ue_id"] == "ue-1")
    assert first["service_type"] == "EMBB"
    assert first["qos_requirements"]["throughput_requirement_mbps"] == pytest.approx(75.0)

    second = next(record for record in records if record["ue_id"] == "ue-2")
    assert second["service_type"] == "URLLC"
    assert second["qos_requirements"]["reliability_pct"] == pytest.approx(99.9)

    # Ensure the collector timestamps the record
    for record in records:
        assert "T" in record["collected_at"]


def test_collector_logs_and_skips_invalid_payload(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)

    client = DummyNEFClient(
        {
            "ue-3": {},
            "ue-4": {"requirements": {"latencyRequirementMs": "invalid"}},
        }
    )

    collector = NEFQoSCollector(client, logger=logging.getLogger("test.invalid"))

    records = collector.collect_for_ues(["ue-3", "ue-4"])

    assert records == []
    assert "invalid QoS payload" in caplog.text


def test_collector_handles_nef_api_error(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.ERROR)

    client = DummyNEFClient({"ue-5": NEFAPIError("service unavailable")})

    collector = NEFQoSCollector(client, logger=logging.getLogger("test.error"))

    result = collector.collect_for_ue("ue-5")

    assert result is None
    assert "service unavailable" in caplog.text

