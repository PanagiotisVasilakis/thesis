"""Deterministic offline replay for fair policy comparison."""

from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import groupby
from typing import Any, Dict, List, Mapping, Sequence

from .metrics import PolicyMetricSummary, summarize_policy_decisions
from .policy_adapters import ComparisonPolicyAdapter
from .schemas import MeasurementTraceRecord, PolicyDecisionRecord
from .qos_model import estimate_counterfactual_qos, qos_compliance


@dataclass(frozen=True)
class PolicyReplayResult:
    """Decision log and summary for one policy replay."""

    policy_name: str
    decisions: List[PolicyDecisionRecord]
    summary: PolicyMetricSummary

    def to_dict(self) -> Dict[str, object]:
        return {
            "policy_name": self.policy_name,
            "decisions": [decision.to_dict() for decision in self.decisions],
            "summary": self.summary.to_dict(),
        }


@dataclass(frozen=True)
class ReplayResult:
    """Full offline replay result across all selected policies."""

    scenario: str
    seed: int
    topology_hash: str | None
    policy_results: Dict[str, PolicyReplayResult]

    def to_dict(self) -> Dict[str, object]:
        return {
            "scenario": self.scenario,
            "seed": self.seed,
            "topology_hash": self.topology_hash,
            "policy_results": {
                name: result.to_dict() for name, result in self.policy_results.items()
            },
        }


class OfflineReplayRunner:
    """Replay the same measurement snapshots through multiple policies."""

    def __init__(self, policies: Sequence[ComparisonPolicyAdapter]) -> None:
        if not policies:
            raise ValueError("at least one policy adapter is required")
        names = [policy.name for policy in policies]
        if len(set(names)) != len(names):
            raise ValueError("policy adapter names must be unique")
        self.policies = list(policies)

    def replay(self, records: Sequence[MeasurementTraceRecord]) -> ReplayResult:
        """Replay a canonical trace without mutating the original records."""
        if not records:
            raise ValueError("records must not be empty")

        ordered = sorted(records, key=lambda item: (item.timestamp_s, item.step_index, item.ue_id))
        scenario = ordered[0].scenario
        seed = ordered[0].seed
        topology_hash = ordered[0].topology_hash
        for record in ordered:
            if record.scenario != scenario:
                raise ValueError("all trace records must use the same scenario")
            if record.seed != seed:
                raise ValueError("all trace records must use the same seed")
            if record.topology_hash != topology_hash:
                raise ValueError("all trace records must use the same topology_hash")

        serving_by_policy: Dict[str, Dict[str, str]] = {
            policy.name: {} for policy in self.policies
        }
        replay_state_by_policy: Dict[str, Dict[str, Dict[str, Any]]] = {
            policy.name: {} for policy in self.policies
        }
        decisions_by_policy: Dict[str, List[PolicyDecisionRecord]] = {
            policy.name: [] for policy in self.policies
        }

        warmup_record = max(ordered, key=lambda item: len(item.visible_cells))
        for policy in self.policies:
            policy.reset()
            warmup = getattr(policy, "warmup", None)
            if callable(warmup):
                warmup(warmup_record)
        for policy in self.policies:
            policy.reset()

        for _snapshot_key, snapshot_items in groupby(
            ordered,
            key=lambda item: (item.timestamp_s, item.step_index),
        ):
            snapshot = list(snapshot_items)
            for policy in self.policies:
                policy_serving_by_ue = serving_by_policy[policy.name]
                for item in snapshot:
                    policy_serving_by_ue.setdefault(item.ue_id, item.serving_cell)
                policy_loads: Dict[str, int] = {}
                for serving in policy_serving_by_ue.values():
                    policy_loads[serving] = policy_loads.get(serving, 0) + 1

                for record in snapshot:
                    current_serving = policy_serving_by_ue[record.ue_id]
                    policy_record = _with_policy_context(
                        record,
                        current_serving=current_serving,
                        policy_loads=policy_loads,
                    )
                    state = _state_for_decision(
                        replay_state_by_policy[policy.name],
                        policy_record,
                        current_serving,
                    )
                    setter = getattr(policy, "set_replay_state", None)
                    if callable(setter):
                        setter(record.ue_id, state)
                    decision = policy.decide(policy_record)
                    compliance = qos_compliance(
                        policy_record.qos_requirements,
                        policy_record.observed_qos or {},
                    )
                    decision = replace(
                        decision,
                        debug={
                            **decision.debug,
                            "qos_compliance": compliance,
                            "counterfactual_qos": policy_record.observed_qos,
                            "policy_specific_loads": policy_loads,
                        },
                    )
                    decisions_by_policy[policy.name].append(decision)
                    if (
                        decision.decision_type == "handover"
                        and decision.selected_target_cell is not None
                    ):
                        policy_serving_by_ue[record.ue_id] = decision.selected_target_cell
                        _record_handover_state(
                            replay_state_by_policy[policy.name],
                            decision,
                        )

        return ReplayResult(
            scenario=scenario,
            seed=seed,
            topology_hash=topology_hash,
            policy_results={
                policy.name: PolicyReplayResult(
                    policy_name=policy.name,
                    decisions=decisions_by_policy[policy.name],
                    summary=summarize_policy_decisions(
                        policy.name,
                        decisions_by_policy[policy.name],
                        metric_version="v3_physical_qos_cost",
                    ),
                )
                for policy in self.policies
            },
        )


