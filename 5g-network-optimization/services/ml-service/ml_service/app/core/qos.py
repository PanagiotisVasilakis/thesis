"""Simple QoS utilities and a lightweight QoS classifier used during feature extraction.

This module intentionally implements a conservative, rule-based QoS classifier
that can be used during feature extraction to derive QoS-priority features
without requiring model retraining. It also exposes presets for common
service types.
"""
from typing import Dict, Any

_SERVICE_PRIORITY_MIN = 1
_SERVICE_PRIORITY_MAX = 10

_REQUIREMENT_LIMITS = {
    "latency_requirement_ms": (0.0, 10000.0),
    "throughput_requirement_mbps": (0.0, 100000.0),
    "jitter_ms": (0.0, 1000.0),
    "reliability_pct": (0.0, 100.0),
}


def _coerce_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(value, maximum))


DEFAULT_SERVICE_PRESETS = {
    "urllc": {
        "service_priority": 10,
        "latency_requirement_ms": 5.0,
        "throughput_requirement_mbps": 1.0,
        "reliability_pct": 99.99,
        "jitter_ms": 1.0,
    },
    "embb": {
        "service_priority": 7,
        "latency_requirement_ms": 50.0,
        "throughput_requirement_mbps": 100.0,
        "reliability_pct": 99.0,
        "jitter_ms": 15.0,
    },
    "mmtc": {
        "service_priority": 3,
        "latency_requirement_ms": 1000.0,
        "throughput_requirement_mbps": 0.1,
        "reliability_pct": 95.0,
        "jitter_ms": 100.0,
    },
    "default": {
        "service_priority": 5,
        "latency_requirement_ms": 100.0,
        "throughput_requirement_mbps": 5.0,
        "reliability_pct": 98.0,
        "jitter_ms": 20.0,
    },
}


def qos_from_request(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Return a normalized QoS dict from incoming request data.

    Behavior:
    - If `service_type` is provided and matches a preset, use preset values as defaults.
    - Override preset values with any explicit numeric QoS fields present in the payload.
    - Ensure returned keys: service_type, service_priority, latency_requirement_ms,
      throughput_requirement_mbps, reliability_pct.
    """
    svc = str(payload.get("service_type", "default") or "default").lower()
    preset = DEFAULT_SERVICE_PRESETS.get(svc, DEFAULT_SERVICE_PRESETS["default"]).copy()

    # Start with preset values
    qos = {
        "service_type": svc,
        "service_priority": int(preset.get("service_priority", 5)),
        "latency_requirement_ms": float(preset.get("latency_requirement_ms", 100.0)),
        "throughput_requirement_mbps": float(preset.get("throughput_requirement_mbps", 1.0)),
        "reliability_pct": float(preset.get("reliability_pct", 95.0)),
        "jitter_ms": float(preset.get("jitter_ms", 0.0)),
    }

    # Override if explicit values provided
    if "service_priority" in payload:
        try:
            qos["service_priority"] = int(payload["service_priority"])
        except Exception:
            pass
    if "latency_requirement_ms" in payload:
        try:
            qos["latency_requirement_ms"] = float(payload["latency_requirement_ms"])
        except Exception:
            pass
    if "throughput_requirement_mbps" in payload:
        try:
            qos["throughput_requirement_mbps"] = float(payload["throughput_requirement_mbps"])
        except Exception:
            pass
    if "reliability_pct" in payload:
        try:
            qos["reliability_pct"] = float(payload["reliability_pct"])
        except Exception:
            pass

    req_overrides = payload.get("qos_requirements")
    if isinstance(req_overrides, dict):
        for key, (min_val, max_val) in _REQUIREMENT_LIMITS.items():
            if key in req_overrides:
                qos[key] = _coerce_float(req_overrides[key], qos[key])
                qos[key] = _clamp(qos[key], min_val, max_val)

    qos["service_priority"] = int(_clamp(qos["service_priority"], _SERVICE_PRIORITY_MIN, _SERVICE_PRIORITY_MAX))
    for key, (min_val, max_val) in _REQUIREMENT_LIMITS.items():
        qos[key] = _clamp(float(qos[key]), min_val, max_val)

    return qos
