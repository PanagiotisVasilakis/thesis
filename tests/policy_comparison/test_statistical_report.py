import json

import pytest

from scripts.policy_comparison.statistical_report import (
    StatisticalReportError,
    build_statistical_report,
    load_run_metrics,
    markdown_report,
    metric_direction,
    write_statistical_report,
)
from scripts.policy_comparison.summarize_policy_statistics import main as stats_main


def write_offline_run(
    root,
    *,
    seed,
    fixed_handovers,
    ml_handovers,
    topology_hash="topology-a",
):
    run_dir = root / f"offline_seed_{seed}"
    run_dir.mkdir()
    (run_dir / "summary.json").write_text(
        json.dumps(
            {
                "scenario": "highway",
                "seed": seed,
                "topology_hash": topology_hash,
                "policy_results": {
                    "fixed_a3_baseline": {
                        "summary": {
                            "handover_count": fixed_handovers,
                            "ping_pong_count": 2,
                            "avg_dwell_time_s": 10.0,
                        }
                    },
                    "ml_policy": {
                        "summary": {
                            "handover_count": ml_handovers,
                            "ping_pong_count": 1,
                            "avg_dwell_time_s": 12.0,
                        }
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    return run_dir


def write_live_run(root, *, seed, fixed_handovers, ml_handovers):
    run_dir = root / f"live_seed_{seed}"
    run_dir.mkdir()
    (run_dir / "experiment_summary.json").write_text(
        json.dumps(
            {
                "experiment": {
                    "scenario": "highway",
                    "seed": seed,
                    "topology_hash": "live-topology",
                },
                "policy_metrics": {
                    "fixed_a3_baseline": {"total_handovers": fixed_handovers},
                    "ml": {"total_handovers": ml_handovers},
                },
            }
        ),
        encoding="utf-8",
    )
    return run_dir


def test_load_run_metrics_detects_offline_and_live(tmp_path):
    offline = write_offline_run(
        tmp_path,
        seed=1,
        fixed_handovers=10,
        ml_handovers=7,
    )
    live = write_live_run(tmp_path, seed=1, fixed_handovers=12, ml_handovers=9)

    offline_metrics = load_run_metrics(offline)
    live_metrics = load_run_metrics(live)

    assert offline_metrics.evidence_type == "offline_replay"
    assert offline_metrics.policy_metrics["ml_policy"]["handover_count"] == 7.0
    assert live_metrics.evidence_type == "live_experiment"
    assert live_metrics.policy_metrics["ml"]["total_handovers"] == 9.0


def test_statistical_report_keeps_evidence_types_separate(tmp_path):
    runs = [
        load_run_metrics(
            write_offline_run(tmp_path, seed=1, fixed_handovers=10, ml_handovers=7)
        ),
        load_run_metrics(
            write_offline_run(tmp_path, seed=2, fixed_handovers=11, ml_handovers=8)
        ),
        load_run_metrics(write_live_run(tmp_path, seed=1, fixed_handovers=12, ml_handovers=9)),
        load_run_metrics(write_live_run(tmp_path, seed=2, fixed_handovers=13, ml_handovers=10)),
    ]

    offline_report = build_statistical_report(
        runs,
        reference_policy="fixed_a3_baseline",
        candidate_policy="ml_policy",
        metrics=["handover_count"],
        evidence_type="offline_replay",
        bootstrap_iterations=100,
        seed=7,
    )
    live_report = build_statistical_report(
        runs,
        reference_policy="fixed_a3_baseline",
        candidate_policy="ml",
        metrics=["total_handovers"],
        evidence_type="live_experiment",
        bootstrap_iterations=100,
        seed=7,
    )

    assert set(offline_report.comparisons) == {"offline_replay"}
    assert set(live_report.comparisons) == {"live_experiment"}
    comparison = offline_report.comparisons["offline_replay"][0]
    assert comparison.mean_improvement == pytest.approx(3.0)
    assert comparison.direction == "lower_is_better"


def test_report_marks_insufficient_pairs(tmp_path):
    run = load_run_metrics(
        write_offline_run(tmp_path, seed=1, fixed_handovers=10, ml_handovers=7)
    )

    report = build_statistical_report(
        [run],
        reference_policy="fixed_a3_baseline",
        candidate_policy="ml_policy",
        metrics=["handover_count"],
    )

    comparison = report.comparisons["offline_replay"][0]
    assert comparison.test_type == "insufficient_pairs"
    assert "need at least 2 paired runs" in report.warnings[0]


def test_metric_direction_is_explicit():
    assert metric_direction("handover_count") == "lower_is_better"
    assert metric_direction("composite_cost") == "lower_is_better"
    assert metric_direction("complexity_high_composite_cost") == "lower_is_better"
    assert metric_direction("avg_dwell_time_s") == "higher_is_better"
    assert metric_direction("custom_metric") == "neutral_delta"


def test_write_statistical_report_rejects_nonempty_output(tmp_path):
    runs = [
        load_run_metrics(
            write_offline_run(tmp_path, seed=1, fixed_handovers=10, ml_handovers=7)
        ),
        load_run_metrics(
            write_offline_run(tmp_path, seed=2, fixed_handovers=11, ml_handovers=8)
        ),
    ]
    report = build_statistical_report(
        runs,
        reference_policy="fixed_a3_baseline",
        candidate_policy="ml_policy",
        metrics=["handover_count"],
        bootstrap_iterations=100,
    )
    output_dir = tmp_path / "report"
    write_statistical_report(report, output_dir)

    with pytest.raises(StatisticalReportError, match="already exists"):
        write_statistical_report(report, output_dir)

    markdown = markdown_report(report)
    assert "offline_replay" in markdown
    assert "handover_count" in markdown


def test_statistics_cli_writes_report(tmp_path):
    run1 = write_offline_run(tmp_path, seed=1, fixed_handovers=10, ml_handovers=7)
    run2 = write_offline_run(tmp_path, seed=2, fixed_handovers=11, ml_handovers=8)
    output_dir = tmp_path / "cli_report"

    exit_code = stats_main(
        [
            "--run",
            str(run1),
            "--run",
            str(run2),
            "--reference-policy",
            "fixed_a3_baseline",
            "--candidate-policy",
            "ml_policy",
            "--metrics",
            "handover_count",
            "--bootstrap-iterations",
            "100",
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 0
    assert (output_dir / "policy_statistical_report.json").is_file()
    assert (output_dir / "policy_statistical_report.md").is_file()
