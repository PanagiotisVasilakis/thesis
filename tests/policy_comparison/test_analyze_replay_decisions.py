import json
from types import SimpleNamespace

from scripts.policy_comparison.analyze_replay_decisions import analyze_replay_decisions
from scripts.policy_comparison.schemas import PolicyDecisionRecord
from scripts.policy_comparison.trace_io import write_decisions_jsonl


def decision(step, *, source, bucket, target=None):
    return PolicyDecisionRecord(
        ue_id="ue-1",
        timestamp_s=float(step),
        step_index=step,
        current_serving_cell="cell-a" if step == 0 else "cell-b",
        selected_target_cell=target,
        decision_type="handover" if target else "stay",
        policy_name="complexity_aware_ml_a3",
        policy_parameters={},
        serving_measurement_value=-80.0,
        neighbour_measurements_considered={"cell-a": -82.0, "cell-b": -78.0},
        trigger_condition_result=target is not None,
        time_to_trigger_state={},
        cooldown_state={},
        reason="test",
        debug={
            "decision_source": source,
            "candidate_complexity": {
                "complexity_bucket": bucket,
                "viable_candidate_count": 3 if bucket == "high" else 1,
            },
            "ranker_candidate_scores": {"cell-b": 8.0},
            "ranker_selected_score": 8.0,
            "ranker_margin_vs_stay": 8.0,
        },
    )


def test_analyze_replay_decisions_reports_source_transitions(tmp_path):
    replay = tmp_path / "replay"
    write_decisions_jsonl(
        [
            decision(0, source="ml_high_complexity", bucket="high", target="cell-b"),
            decision(1, source="a3_complexity_gate", bucket="sparse", target="cell-a"),
        ],
        replay / "decisions" / "complexity_aware_ml_a3.jsonl",
    )

    report = analyze_replay_decisions(
        SimpleNamespace(
            replay_dir=str(replay),
            policy="complexity_aware_ml_a3",
            output_dir=None,
        )
    )

    payload = report["policy_reports"]["complexity_aware_ml_a3"]
    assert payload["handovers_by_decision_source"] == {
        "a3_complexity_gate": 1,
        "ml_high_complexity": 1,
    }
    assert payload["handover_source_transitions"] == {
        "ml_high_complexity->a3_complexity_gate": 1
    }
    assert payload["sparse_handovers_after_recent_ml"] == 1
    assert (replay / "decision_diagnostics" / "decision_diagnostics.json").exists()
    written = json.loads(
        (replay / "decision_diagnostics" / "decision_diagnostics.json").read_text()
    )
    assert written["policies"] == ["complexity_aware_ml_a3"]
