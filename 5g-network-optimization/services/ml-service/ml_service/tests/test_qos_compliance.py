from __future__ import annotations

from ml_service.app.core.qos_compliance import evaluate_qos_compliance


def test_qos_compliance_passes_when_metrics_within_thresholds():
    qos_context = {
        "service_type": "embb",
        "service_priority": 6,
        "latency_requirement_ms": 50.0,
        "throughput_requirement_mbps": 150.0,
        "jitter_ms": 10.0,
        "reliability_pct": 99.0,
    }
    observed = {
        "latency_ms": 45.0,
        "throughput_mbps": 180.0,
        "jitter_ms": 5.0,
        "packet_loss_rate": 0.5,
    }

    compliance, violations = evaluate_qos_compliance(
        qos_context=qos_context,
        observed=observed,
        confidence=0.8,
    )

    assert compliance["service_priority_ok"] is True
    assert compliance["confidence_ok"] is True
    assert violations == []
    assert compliance["observed"]["throughput_mbps"] == observed["throughput_mbps"]
    assert compliance["metrics"]["latency"]["passed"] is True


def test_qos_compliance_flags_latency_violation():
    qos_context = {
        "service_type": "urllc",
        "service_priority": 9,
        "latency_requirement_ms": 10.0,
        "throughput_requirement_mbps": 50.0,
        "jitter_ms": 2.0,
        "reliability_pct": 99.9,
    }
    observed = {
        "latency_ms": 18.0,
        "throughput_mbps": 60.0,
        "jitter_ms": 1.0,
        "packet_loss_rate": 0.05,
    }

    compliance, violations = evaluate_qos_compliance(
        qos_context=qos_context,
        observed=observed,
        confidence=0.7,
    )

    assert compliance["service_priority_ok"] is False
    assert compliance["confidence_ok"] is False  # high priority raises threshold
    assert any(v["metric"] == "latency" for v in violations)
    latency_metric = compliance["metrics"]["latency"]
    assert latency_metric["passed"] is False
    assert latency_metric["delta"] > 0

