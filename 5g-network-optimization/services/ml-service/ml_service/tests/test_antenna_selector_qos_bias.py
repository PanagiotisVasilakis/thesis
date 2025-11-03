from __future__ import annotations

import time

import numpy as np

from ml_service.app.models.antenna_selector import AntennaSelector
from ml_service.app.core.adaptive_qos import adaptive_qos_manager


def _make_selector() -> AntennaSelector:
    selector = AntennaSelector(neighbor_count=2)
    # Ensure profiler is empty for deterministic tests
    selector.antenna_profiler.reset()
    selector.qos_history.reset()
    selector.qos_bias_enabled = True
    selector.qos_bias_min_samples = 3
    selector.qos_bias_success_threshold = 0.9
    selector.qos_bias_min_multiplier = 0.3
    return selector


def test_apply_qos_bias_deprioritises_poor_antenna() -> None:
    selector = _make_selector()
    profiler = selector.antenna_profiler
    now = time.time()

    # Good antenna -- mostly passing QoS
    for _ in range(5):
        profiler.record("antA", "embb", {"latency_ms": 25.0}, True, timestamp=now - _)

    # Poor antenna -- repeated failures with high latency and low throughput
    for _ in range(5):
        profiler.record(
            "antB",
            "embb",
            {"latency_ms": 160.0, "throughput_mbps": 40.0},
            False,
            timestamp=now - _,
        )

    probs = np.array([0.45, 0.55])
    classes = np.array(["antA", "antB"])
    adjusted, details, applied = selector._apply_qos_bias(probs, classes, "embb")

    assert applied is True
    assert "antB" in details
    assert adjusted[1] < 0.55  # penalised
    assert np.isclose(adjusted.sum(), 1.0)


def test_apply_qos_bias_no_change_when_samples_insufficient() -> None:
    selector = _make_selector()
    profiler = selector.antenna_profiler
    profiler.record("antA", "embb", {"latency_ms": 30.0}, True)

    probs = np.array([0.4, 0.6])
    classes = np.array(["antA", "antB"])
    adjusted, details, applied = selector._apply_qos_bias(probs, classes, "embb")

    assert applied is False
    assert np.allclose(adjusted, probs)
    assert details == {}


def test_record_qos_feedback_updates_history_and_threshold() -> None:
    selector = _make_selector()
    selector.qos_history.reset()
    selector.antenna_profiler.reset()
    adaptive_qos_manager.reset()

    base = adaptive_qos_manager.get_required_confidence("embb", 5)

    for idx in range(6):
        selector.record_qos_feedback(
            ue_id=f"ue-{idx}",
            antenna_id="antB",
            service_type="embb",
            metrics={"latency_ms": 150.0, "throughput_mbps": 40.0},
            passed=False,
            confidence=0.6,
        )

    updated = adaptive_qos_manager.get_required_confidence("embb", 5)
    history = selector.qos_history.get_qos_history("ue-0")
    profile = selector.antenna_profiler.get_profile("antB", "embb")

    assert updated > base
    assert history["sample_count"] >= 1
    assert profile["sample_count"] >= 6

