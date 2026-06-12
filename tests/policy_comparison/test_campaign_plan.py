import json

from scripts.policy_comparison.campaign_plan import (
    CampaignPlanError,
    build_comparison_campaign_plan,
    write_comparison_campaign_plan,
)
from scripts.policy_comparison.prepare_comparison_campaign import main


def test_campaign_plan_builds_safe_live_and_analysis_commands(tmp_path):
    plan = build_comparison_campaign_plan(
        campaign_name="highway_validation",
        output_root=tmp_path / "campaign",
        primary_scenario="highway",
        evaluation_seeds=[42, 43],
        policies=["ml", "fixed_a3_baseline"],
        ue_ids=["ue-1", "ue-2"],
        duration_minutes=10,
    )

    assert plan.primary_scenario == "highway"
    assert len(plan.primary_live_runs) == 2
    assert plan.secondary_live_runs == []
    assert "prepare_trace_plan" in (plan.offline_trace_plan_command or "")
    assert "--plan-only" in plan.primary_live_runs[0].plan_only_command
    assert "run_enhanced_experiment.py" in plan.primary_live_runs[0].run_command
    assert plan.primary_live_runs[0].run_command.startswith(".venv/bin/python")
    assert "validate_comparison_outputs" in plan.validation_commands[0]
    assert "summarize_policy_statistics" in plan.statistics_commands[0]


def test_campaign_plan_rejects_unknown_scenario(tmp_path):
    try:
        build_comparison_campaign_plan(
            campaign_name="bad",
            output_root=tmp_path / "campaign",
            primary_scenario="not_a_scenario",
            evaluation_seeds=[42],
            policies=["ml", "fixed_a3_baseline"],
            ue_ids=["ue-1"],
            duration_minutes=10,
        )
    except CampaignPlanError as exc:
        assert "unknown scenario" in str(exc)
    else:
        raise AssertionError("unknown scenario should fail")


def test_campaign_plan_requires_ml_and_fixed_a3(tmp_path):
    try:
        build_comparison_campaign_plan(
            campaign_name="bad",
            output_root=tmp_path / "campaign",
            primary_scenario="highway",
            evaluation_seeds=[42],
            policies=["ml"],
            ue_ids=["ue-1"],
            duration_minutes=10,
        )
    except CampaignPlanError as exc:
        assert "fixed_a3_baseline" in str(exc)
    else:
        raise AssertionError("missing fixed baseline should fail")


def test_campaign_plan_rejects_tuned_without_real_config(tmp_path):
    try:
        build_comparison_campaign_plan(
            campaign_name="bad",
            output_root=tmp_path / "campaign",
            primary_scenario="highway",
            evaluation_seeds=[42],
            calibration_seed=41,
            policies=["ml", "fixed_a3_baseline", "tuned_a3_baseline"],
            ue_ids=["ue-1"],
            duration_minutes=10,
        )
    except CampaignPlanError as exc:
        assert "tuned-a3-config" in str(exc)
    else:
        raise AssertionError("missing tuned config should fail")


def test_campaign_plan_rejects_tuned_calibration_overlap(tmp_path):
    tuned_config = tmp_path / "tuned.json"
    tuned_config.write_text(
        json.dumps(
            {
                "selected_parameters": {
                    "a3_offset_db": 0.0,
                    "hysteresis_db": 2.0,
                    "time_to_trigger_s": 1.0,
                    "cooldown_s": 2.0,
                }
            }
        ),
        encoding="utf-8",
    )

    try:
        build_comparison_campaign_plan(
            campaign_name="bad",
            output_root=tmp_path / "campaign",
            primary_scenario="highway",
            evaluation_seeds=[42],
            calibration_seed=42,
            policies=["ml", "fixed_a3_baseline", "tuned_a3_baseline"],
            tuned_a3_config=tuned_config,
            ue_ids=["ue-1"],
            duration_minutes=10,
        )
    except CampaignPlanError as exc:
        assert "disjoint" in str(exc)
    else:
        raise AssertionError("calibration/evaluation overlap should fail")


def test_write_campaign_plan_creates_command_files(tmp_path):
    root = tmp_path / "campaign"
    root.mkdir()
    plan = build_comparison_campaign_plan(
        campaign_name="highway_validation",
        output_root=root,
        primary_scenario="highway",
        secondary_scenario="smart_city",
        evaluation_seeds=[42],
        policies=["ml", "fixed_a3_baseline"],
        ue_ids=["ue-1"],
        duration_minutes=10,
        secondary_duration_minutes=5,
    )

    plan_path, offline_path, live_path, analysis_path = write_comparison_campaign_plan(
        plan,
        root,
    )

    assert plan_path.is_file()
    assert offline_path.is_file()
    assert live_path.is_file()
    assert analysis_path.is_file()
    assert "smart_city" in json.loads(plan_path.read_text(encoding="utf-8"))[
        "secondary_scenario"
    ]
    assert "# " + plan.primary_live_runs[0].run_command in live_path.read_text(
        encoding="utf-8"
    )


def test_prepare_comparison_campaign_cli_writes_plan(tmp_path):
    output_root = tmp_path / "campaign"

    code = main(
        [
            "--campaign-name",
            "highway_validation",
            "--output-root",
            str(output_root),
            "--primary-scenario",
            "highway",
            "--evaluation-seed",
            "42,43",
            "--ue-id",
            "ue-1,ue-2",
            "--policies",
            "ml,fixed_a3_baseline",
        ]
    )

    assert code == 0
    assert (output_root / "comparison_campaign_plan.json").is_file()
    assert (output_root / "offline_commands.sh").is_file()
    assert (output_root / "live_commands.sh").is_file()
    assert (output_root / "analysis_commands.sh").is_file()


def test_prepare_comparison_campaign_cli_rejects_nonempty_root(tmp_path):
    output_root = tmp_path / "campaign"
    output_root.mkdir()
    (output_root / "old.txt").write_text("old", encoding="utf-8")

    code = main(
        [
            "--campaign-name",
            "highway_validation",
            "--output-root",
            str(output_root),
            "--evaluation-seed",
            "42",
            "--ue-id",
            "ue-1",
        ]
    )

    assert code == 1
