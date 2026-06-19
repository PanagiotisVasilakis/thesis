"""Deterministic counterfactual QoS proxy shared by offline thesis replay."""

from __future__ import annotations

from typing import Mapping

from .schemas import MeasurementTraceRecord


QOS_MODEL_VERSION = "sinr_cqi_v1"
CQI = (
    (-6.7, 0.1523), (-4.7, 0.2344), (-2.3, 0.3770),
    (0.2, 0.6016), (2.4, 0.8770), (4.3, 1.1758),
    (5.9, 1.4766), (8.1, 1.9141), (10.3, 2.4063),
    (11.7, 2.7305), (14.1, 3.3223), (16.3, 3.9023),
    (18.7, 4.5234), (21.0, 5.1152), (22.7, 5.5547),
)


def spectral_efficiency(sinr_db: float) -> float:
    result = 0.0
    for threshold, value in CQI:
        if sinr_db < threshold:
            break
        result = value
    return result


def estimate_counterfactual_qos(
    record: MeasurementTraceRecord,
    *,
    serving_cell: str,
    load: float,
    bandwidth_hz: float = 100e6,
    handover_interruption: bool = False,
) -> dict[str, float]:
    cell = record.visible_cell_map[serving_cell]
    sinr_db = float(cell.sinr_db if cell.sinr_db is not None else -30.0)
    speed = float(record.speed_mps or 0.0)
    efficiency = spectral_efficiency(sinr_db)
    resource_share = 1.0 / max(1.0, 1.0 + max(0.0, load))
    throughput = min(400.0, bandwidth_hz / 1e6 * efficiency * 0.75 * resource_share)
    retransmission_penalty = max(0.0, -5.0 - sinr_db)
    latency = min(80.0, max(4.0, 5.0 + 1.5 * load + 1.2 * retransmission_penalty + speed / 40.0))
    if handover_interruption:
        latency += 20.0
        throughput = 0.0
    jitter = min(50.0, max(0.5, 0.5 + 0.15 * latency + 0.5 * load))
    packet_loss = min(20.0, 0.1 + 1.5 * retransmission_penalty)
    return {
        "latency_ms": float(latency),
        "jitter_ms": float(jitter),
        "throughput_mbps": float(throughput),
        "packet_loss_rate": float(packet_loss),
    }


def qos_compliance(
    requirements: Mapping[str, float] | None,
    observed: Mapping[str, float],
) -> dict:
    requirements = requirements or {}
    violations: list[str] = []
    pairs = (
        ("latency_requirement_ms", "latency_ms", lambda actual, limit: actual > limit),
        ("throughput_requirement_mbps", "throughput_mbps", lambda actual, limit: actual < limit),
        ("jitter_ms", "jitter_ms", lambda actual, limit: actual > limit),
    )
    for requirement_key, observed_key, fails in pairs:
        if requirement_key in requirements and observed_key in observed:
            if fails(float(observed[observed_key]), float(requirements[requirement_key])):
                violations.append(observed_key)
    reliability = requirements.get("reliability_pct")
    if reliability is not None:
        if 100.0 - float(observed.get("packet_loss_rate", 100.0)) < float(reliability):
            violations.append("reliability_pct")
    return {
        "evaluated": bool(requirements),
        "passed": not violations,
        "service_priority_ok": not violations,
        "violations": violations,
        "model_version": QOS_MODEL_VERSION,
    }
