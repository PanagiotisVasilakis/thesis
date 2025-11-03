from __future__ import annotations

import time

import pytest

from ml_service.app.data.qos_tracker import QoSHistoryTracker


def test_tracker_collects_statistics() -> None:
    tracker = QoSHistoryTracker(window_seconds=60.0, max_samples=10)
    now = time.time()

    tracker.record(
        ue_id="ue-1",
        service_type="embb",
        metrics={"latency_ms": 12.0, "throughput_mbps": 140.0},
        passed=True,
        timestamp=now - 10,
    )
    tracker.record(
        ue_id="ue-1",
        service_type="embb",
        metrics={"latency_ms": 18.0, "throughput_mbps": 120.0},
        passed=False,
        timestamp=now - 5,
    )
    tracker.record(
        ue_id="ue-1",
        service_type="embb",
        metrics={"latency_ms": 16.0, "throughput_mbps": 135.0},
        passed=True,
        timestamp=now,
    )

    stats = tracker.get_qos_history("ue-1")
    assert stats["sample_count"] == 3
    assert stats["violation_count"] == 1
    assert stats["success_rate"] == pytest.approx(2 / 3, rel=1e-6)
    metrics = stats["metrics"]
    assert pytest.approx(metrics["latency_ms"]["avg"], rel=1e-6) == (12.0 + 16.0 + 18.0) / 3
    assert metrics["throughput_mbps"]["min"] == 120.0


def test_tracker_prunes_outside_window() -> None:
    tracker = QoSHistoryTracker(window_seconds=5.0, max_samples=5)
    now = time.time()

    tracker.record("ue-1", "embb", {"latency_ms": 10.0}, True, timestamp=now - 20)
    tracker.record("ue-1", "embb", {"latency_ms": 12.0}, True, timestamp=now - 1)

    stats = tracker.get_qos_history("ue-1")
    assert stats["sample_count"] == 1
    assert stats["metrics"]["latency_ms"]["avg"] == 12.0


def test_degradation_detection() -> None:
    tracker = QoSHistoryTracker(window_seconds=60.0, max_samples=20)
    now = time.time()

    for i in range(5):
        tracker.record("ue-1", "embb", {"latency_ms": 20.0 + i}, passed=False, timestamp=now - i)

    assert tracker.has_degradation("ue-1", threshold=0.5, min_samples=5) is True
    stats = tracker.get_qos_history("ue-1")
    assert stats["degradation_detected"] is True


def test_reset_clears_history() -> None:
    tracker = QoSHistoryTracker(window_seconds=60.0, max_samples=10)
    tracker.record("ue-1", "embb", {"latency_ms": 10.0}, True)
    tracker.reset("ue-1")

    stats = tracker.get_qos_history("ue-1")
    assert stats["sample_count"] == 0


