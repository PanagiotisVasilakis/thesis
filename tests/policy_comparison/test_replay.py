from scripts.policy_comparison.nef_trace import feature_vector_to_trace_record
from scripts.policy_comparison.replay import OfflineReplayRunner
from scripts.policy_comparison.schemas import MeasurementTraceRecord, PolicyDecisionRecord


def record(step, serving="cell-a"):
    return feature_vector_to_trace_record(
        {
            "ue_id": "ue-1",
            "latitude": 37.1,
            "longitude": 23.2,
            "connected_to": serving,
            "neighbor_rsrp_dbm": {"cell-a": -84.0, "cell-b": -78.0},
        },
        scenario="highway",
        seed=11,
        step_index=step,
        timestamp_s=float(step),
        topology_hash="same-topology",
    )


class RecordingPolicy:
    def __init__(self, name, handover_on_first_step=False):
        self._name = name
        self.handover_on_first_step = handover_on_first_step
        self.seen_serving_cells = []
        self.warmup_calls = 0

    @property
    def name(self):
        return self._name

    @property
    def parameters(self):
        return {"handover_on_first_step": self.handover_on_first_step}

    def reset(self, ue_id=None):
        self.seen_serving_cells.clear()

    def decide(self, trace_record: MeasurementTraceRecord):
        self.seen_serving_cells.append(trace_record.serving_cell)
        decision_type = (
            "handover"
            if self.handover_on_first_step and trace_record.step_index == 0
            else "stay"
        )
        selected_target = "cell-b" if decision_type == "handover" else None
        return PolicyDecisionRecord(
            ue_id=trace_record.ue_id,
            timestamp_s=trace_record.timestamp_s,
            step_index=trace_record.step_index,
            current_serving_cell=trace_record.serving_cell,
            selected_target_cell=selected_target,
            decision_type=decision_type,
            policy_name=self.name,
            policy_parameters=self.parameters,
            serving_measurement_value=trace_record.visible_cell_map[
                trace_record.serving_cell
            ].rsrp_dbm,
            neighbour_measurements_considered={
                cell.cell_id: cell.rsrp_dbm
                for cell in trace_record.visible_cells
                if cell.cell_id != trace_record.serving_cell
            },
            trigger_condition_result=decision_type == "handover",
            time_to_trigger_state={},
            cooldown_state={},
            reason="test",
            decision_latency_ms=0.1,
        )


class WarmRecordingPolicy(RecordingPolicy):
    def warmup(self, trace_record):
        self.warmup_calls += 1
        self.seen_serving_cells.append(f"warm:{trace_record.serving_cell}")


def test_replay_uses_separate_serving_state_per_policy():
    handover_policy = RecordingPolicy("handover-policy", handover_on_first_step=True)
    stay_policy = RecordingPolicy("stay-policy")
    runner = OfflineReplayRunner([handover_policy, stay_policy])

    result = runner.replay([record(0), record(1)])

    assert handover_policy.seen_serving_cells == ["cell-a", "cell-b"]
    assert stay_policy.seen_serving_cells == ["cell-a", "cell-a"]
    assert result.policy_results["handover-policy"].summary.handover_count == 1
    assert result.policy_results["stay-policy"].summary.stay_count == 2


def test_replay_rejects_mixed_topology_hashes():
    runner = OfflineReplayRunner([RecordingPolicy("policy")])
    first = record(0)
    second = feature_vector_to_trace_record(
        {
            "ue_id": "ue-1",
            "latitude": 37.1,
            "longitude": 23.2,
            "connected_to": "cell-a",
            "neighbor_rsrp_dbm": {"cell-a": -84.0, "cell-b": -78.0},
        },
        scenario="highway",
        seed=11,
        step_index=1,
        timestamp_s=1.0,
        topology_hash="different-topology",
    )

    try:
        runner.replay([first, second])
    except ValueError as exc:
        assert "same topology_hash" in str(exc)
    else:
        raise AssertionError("mixed topology hashes should be rejected")


def test_replay_warms_policy_then_resets_state_before_measurement():
    policy = WarmRecordingPolicy("warm-policy")

    OfflineReplayRunner([policy]).replay([record(0), record(1)])

    assert policy.warmup_calls == 1
    assert policy.seen_serving_cells == ["cell-a", "cell-a"]
