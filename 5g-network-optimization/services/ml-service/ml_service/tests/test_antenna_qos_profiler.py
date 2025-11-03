from __future__ import annotations

import time

import pytest

from ml_service.app.data.antenna_profiler import AntennaQoSProfiler


def test_profile_aggregates_metrics() -> None:
    profiler = AntennaQoSProfiler(window_seconds=120.0, max_samples=10)
    now = time.time()

    profiler.record(
        antenna_id="antA",
        service_type="eMBB",
        metrics={"latency_ms": 30.0, "throughput_mbps": 150.0},
        passed=True,
        timestamp=now - 20,
    )
    profiler.record(
        antenna_id="antA",
        service_type="eMBB",
        metrics={"latency_ms": 60.0, "throughput_mbps": 80.0},
        passed=False,
        timestamp=now - 10,
    )

    profile = profiler.get_profile("antA", "eMBB")
    assert profile["sample_count"] == 2
    assert profile["violation_count"] == 1
    assert profile["success_rate"] == pytest.approx(0.5, rel=1e-6)
    assert pytest.approx(profile["metrics"]["latency_ms"]["avg"], rel=1e-6) == 45.0
    assert profile["metrics"]["throughput_mbps"]["min"] == 80.0


def test_pruning_discards_old_samples() -> None:
    profiler = AntennaQoSProfiler(window_seconds=5.0, max_samples=10)
    now = time.time()

    profiler.record("antA", "embb", {"latency_ms": 100.0}, True, timestamp=now - 20)
    profiler.record("antA", "embb", {"latency_ms": 50.0}, True, timestamp=now)

    profile = profiler.get_profile("antA", "embb")
    assert profile["sample_count"] == 1
    assert profile["metrics"]["latency_ms"]["avg"] == 50.0


def test_score_penalises_poor_metrics() -> None:
    profiler = AntennaQoSProfiler(window_seconds=60.0, max_samples=20)
    now = time.time()

    for i in range(8):
        profiler.record(
            "antA",
            "urllc",
            {"latency_ms": 120.0, "throughput_mbps": 30.0, "jitter_ms": 25.0},
            passed=False,
            timestamp=now - i,
        )

    score = profiler.get_antenna_qos_score("antA", "urllc")
    assert score < 0.5
    assert profiler.is_poor_performer("antA", "urllc", threshold=0.6, min_samples=5)


def test_reset_specific_service() -> None:
    profiler = AntennaQoSProfiler(window_seconds=60.0, max_samples=10)
    profiler.record("antA", "embb", {"latency_ms": 20.0}, True)
    profiler.record("antA", "urllc", {"latency_ms": 5.0}, True)

    profiler.reset("antA", "embb")
    assert profiler.get_profile("antA", "embb")["sample_count"] == 0
    assert profiler.get_profile("antA", "urllc")["sample_count"] == 1


