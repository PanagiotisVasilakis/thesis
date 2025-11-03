from __future__ import annotations

from typing import Dict

import pytest

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
NEF_ROOT = REPO_ROOT / "5g-network-optimization" / "services" / "nef-emulator"
sys.path.insert(0, str(NEF_ROOT))

from backend.app.app.monitoring import qos_monitor as qos_monitor_module
from backend.app.app.monitoring.qos_monitor import QoSMonitor
from backend.app.app.network.state_manager import NetworkStateManager
from backend.app.app.handover.engine import HandoverEngine
from antenna_models.models import MacroCellModel


def _make_state_manager() -> NetworkStateManager:
    nsm = NetworkStateManager()
    nsm.antenna_list = {
        "antA": MacroCellModel("antA", (0.0, 0.0, 15.0), 2.6e9, tx_power_dbm=46),
        "antB": MacroCellModel("antB", (250.0, 0.0, 15.0), 2.6e9, tx_power_dbm=43),
    }
    nsm.ue_states = {
        "ue-1": {
            "position": (50.0, 0.0, 1.5),
            "speed": 5.0,
            "connected_to": "antA",
        }
    }
    return nsm


def test_qos_monitor_sliding_window(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = {"value": 0.0}

    def fake_monotonic() -> float:
        return clock["value"]

    monkeypatch.setattr(qos_monitor_module.time, "monotonic", fake_monotonic)

    monitor = QoSMonitor(window_seconds=1.0, max_samples=5)

    monitor.update_qos_metrics(
        "ue-1",
        {
            "latency_ms": 10.0,
            "jitter_ms": 1.0,
            "throughput_mbps": 150.0,
            "packet_loss_rate": 0.1,
        },
    )

    clock["value"] = 0.5
    monitor.update_qos_metrics(
        "ue-1",
        {
            "latency_ms": 12.0,
            "jitter_ms": 1.3,
            "throughput_mbps": 145.0,
            "packet_loss_rate": 0.2,
        },
    )

    clock["value"] = 1.6  # prune first sample (> window)
    monitor.update_qos_metrics(
        "ue-1",
        {
            "latency_ms": 18.0,
            "jitter_ms": 2.0,
            "throughput_mbps": 120.0,
            "packet_loss_rate": 0.8,
        },
    )

    samples = monitor.get_recent_samples("ue-1")
    assert len(samples) == 1  # oldest samples pruned; min_samples keeps latest

    aggregates = monitor.get_qos_metrics("ue-1")
    assert aggregates is not None
    assert aggregates["sample_count"] == 1
    assert pytest.approx(aggregates["latest"]["latency_ms"], rel=1e-6) == 18.0


def test_state_manager_includes_observed_qos() -> None:
    nsm = _make_state_manager()

    fv = nsm.get_feature_vector("ue-1")

    observed = fv.get("observed_qos")
    assert observed is not None
    assert observed["sample_count"] >= 1
    latest = observed["latest"]
    assert latest["latency_ms"] > 0
    assert latest["throughput_mbps"] > 0


def test_handover_engine_sends_observed_qos(monkeypatch: pytest.MonkeyPatch) -> None:
    nsm = _make_state_manager()

    captured: Dict[str, Dict[str, float]] = {}

    class DummyResponse:
        def __init__(self, payload: Dict[str, object]):
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> Dict[str, object]:
            return self._payload

    def fake_post(url: str, json: Dict[str, object], timeout: float):  # type: ignore[override]
        captured["payload"] = json
        return DummyResponse(
            {
                "predicted_antenna": "antA",
                "confidence": 0.95,
                "qos_compliance": {
                    "service_priority_ok": True,
                    "required_confidence": 0.5,
                    "observed_confidence": 0.95,
                    "details": {
                        "service_type": "embb",
                        "service_priority": 5,
                        "latency_requirement_ms": 25.0,
                        "throughput_requirement_mbps": 120.0,
                        "reliability_pct": 99.0,
                    },
                },
            }
        )

    monkeypatch.setattr(
        "backend.app.app.handover.engine.requests.post",
        fake_post,
    )

    engine = HandoverEngine(
        state_mgr=nsm,
        use_ml=True,
        ml_service_url="http://ml-service",
        confidence_threshold=0.1,
    )

    result = engine.decide_and_apply("ue-1")

    assert result is not None
    assert "payload" in captured
    observed_payload = captured["payload"].get("observed_qos")
    assert observed_payload is not None
    assert set(observed_payload.keys()).issuperset(
        {"latency_ms", "throughput_mbps", "jitter_ms", "packet_loss_rate"}
    )

