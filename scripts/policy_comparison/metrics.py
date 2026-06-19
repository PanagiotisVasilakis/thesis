"""Offline comparison metrics derived from canonical decision logs."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from statistics import median
from typing import Dict, Iterable, List, Tuple

from .schemas import PolicyDecisionRecord


@dataclass(frozen=True)
class PolicyMetricSummary:
    """Aggregate metrics available from offline decision replay."""

    policy_name: str
    composite_cost_version: str
    handover_count: int
    stay_count: int
    ping_pong_count: int
    low_quality_step_count: int
    low_sinr_step_count: int
    unnecessary_handover_count: int
    late_handover_proxy_count: int
    failed_handover_proxy_count: int
    poor_handover_target_sinr_count: int
    rlf_proxy_count: int
    qos_violation_proxy_count: int
    load_balance_regression_count: int
    avg_dwell_time_s: float
    avg_decision_latency_ms: float
    latency_budget_violation_count: int
    min_serving_rsrp_dbm: float
    avg_serving_rsrp_dbm: float
    min_serving_sinr_db: float
    avg_serving_sinr_db: float
    avg_handover_target_rsrp_dbm: float
    avg_handover_target_sinr_db: float
    avg_serving_load: float
    avg_handover_target_load: float
    composite_cost: float
    complexity_sparse_composite_cost: float
    complexity_moderate_composite_cost: float
    complexity_high_composite_cost: float
    complexity_bucket_counts: Dict[str, int]
    complexity_bucket_costs: Dict[str, float]
    mean_segment_duration_s: float
    segment_entry_count: int
    segment_exit_count: int
    emergency_exit_count: int
    post_segment_a3_guard_suppression_count: int
    high_reject_hold_count: int
    post_segment_a3_handover_count: int
    post_segment_ping_pong_count: int
    sparse_moderate_churn_after_ml_count: int
    sparse_authority_suppression_count: int
    sparse_authority_handover_count: int
    observation_time_ue_minutes: float
    handovers_per_ue_minute: float
    ping_pongs_per_ue_minute: float
    qos_violations_per_ue_minute: float
    rlf_proxies_per_ue_minute: float
    sinr_outage_fraction: float
    handover_interruption_time_s: float
    composite_cost_components: Dict[str, float]
    composite_cost_sensitivity: Dict[str, float]
    per_ue: Dict[str, Dict[str, int]]

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


def summarize_policy_decisions(
    policy_name: str,
    decisions: Iterable[PolicyDecisionRecord],
    *,
    ping_pong_window_s: float = 60.0,
    low_quality_rsrp_floor_dbm: float = -110.0,
    low_quality_sinr_floor_db: float = -5.0,
    rlf_rsrp_floor_dbm: float = -115.0,
    decision_latency_budget_ms: float = 10.0,
    metric_version: str = "v2_rsrp_sinr_latency_budget",
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
    low_sinr_step_count = 0
    unnecessary_handover_count = 0
    late_handover_proxy_count = 0
    failed_handover_proxy_count = 0
    poor_handover_target_sinr_count = 0
    rlf_proxy_count = 0
    qos_violation_proxy_count = 0
    load_balance_regression_count = 0
    latency_values: List[float] = []
    latency_budget_violation_count = 0
    serving_values: List[float] = []
    serving_sinr_values: List[float] = []
    handover_target_values: List[float] = []
    handover_target_sinr_values: List[float] = []
    serving_load_values: List[float] = []
    handover_target_load_values: List[float] = []
    dwell_segments: List[float] = []
    composite_cost = 0.0
    bucket_counts: Dict[str, int] = defaultdict(int)
    bucket_costs: Dict[str, float] = defaultdict(float)
    segment_durations: List[float] = []
    segment_entry_count = 0
    segment_exit_count = 0
    emergency_exit_count = 0
    post_segment_a3_guard_suppression_count = 0
    high_reject_hold_count = 0
    post_segment_a3_handover_count = 0
    post_segment_ping_pong_count = 0
    last_segment_exit: Dict[str, PolicyDecisionRecord] = {}
    sparse_moderate_churn_after_ml_count = 0
    sparse_authority_suppression_count = 0
    sparse_authority_handover_count = 0
    last_ml_authority: Dict[str, PolicyDecisionRecord] = {}
    per_ue: Dict[str, Dict[str, int]] = defaultdict(
        lambda: {
            "handovers": 0,
            "stays": 0,
            "ping_pongs": 0,
            "low_quality_steps": 0,
            "low_sinr_steps": 0,
            "unnecessary_handovers": 0,
            "late_handover_proxies": 0,
            "failed_handover_proxies": 0,
            "poor_handover_target_sinr": 0,
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
        cell_sinrs = _cell_sinrs(decision)
        serving_load = cell_loads.get(decision.current_serving_cell)
        if serving_load is not None:
            serving_load_values.append(serving_load)
        if decision.serving_measurement_value < low_quality_rsrp_floor_dbm:
            low_quality_step_count += 1
            per_ue[decision.ue_id]["low_quality_steps"] += 1
            decision_cost += 2.0
        serving_sinr = cell_sinrs.get(decision.current_serving_cell)
        if serving_sinr is not None:
            serving_sinr_values.append(serving_sinr)
            if serving_sinr < low_quality_sinr_floor_db:
                low_sinr_step_count += 1
                per_ue[decision.ue_id]["low_sinr_steps"] += 1
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
            if decision.decision_latency_ms > decision_latency_budget_ms:
                latency_budget_violation_count += 1
                decision_cost += min(
                    (decision.decision_latency_ms - decision_latency_budget_ms)
                    / max(decision_latency_budget_ms, 1e-9),
                    5.0,
                )
        source = str(decision.debug.get("decision_source") or decision.policy_name)
        if source == "ml_segment_entry":
            segment_entry_count += 1
        if source in {"ml_segment_exit_to_a3", "ml_segment_emergency_exit"}:
            segment_exit_count += 1
            if source == "ml_segment_emergency_exit":
                emergency_exit_count += 1
            age = decision.debug.get("segment_age_s")
            if isinstance(age, (int, float)):
                segment_durations.append(float(age))
            last_segment_exit[decision.ue_id] = decision
            last_ml_authority[decision.ue_id] = decision
        if source in {
            "ml_segment_entry",
            "ml_segment_hold",
            "ml_segment_rejected_stay",
            "ml_segment_rejected_stay_hold",
        }:
            last_ml_authority[decision.ue_id] = decision
        if decision.debug.get("post_segment_a3_guard_applied") is True:
            post_segment_a3_guard_suppression_count += 1
        if decision.debug.get("high_reject_hold_applied") is True:
            high_reject_hold_count += 1
        if decision.debug.get("sparse_authority_applied") is True:
            sparse_authority_suppression_count += 1

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
        if decision.debug.get("sparse_authority_mode") in {
            "quality_gated_a3",
            "stay_unless_weak",
        }:
            sparse_authority_handover_count += 1
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
        target_sinr = cell_sinrs.get(target)
        if target_sinr is not None:
            handover_target_sinr_values.append(target_sinr)
            if target_sinr < low_quality_sinr_floor_db:
                poor_handover_target_sinr_count += 1
                summary["poor_handover_target_sinr"] += 1
                decision_cost += 3.0
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
        previous_exit = last_segment_exit.get(decision.ue_id)
        if (
            previous_exit is not None
            and source == "a3_complexity_gate"
            and decision.timestamp_s - previous_exit.timestamp_s <= 60.0
        ):
            post_segment_a3_handover_count += 1
            if (
                decision.selected_target_cell == previous_exit.current_serving_cell
                or decision.current_serving_cell == previous_exit.selected_target_cell
            ):
                post_segment_ping_pong_count += 1
        previous_ml = last_ml_authority.get(decision.ue_id)
        if (
            previous_ml is not None
            and source == "a3_complexity_gate"
            and bucket in {"sparse", "moderate"}
            and decision.timestamp_s - previous_ml.timestamp_s <= 60.0
        ):
            sparse_moderate_churn_after_ml_count += 1
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

    timestamps_by_ue: Dict[str, List[float]] = defaultdict(list)
    for decision in materialized:
        timestamps_by_ue[decision.ue_id].append(float(decision.timestamp_s))
    observation_time_s = 0.0
    for timestamps in timestamps_by_ue.values():
        ordered_times = sorted(set(timestamps))
        deltas = [
            current - previous
            for previous, current in zip(ordered_times, ordered_times[1:])
            if current > previous
        ]
        interval = median(deltas) if deltas else 1.0
        observation_time_s += max(interval, ordered_times[-1] - ordered_times[0] + interval)
    observation_ue_minutes = max(observation_time_s / 60.0, 1e-9)
    use_v3 = metric_version == "v3_physical_qos_cost"
    reported_cost = composite_cost / observation_ue_minutes if use_v3 else composite_cost
    bucket_total = max(1, sum(bucket_counts.values()))
    reported_bucket_costs = {
        bucket: (
            value
            / max(observation_ue_minutes * count / bucket_total, 1e-9)
            if use_v3
            else value
        )
        for bucket, value in bucket_costs.items()
        for count in [bucket_counts.get(bucket, 0)]
    }
    primary_components = {
        "sinr_outage": float(low_sinr_step_count * 2.0),
        "rsrp_outage": float(low_quality_step_count * 2.0),
        "qos_violation": float(qos_violation_proxy_count * 10.0),
        "rlf": float(rlf_proxy_count * 8.0),
        "handover_action": float(handover_count),
        "ping_pong": float(ping_pong_count * 5.0),
        "unnecessary_handover": float(unnecessary_handover_count * 3.0),
        "failed_handover": float(failed_handover_proxy_count * 6.0),
        "late_handover": float(late_handover_proxy_count * 3.0),
        "poor_target_sinr": float(poor_handover_target_sinr_count * 3.0),
        "load_regression": float(load_balance_regression_count * 2.0),
    }
    sensitivity = {
        "primary": round(reported_cost, 6),
        "safety_heavy": round(
            (
                composite_cost
                + low_sinr_step_count
                + qos_violation_proxy_count * 5.0
                + rlf_proxy_count * 8.0
            )
            / observation_ue_minutes
            if use_v3
            else composite_cost,
            6,
        ),
    }

    return PolicyMetricSummary(
        policy_name=policy_name,
        composite_cost_version=metric_version,
        handover_count=handover_count,
        stay_count=stay_count,
        ping_pong_count=ping_pong_count,
        low_quality_step_count=low_quality_step_count,
        low_sinr_step_count=low_sinr_step_count,
        unnecessary_handover_count=unnecessary_handover_count,
        late_handover_proxy_count=late_handover_proxy_count,
        failed_handover_proxy_count=failed_handover_proxy_count,
        poor_handover_target_sinr_count=poor_handover_target_sinr_count,
        rlf_proxy_count=rlf_proxy_count,
        qos_violation_proxy_count=qos_violation_proxy_count,
        load_balance_regression_count=load_balance_regression_count,
        avg_dwell_time_s=(
            sum(dwell_segments) / len(dwell_segments) if dwell_segments else 0.0
        ),
        avg_decision_latency_ms=(
            sum(latency_values) / len(latency_values) if latency_values else 0.0
        ),
        latency_budget_violation_count=latency_budget_violation_count,
        min_serving_rsrp_dbm=min(serving_values) if serving_values else 0.0,
        avg_serving_rsrp_dbm=(
            sum(serving_values) / len(serving_values) if serving_values else 0.0
        ),
        min_serving_sinr_db=(
            min(serving_sinr_values) if serving_sinr_values else 0.0
        ),
        avg_serving_sinr_db=(
            sum(serving_sinr_values) / len(serving_sinr_values)
            if serving_sinr_values
            else 0.0
        ),
        avg_handover_target_rsrp_dbm=(
            sum(handover_target_values) / len(handover_target_values)
            if handover_target_values
            else 0.0
        ),
        avg_handover_target_sinr_db=(
            sum(handover_target_sinr_values) / len(handover_target_sinr_values)
            if handover_target_sinr_values
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
        composite_cost=round(reported_cost, 6),
        complexity_sparse_composite_cost=round(reported_bucket_costs.get("sparse", 0.0), 6),
        complexity_moderate_composite_cost=round(reported_bucket_costs.get("moderate", 0.0), 6),
        complexity_high_composite_cost=round(reported_bucket_costs.get("high", 0.0), 6),
        complexity_bucket_counts=dict(bucket_counts),
        complexity_bucket_costs={
            bucket: round(cost, 6) for bucket, cost in reported_bucket_costs.items()
        },
        mean_segment_duration_s=(
            sum(segment_durations) / len(segment_durations)
            if segment_durations
            else 0.0
        ),
        segment_entry_count=segment_entry_count,
        segment_exit_count=segment_exit_count,
        emergency_exit_count=emergency_exit_count,
        post_segment_a3_guard_suppression_count=post_segment_a3_guard_suppression_count,
        high_reject_hold_count=high_reject_hold_count,
        post_segment_a3_handover_count=post_segment_a3_handover_count,
        post_segment_ping_pong_count=post_segment_ping_pong_count,
        sparse_moderate_churn_after_ml_count=sparse_moderate_churn_after_ml_count,
        sparse_authority_suppression_count=sparse_authority_suppression_count,
        sparse_authority_handover_count=sparse_authority_handover_count,
        observation_time_ue_minutes=round(observation_ue_minutes, 6),
        handovers_per_ue_minute=round(handover_count / observation_ue_minutes, 6),
        ping_pongs_per_ue_minute=round(ping_pong_count / observation_ue_minutes, 6),
        qos_violations_per_ue_minute=round(
            qos_violation_proxy_count / observation_ue_minutes, 6
        ),
        rlf_proxies_per_ue_minute=round(rlf_proxy_count / observation_ue_minutes, 6),
        sinr_outage_fraction=round(
            low_sinr_step_count / max(1, len(materialized)), 6
        ),
        handover_interruption_time_s=round(handover_count * 0.020, 6),
        composite_cost_components=primary_components,
        composite_cost_sensitivity=sensitivity,
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


def _cell_sinrs(decision: PolicyDecisionRecord) -> Dict[str, float]:
    raw = decision.debug.get("cell_sinrs")
    if not isinstance(raw, dict):
        return {}
    return {
        str(cell_id): float(sinr)
        for cell_id, sinr in raw.items()
        if isinstance(sinr, (int, float))
    }


def _complexity_bucket(decision: PolicyDecisionRecord) -> str:
    complexity = decision.debug.get("candidate_complexity")
    if isinstance(complexity, dict):
        bucket = complexity.get("environment_complexity_bucket") or complexity.get(
            "complexity_bucket"
        )
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
