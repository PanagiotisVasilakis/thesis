"""Small pure-Python metrics for policy replay outputs."""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List, Tuple

from .models import PolicyDecision, PolicyEvaluationSummary


def summarize_decisions(
    decisions: Iterable[PolicyDecision],
    *,
    ping_pong_window_s: float = 60.0,
) -> PolicyEvaluationSummary:
    """Summarize decision outputs without relying on Prometheus.

    This is intentionally lightweight. The full experiment runner should still
    use the existing Prometheus/Grafana path for runtime metrics.
    """
    handover_count = 0
    stay_count = 0
    ping_pong_count = 0
    per_ue: Dict[str, Dict[str, int]] = defaultdict(
        lambda: {"handovers": 0, "stays": 0, "ping_pongs": 0}
    )
    last_handover: Dict[str, Tuple[str, str, float]] = {}

    for decision in decisions:
        ue_summary = per_ue[decision.ue_id]
        if decision.decision_type == "stay":
            stay_count += 1
            ue_summary["stays"] += 1
            continue

        handover_count += 1
        ue_summary["handovers"] += 1
        target = decision.selected_target_cell
        if target is None:
            continue

        previous = last_handover.get(decision.ue_id)
        if previous is not None:
            previous_from, previous_to, previous_time = previous
            if (
                previous_from == target
                and previous_to == decision.current_serving_cell
                and decision.timestamp_s - previous_time <= ping_pong_window_s
            ):
                ping_pong_count += 1
                ue_summary["ping_pongs"] += 1

        last_handover[decision.ue_id] = (
            decision.current_serving_cell,
            target,
            decision.timestamp_s,
        )

    return PolicyEvaluationSummary(
        handover_count=handover_count,
        stay_count=stay_count,
        ping_pong_count=ping_pong_count,
        per_ue=dict(per_ue),
    )


def decision_list_to_dicts(decisions: Iterable[PolicyDecision]) -> List[dict]:
    """Serialize decisions for future JSONL/JSON comparison outputs."""
    return [decision.to_dict() for decision in decisions]

