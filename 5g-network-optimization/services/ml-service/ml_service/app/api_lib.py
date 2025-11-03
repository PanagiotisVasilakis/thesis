"""Helper functions for ML service API operations."""

from __future__ import annotations

from typing import Any, Dict, Iterable

from .initialization.model_init import ModelManager
from .core.qos import qos_from_request
from .core.qos_compliance import evaluate_qos_compliance
from .core.adaptive_qos import adaptive_qos_manager
from .monitoring import metrics


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
    try:
        qos = qos_from_request(ue_data)

        observed_payload: Dict[str, Any] = {}
        if isinstance(ue_data.get("observed_qos"), dict):
            observed_payload = ue_data.get("observed_qos", {})  # type: ignore[assignment]
        elif isinstance(ue_data.get("observed_qos_summary"), dict):
            latest = ue_data.get("observed_qos_summary", {}).get("latest", {})  # type: ignore[assignment]
            if isinstance(latest, dict):
                observed_payload = latest

        observed_metrics = {
            "latency_ms": observed_payload.get("latency_ms", features.get("observed_latency_ms")),
            "throughput_mbps": observed_payload.get("throughput_mbps", features.get("observed_throughput_mbps")),
            "jitter_ms": observed_payload.get("jitter_ms", features.get("observed_jitter_ms")),
            "packet_loss_rate": observed_payload.get("packet_loss_rate", features.get("observed_packet_loss_rate")),
        }

        priority = int(qos.get("service_priority", 5))
        service_type = qos.get("service_type") or "default"
        adaptive_required = adaptive_qos_manager.get_required_confidence(service_type, priority)
        compliance, violations = evaluate_qos_compliance(
            qos_context=qos,
            observed=observed_metrics,
            confidence=float(result.get("confidence", 0.0)),
            default_priority=priority,
            adaptive_required_confidence=adaptive_required,
        )
        result["qos_compliance"] = compliance
        metrics.track_qos_compliance(
            qos.get("service_type"),
            compliance.get("service_priority_ok", True),
            violations,
            observed=observed_metrics,
        )
        try:
            metrics.ADAPTIVE_CONFIDENCE.labels(service_type=service_type).set(adaptive_required)
        except Exception:
            pass
    except Exception:
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
