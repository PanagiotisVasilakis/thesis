"""Helper functions for ML service API operations."""

from __future__ import annotations

from typing import Any, Iterable

from .initialization.model_init import ModelManager
from .core.qos import qos_from_request


def load_model(
    model_path: str | None = None,
    neighbor_count: int | None = None,
    *,
    wait: bool = True,
) -> Any:
    """Return a LightGBM model instance using ``ModelManager``."""
    if wait:
        ModelManager.wait_until_ready()
    return ModelManager.get_instance(model_path, neighbor_count=neighbor_count)


def predict(ue_data: dict, model: Any | None = None):
    """Return prediction for ``ue_data`` using the provided model."""
    mdl = model or load_model()
    features = mdl.extract_features(ue_data)
    result = mdl.predict(features)
    # If the request carries QoS context, compute a lightweight
    # qos_compliance flag. This is conservative: compute a required
    # confidence threshold from the declared service_priority and
    # compare against the model's confidence.
    # If the model already returned qos_compliance, preserve it (model may
    # include richer information). Otherwise, compute a conservative
    # qos_compliance based on declared QoS in the request.
    if "qos_compliance" not in result:
        try:
            qos = qos_from_request(ue_data)
            priority = int(qos.get("service_priority", 5))
            required_conf = 0.5 + (min(max(priority, 1), 10) - 1) * (0.45 / 9)
            confidence = float(result.get("confidence", 0.0))

            compliance = {
                "service_priority_ok": confidence >= required_conf,
                "required_confidence": required_conf,
                "observed_confidence": confidence,
                "details": {
                    "service_type": qos.get("service_type"),
                    "service_priority": qos.get("service_priority"),
                    "latency_requirement_ms": qos.get("latency_requirement_ms"),
                    "throughput_requirement_mbps": qos.get("throughput_requirement_mbps"),
                    "reliability_pct": qos.get("reliability_pct"),
                },
            }
            result["qos_compliance"] = compliance
        except Exception:
            # Non-fatal: if QoS derivation fails, set a permissive compliance
            result.setdefault("qos_compliance", {"service_priority_ok": True, "details": {}})
    return result, features


def train(
    data: Iterable[dict],
    model: Any | None = None,
    *,
    neighbor_count: int | None = None,
) -> dict:
    """Train ``model`` with ``data`` and return training metrics."""
    mdl = model or load_model(neighbor_count=neighbor_count)
    metrics = mdl.train(data)
    return metrics
