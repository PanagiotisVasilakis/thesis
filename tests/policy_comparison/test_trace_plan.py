import json

from scripts.policy_comparison.prepare_trace_plan import main
from scripts.policy_comparison.trace_plan import (
    TracePlanError,
    build_trace_preparation_plan,
    parse_int_list,
    validate_trace_split,
)


def test_parse_int_list_accepts_repeatable_and_comma_separated_values():
    assert parse_int_list(["1,2", "3"], field_name="seeds") == [1, 2, 3]


def test_trace_split_rejects_shared_seed():
    try:
        validate_trace_split(
            calibration_seeds=[1],
            evaluation_seeds=[1, 2],
            policies=["tuned_a3_baseline"],
        )
    except TracePlanError as exc:
        assert "disjoint" in str(exc)
    else:
        raise AssertionError("shared seeds should be rejected")


def test_trace_split_requires_single_calibration_seed_for_tuned_a3():
    try:
        validate_trace_split(
            calibration_seeds=[1, 2],
            evaluation_seeds=[3],
            policies=["tuned_a3_baseline"],
        )
    except TracePlanError as exc:
        assert "exactly one calibration trace" in str(exc)
    else:
        raise AssertionError("multiple tuned calibration seeds should be rejected")


def test_build_trace_plan_renders_capture_and_replay_commands(tmp_path):
    plan = build_trace_preparation_plan(
        scenario="highway",
        ue_ids=["ue-1,ue-2"],
        calibration_seeds=[10],
        evaluation_seeds=[20, 21],
        output_root=tmp_path / "trace_plan",
        samples=30,
        interval_s=0.5,
        timeout_s=3.0,
        policies=["fixed_a3_baseline", "tuned_a3_baseline"],
        nef_url="http://nef.local",
        topology_hash="topology",
        python_bin="python3",
    )

    assert len(plan.calibration_traces) == 1
    assert len(plan.evaluation_traces) == 2
    assert len(plan.capture_commands) == 3
    assert len(plan.replay_commands) == 2
    assert "--calibration-trace" in plan.replay_commands[0]
    assert "--nef-url http://nef.local" in plan.capture_commands[0]
    assert "highway_evaluation_seed20" in plan.replay_commands[0]


def test_prepare_trace_plan_cli_writes_plan_and_commands(tmp_path):
    output_root = tmp_path / "prepared"

    code = main(
        [
            "--scenario",
            "highway",
            "--ue-id",
            "ue-1,ue-2",
            "--calibration-seed",
            "10",
            "--evaluation-seed",
            "20",
            "--output-root",
            str(output_root),
            "--samples",
            "5",
            "--interval-s",
            "0.1",
            "--policies",
            "fixed_a3_baseline,tuned_a3_baseline",
        ]
    )

    assert code == 0
    plan = json.loads((output_root / "trace_plan.json").read_text(encoding="utf-8"))
    commands = (output_root / "trace_commands.sh").read_text(encoding="utf-8")

    assert plan["scenario"] == "highway"
    assert plan["ue_ids"] == ["ue-1", "ue-2"]
    assert "capture_nef_trace" in commands
    assert "run_offline_replay" in commands


def test_prepare_trace_plan_cli_rejects_nonempty_output_root(tmp_path):
    output_root = tmp_path / "prepared"
    output_root.mkdir()
    (output_root / "old.txt").write_text("old", encoding="utf-8")

    code = main(
        [
            "--scenario",
            "highway",
            "--ue-id",
            "ue-1",
            "--evaluation-seed",
            "20",
            "--output-root",
            str(output_root),
            "--policies",
            "fixed_a3_baseline",
        ]
    )

    assert code == 1


def test_prepare_trace_plan_cli_allows_fixed_a3_without_calibration(tmp_path):
    output_root = tmp_path / "prepared"

    code = main(
        [
            "--scenario",
            "highway",
            "--ue-id",
            "ue-1",
            "--evaluation-seed",
            "20",
            "--output-root",
            str(output_root),
            "--policies",
            "fixed_a3_baseline",
        ]
    )

    assert code == 0
    plan = json.loads((output_root / "trace_plan.json").read_text(encoding="utf-8"))
    assert plan["calibration_traces"] == []
    assert "--calibration-trace" not in plan["replay_commands"][0]
