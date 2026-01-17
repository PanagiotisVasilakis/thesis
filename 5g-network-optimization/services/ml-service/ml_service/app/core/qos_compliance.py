"""QoS compliance evaluation utilities."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .qos import _coerce_float


# Alias for backward compatibility (was _as_float)
_as_float = _coerce_float


def _confidence_threshold(priority: int) -> float:
    priority = max(1, min(priority, 10))
    return 0.5 + (priority - 1) * (0.45 / 9)


def evaluate_qos_compliance(*,
    qos_context: Dict[str, Any],
    observed: Dict[str, Any],
    confidence: float,
    default_priority: int = 5,
    adaptive_required_confidence: float | None = None,
) -> Tuple[Dict[str, Any], List[Dict[str, float]]]:
    """Return structured QoS compliance verdict and violation list."""

    service_type = qos_context.get("service_type") or "default"
    priority = int(qos_context.get("service_priority", default_priority))
    base_required_conf = _confidence_threshold(priority)
    required_conf = adaptive_required_confidence if adaptive_required_confidence is not None else base_required_conf

    requirements = {
        "latency_ms": _as_float(qos_context.get("latency_requirement_ms"), 0.0),
        "throughput_mbps": _as_float(qos_context.get("throughput_requirement_mbps"), 0.0),
        "jitter_ms": _as_float(qos_context.get("jitter_ms"), qos_context.get("latency_requirement_ms", 0.0) * 0.1),
        "reliability_pct": _as_float(qos_context.get("reliability_pct"), 0.0),
    }

    observed_metrics = {
        "latency_ms": _as_float(observed.get("latency_ms"), requirements["latency_ms"]),
        "throughput_mbps": _as_float(observed.get("throughput_mbps"), requirements["throughput_mbps"]),
        "jitter_ms": _as_float(observed.get("jitter_ms"), requirements["jitter_ms"]),
        "packet_loss_rate": _as_float(observed.get("packet_loss_rate"), 0.0),
    }

    metrics: Dict[str, Dict[str, float | bool]] = {}
    violations: List[Dict[str, float]] = []

    latency_ok = observed_metrics["latency_ms"] <= requirements["latency_ms"] if requirements["latency_ms"] > 0 else True
    throughput_ok = observed_metrics["throughput_mbps"] >= requirements["throughput_mbps"] if requirements["throughput_mbps"] > 0 else True
    jitter_ok = observed_metrics["jitter_ms"] <= requirements["jitter_ms"] if requirements["jitter_ms"] > 0 else True
    reliability_threshold_loss = max(0.0, 100.0 - requirements["reliability_pct"])
    reliability_ok = observed_metrics["packet_loss_rate"] <= reliability_threshold_loss if requirements["reliability_pct"] > 0 else True

    metrics["latency"] = {
        "passed": latency_ok,
        "required": requirements["latency_ms"],
        "observed": observed_metrics["latency_ms"],
        "delta": observed_metrics["latency_ms"] - requirements["latency_ms"],
    }
    metrics["throughput"] = {
        "passed": throughput_ok,
        "required": requirements["throughput_mbps"],
        "observed": observed_metrics["throughput_mbps"],
        "delta": observed_metrics["throughput_mbps"] - requirements["throughput_mbps"],
    }
    metrics["jitter"] = {
        "passed": jitter_ok,
        "required": requirements["jitter_ms"],
        "observed": observed_metrics["jitter_ms"],
        "delta": observed_metrics["jitter_ms"] - requirements["jitter_ms"],
    }
    metrics["reliability"] = {
        "passed": reliability_ok,
        "required_loss_max": reliability_threshold_loss,
        "observed_loss": observed_metrics["packet_loss_rate"],
        "delta": observed_metrics["packet_loss_rate"] - reliability_threshold_loss,
    }

    for metric_name, data in metrics.items():
        if not bool(data["passed"]):
            violations.append(
                {
                    "metric": metric_name,
                    "required": float(data.get("required", data.get("required_loss_max", 0.0))),
                    "observed": float(data.get("observed", data.get("observed_loss", 0.0))),
                    "delta": float(data["delta"]),
                }
            )

    confidence_ok = float(confidence) >= required_conf
    overall_passed = not violations and confidence_ok

    compliance = {
        "service_priority_ok": overall_passed,
        "confidence_ok": confidence_ok,
        "required_confidence": required_conf,
        "base_required_confidence": base_required_conf,
        "observed_confidence": float(confidence),
        "details": {
            "service_type": service_type,
            "service_priority": priority,
            "latency_requirement_ms": requirements["latency_ms"],
            "throughput_requirement_mbps": requirements["throughput_mbps"],
            "jitter_ms": requirements["jitter_ms"],
            "reliability_pct": requirements["reliability_pct"],
        },
        "metrics": metrics,
        "violations": violations,
    }

    compliance["observed"] = observed_metrics
    compliance["requirements"] = {
        "latency_ms": requirements["latency_ms"],
        "throughput_mbps": requirements["throughput_mbps"],
        "jitter_ms": requirements["jitter_ms"],
        "reliability_pct": requirements["reliability_pct"],
        "max_packet_loss_rate": reliability_threshold_loss,
    }

    return compliance, violations
