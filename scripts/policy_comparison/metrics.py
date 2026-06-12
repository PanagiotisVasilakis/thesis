"""Offline comparison metrics derived from canonical decision logs."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import Dict, Iterable, List, Tuple

from .schemas import PolicyDecisionRecord


@dataclass(frozen=True)
class PolicyMetricSummary:
    """Aggregate metrics available from offline decision replay."""

    policy_name: str
    handover_count: int
    stay_count: int
    ping_pong_count: int
    low_quality_step_count: int
    unnecessary_handover_count: int
    late_handover_proxy_count: int
    failed_handover_proxy_count: int
    rlf_proxy_count: int
    qos_violation_proxy_count: int
    load_balance_regression_count: int
    avg_dwell_time_s: float
    avg_decision_latency_ms: float
    min_serving_rsrp_dbm: float
    avg_serving_rsrp_dbm: float
    avg_handover_target_rsrp_dbm: float
    avg_serving_load: float
    avg_handover_target_load: float
    composite_cost: float
    complexity_sparse_composite_cost: float
    complexity_moderate_composite_cost: float
    complexity_high_composite_cost: float
    complexity_bucket_counts: Dict[str, int]
    complexity_bucket_costs: Dict[str, float]
    per_ue: Dict[str, Dict[str, int]]

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


def summarize_policy_decisions(
    policy_name: str,
    decisions: Iterable[PolicyDecisionRecord],
    *,
    ping_pong_window_s: float = 60.0,
    low_quality_rsrp_floor_dbm: float = -110.0,
    rlf_rsrp_floor_dbm: float = -115.0,
) -> PolicyMetricSummary:
    """Summarize comparable metrics from decision records only."""
    materialized = sorted(
        decisions,
        key=lambda decision: (decision.timestamp_s, decision.step_index, decision.ue_id),
    )
    handover_count = 0
    stay_count = 0
    ping_pong_count = 0
    low_quality_step_count = 0
    unnecessary_handover_count = 0
    late_handover_proxy_count = 0
    failed_handover_proxy_count = 0
    rlf_proxy_count = 0
    qos_violation_proxy_count = 0
    load_balance_regression_count = 0
    latency_values: List[float] = []
    serving_values: List[float] = []
    handover_target_values: List[float] = []
    serving_load_values: List[float] = []
    handover_target_load_values: List[float] = []
    dwell_segments: List[float] = []
    composite_cost = 0.0
    bucket_counts: Dict[str, int] = defaultdict(int)
    bucket_costs: Dict[str, float] = defaultdict(float)
    per_ue: Dict[str, Dict[str, int]] = defaultdict(
        lambda: {
            "handovers": 0,
            "stays": 0,
            "ping_pongs": 0,
            "low_quality_steps": 0,
            "unnecessary_handovers": 0,
            "late_handover_proxies": 0,
            "failed_handover_proxies": 0,
            "rlf_proxies": 0,
            "qos_violation_proxies": 0,
            "load_balance_regressions": 0,
        }
    )
    last_handover: Dict[str, Tuple[str, str, float]] = {}
    dwell_state: Dict[str, Tuple[str, float]] = {}

    for decision in materialized:
        bucket = _complexity_bucket(decision)
        bucket_counts[bucket] += 1
        decision_cost = 0.0
        serving_values.append(decision.serving_measurement_value)
        cell_loads = _cell_loads(decision)
        serving_load = cell_loads.get(decision.current_serving_cell)
        if serving_load is not None:
            serving_load_values.append(serving_load)
        if decision.serving_measurement_value < low_quality_rsrp_floor_dbm:
            low_quality_step_count += 1
            per_ue[decision.ue_id]["low_quality_steps"] += 1
            decision_cost += 2.0
        if decision.serving_measurement_value < rlf_rsrp_floor_dbm:
            rlf_proxy_count += 1
            per_ue[decision.ue_id]["rlf_proxies"] += 1
            decision_cost += 8.0
        if _has_qos_violation(decision):
            qos_violation_proxy_count += 1
            per_ue[decision.ue_id]["qos_violation_proxies"] += 1
            decision_cost += 10.0
        if decision.decision_latency_ms is not None:
            latency_values.append(decision.decision_latency_ms)
            decision_cost += min(max(decision.decision_latency_ms, 0.0) / 50.0, 5.0)

        summary = per_ue[decision.ue_id]
        if decision.ue_id not in dwell_state:
            dwell_state[decision.ue_id] = (
                decision.current_serving_cell,
                decision.timestamp_s,
            )

        if decision.decision_type == "stay":
            stay_count += 1
            summary["stays"] += 1
            strongest_neighbour = (
                max(decision.neighbour_measurements_considered.values())
                if decision.neighbour_measurements_considered
                else None
            )
            if (
                decision.serving_measurement_value < low_quality_rsrp_floor_dbm
                and strongest_neighbour is not None
                and strongest_neighbour > decision.serving_measurement_value
            ):
                late_handover_proxy_count += 1
                summary["late_handover_proxies"] += 1
                decision_cost += 3.0
            composite_cost += decision_cost
            bucket_costs[bucket] += decision_cost
            continue

        handover_count += 1
        summary["handovers"] += 1
        decision_cost += 1.0
        target = decision.selected_target_cell
        if target is None:
            composite_cost += decision_cost
            bucket_costs[bucket] += decision_cost
            continue
        target_rsrp = decision.neighbour_measurements_considered.get(target)
        if target_rsrp is not None:
            handover_target_values.append(target_rsrp)
            if target_rsrp <= decision.serving_measurement_value:
                unnecessary_handover_count += 1
                summary["unnecessary_handovers"] += 1
                decision_cost += 3.0
            if target_rsrp < low_quality_rsrp_floor_dbm:
                failed_handover_proxy_count += 1
                summary["failed_handover_proxies"] += 1
                decision_cost += 6.0
        target_load = cell_loads.get(target)
        if target_load is not None:
            handover_target_load_values.append(target_load)
            if serving_load is not None and target_load > serving_load:
                load_balance_regression_count += 1
                summary["load_balance_regressions"] += 1
                decision_cost += 2.0

        current_cell, started_at = dwell_state[decision.ue_id]
        if current_cell == decision.current_serving_cell:
            dwell_segments.append(max(0.0, decision.timestamp_s - started_at))
        dwell_state[decision.ue_id] = (target, decision.timestamp_s)

        previous = last_handover.get(decision.ue_id)
        if previous is not None:
            previous_from, previous_to, previous_time = previous
            if (
                previous_from == target
                and previous_to == decision.current_serving_cell
                and decision.timestamp_s - previous_time <= ping_pong_window_s
            ):
                ping_pong_count += 1
                summary["ping_pongs"] += 1
                decision_cost += 5.0

        last_handover[decision.ue_id] = (
            decision.current_serving_cell,
            target,
            decision.timestamp_s,
        )
        composite_cost += decision_cost
        bucket_costs[bucket] += decision_cost

    return PolicyMetricSummary(
        policy_name=policy_name,
        handover_count=handover_count,
        stay_count=stay_count,
        ping_pong_count=ping_pong_count,
        low_quality_step_count=low_quality_step_count,
        unnecessary_handover_count=unnecessary_handover_count,
        late_handover_proxy_count=late_handover_proxy_count,
        failed_handover_proxy_count=failed_handover_proxy_count,
        rlf_proxy_count=rlf_proxy_count,
        qos_violation_proxy_count=qos_violation_proxy_count,
        load_balance_regression_count=load_balance_regression_count,
        avg_dwell_time_s=(
            sum(dwell_segments) / len(dwell_segments) if dwell_segments else 0.0
        ),
        avg_decision_latency_ms=(
            sum(latency_values) / len(latency_values) if latency_values else 0.0
        ),
        min_serving_rsrp_dbm=min(serving_values) if serving_values else 0.0,
        avg_serving_rsrp_dbm=(
            sum(serving_values) / len(serving_values) if serving_values else 0.0
        ),
        avg_handover_target_rsrp_dbm=(
            sum(handover_target_values) / len(handover_target_values)
            if handover_target_values
            else 0.0
        ),
        avg_serving_load=(
            sum(serving_load_values) / len(serving_load_values)
            if serving_load_values
            else 0.0
        ),
        avg_handover_target_load=(
            sum(handover_target_load_values) / len(handover_target_load_values)
            if handover_target_load_values
            else 0.0
        ),
        composite_cost=round(composite_cost, 6),
        complexity_sparse_composite_cost=round(bucket_costs.get("sparse", 0.0), 6),
        complexity_moderate_composite_cost=round(bucket_costs.get("moderate", 0.0), 6),
        complexity_high_composite_cost=round(bucket_costs.get("high", 0.0), 6),
        complexity_bucket_counts=dict(bucket_counts),
        complexity_bucket_costs={
            bucket: round(cost, 6) for bucket, cost in bucket_costs.items()
        },
        per_ue=dict(per_ue),
    )


def _cell_loads(decision: PolicyDecisionRecord) -> Dict[str, float]:
    raw = decision.debug.get("cell_loads")
    if not isinstance(raw, dict):
        return {}
    return {
        str(cell_id): float(load)
        for cell_id, load in raw.items()
        if isinstance(load, (int, float))
    }


def _complexity_bucket(decision: PolicyDecisionRecord) -> str:
    complexity = decision.debug.get("candidate_complexity")
    if isinstance(complexity, dict):
        bucket = complexity.get("complexity_bucket")
        if isinstance(bucket, str) and bucket:
            return bucket
    return "unknown"


def _has_qos_violation(decision: PolicyDecisionRecord) -> bool:
    compliance = decision.debug.get("qos_compliance")
    if not isinstance(compliance, dict):
        return False
    if compliance.get("passed") is False:
        return True
    if compliance.get("service_priority_ok") is False:
        return True
    violations = compliance.get("violations")
    return isinstance(violations, list) and bool(violations)
