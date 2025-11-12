"""Heuristics for selecting the optimal antenna based on RF and QoS context."""
from __future__ import annotations

from typing import Dict, Mapping, Optional, Tuple

import numpy as np

AntennaScores = Dict[str, float]
AntennaBias = Mapping[str, Mapping[str, float]]


def _to_float(value: Optional[float]) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize(value: Optional[float], low: float, high: float) -> float:
    numeric = _to_float(value)
    if numeric is None or high <= low:
        return 0.0
    return float(np.clip((numeric - low) / (high - low), 0.0, 1.0))


def select_optimal_antenna(
    rf_metrics: Mapping[str, Mapping[str, float]],
    *,
    qos_requirements: Optional[Mapping[str, float]] = None,
    service_type: Optional[str] = None,
    service_priority: Optional[float] = None,
    stability: Optional[float] = None,
    signal_trend: Optional[float] = None,
    antenna_bias: Optional[AntennaBias] = None,
    rng: Optional[np.random.Generator] = None,
) -> Tuple[str, AntennaScores]:
    """Return the top-scoring antenna id and per-antenna scores.

    The scoring function blends RF quality with QoS constraints so that
    throughput- and latency-sensitive services can favour antennas with the
    required capacity even when they are not geographically closest.
    """
    if not rf_metrics:
        return "antenna_1", {}

    generator = rng or np.random.default_rng()
    qos = dict(qos_requirements or {})

    priority_norm = _normalize(
        service_priority if service_priority is not None else qos.get("service_priority"),
        1.0,
        10.0,
    )
    latency_need = 1.0 - _normalize(qos.get("latency_requirement_ms"), 20.0, 500.0)
    jitter_need = 1.0 - _normalize(qos.get("jitter_ms"), 0.5, 50.0)
    throughput_need = _normalize(qos.get("throughput_requirement_mbps"), 5.0, 500.0)
    reliability_need = _normalize(qos.get("reliability_pct"), 95.0, 100.0)

    svc = (service_type or qos.get("service_type") or "").lower()
    if svc == "urllc":
        latency_need = min(1.0, latency_need + 0.2)
        jitter_need = min(1.0, jitter_need + 0.2)
    elif svc == "embb":
        throughput_need = min(1.0, throughput_need + 0.2)
    elif svc == "mmtc":
        reliability_need = min(1.0, reliability_need + 0.1)

    stability_norm = _normalize(stability, 0.0, 1.0)
    trend_norm = (_normalize(signal_trend, -5.0, 5.0) * 2.0) - 1.0

    scores: AntennaScores = {}
    for antenna_id, metrics in rf_metrics.items():
        rsrp = metrics.get("rsrp")
        sinr = metrics.get("sinr")
        rsrq = metrics.get("rsrq")
        load = metrics.get("cell_load")

        signal_strength = _normalize(rsrp, -115.0, -55.0)
        sinr_quality = _normalize(sinr, -5.0, 30.0)
        rsrq_quality = _normalize(-rsrq if rsrq is not None else None, 3.0, 18.0)
        load_quality = _normalize(None if load is None else 1.0 - load, 0.0, 1.0)

        bias = antenna_bias.get(antenna_id, {}) if antenna_bias else {}
        capacity_bias = float(bias.get("capacity", 1.0))
        latency_bias = float(bias.get("latency", 1.0))
        reliability_bias = float(bias.get("reliability", 1.0))
        coverage_bias = float(bias.get("coverage", 1.0))

        composite = 0.0
        composite += 0.28 * signal_strength * coverage_bias
        composite += 0.18 * sinr_quality * (0.6 + 0.4 * throughput_need) * capacity_bias
        composite += 0.12 * rsrq_quality * (0.5 + 0.5 * reliability_need) * reliability_bias
        composite += 0.14 * load_quality * (0.7 + 0.3 * throughput_need) * capacity_bias
        composite += 0.12 * signal_strength * (0.5 + 0.5 * latency_need) * latency_bias
        composite += 0.08 * sinr_quality * (0.4 + 0.6 * jitter_need) * latency_bias
        composite += 0.04 * stability_norm * (0.3 + 0.7 * reliability_need) * reliability_bias
        composite += 0.02 * trend_norm
        composite += 0.02 * priority_norm
        composite += generator.normal(0.0, 0.01)

        scores[antenna_id] = float(composite)

    best_id = max(scores.items(), key=lambda item: item[1])[0]
    return best_id, scores