def _with_policy_context(
    record: MeasurementTraceRecord,
    *,
    current_serving: str,
    policy_loads: Mapping[str, int],
) -> MeasurementTraceRecord:
    serving_record = record.with_serving_cell(current_serving)
    cells = [
        replace(cell, load=float(policy_loads.get(cell.cell_id, 0)))
        for cell in serving_record.visible_cells
    ]
    contextual = replace(serving_record, visible_cells=cells)
    observed = estimate_counterfactual_qos(
        contextual,
        serving_cell=current_serving,
        load=float(policy_loads.get(current_serving, 0)),
    )
    return replace(contextual, observed_qos=observed)


def replay_summary_table(result: ReplayResult) -> Mapping[str, Mapping[str, object]]:
    """Return a compact policy-to-summary mapping for reports/tests."""
    return {
        policy_name: policy_result.summary.to_dict()
        for policy_name, policy_result in result.policy_results.items()
    }


def _state_for_decision(
    states_by_ue: Dict[str, Dict[str, Any]],
    record: MeasurementTraceRecord,
    current_serving: str,
) -> Dict[str, Any]:
    state = states_by_ue.setdefault(
        record.ue_id,
        {
            "handover_timestamps_s": [],
            "last_handover_time_s": None,
            "last_handover_source": None,
            "previous_serving_cell": None,
            "previous_target_cell": None,
            "dwell_started_at_s": record.timestamp_s,
        },
    )
    timestamps = [
        float(item)
        for item in state.get("handover_timestamps_s", [])
        if record.timestamp_s - float(item) <= 60.0
    ]
    state["handover_timestamps_s"] = timestamps
    last_time = state.get("last_handover_time_s")
    time_since = None if last_time is None else max(0.0, record.timestamp_s - float(last_time))
    dwell_started = float(state.get("dwell_started_at_s", record.timestamp_s))
    return {
        "current_serving_cell": current_serving,
        "recent_handover_count": len(timestamps),
        "time_since_last_handover_s": time_since,
        "last_handover_source": state.get("last_handover_source"),
        "previous_serving_cell": state.get("previous_serving_cell"),
        "previous_target_cell": state.get("previous_target_cell"),
        "current_dwell_time_s": max(0.0, record.timestamp_s - dwell_started),
    }


def _record_handover_state(
    states_by_ue: Dict[str, Dict[str, Any]],
    decision: PolicyDecisionRecord,
) -> None:
    state = states_by_ue.setdefault(decision.ue_id, {})
    timestamps = list(state.get("handover_timestamps_s", []))
    timestamps.append(float(decision.timestamp_s))
    state["handover_timestamps_s"] = timestamps
    state["last_handover_time_s"] = float(decision.timestamp_s)
    state["last_handover_source"] = (
        decision.debug.get("decision_source") or decision.policy_name
    )
    state["previous_serving_cell"] = decision.current_serving_cell
    state["previous_target_cell"] = decision.selected_target_cell
    state["dwell_started_at_s"] = float(decision.timestamp_s)
