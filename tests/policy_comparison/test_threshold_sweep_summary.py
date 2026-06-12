import json
from types import SimpleNamespace

from scripts.policy_comparison.summarize_threshold_sweep import (
    summarize_threshold_sweep,
)


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def decision(policy_name, debug, *, target=None):
    return {
        "ue_id": "ue-1",
        "timestamp_s": 1.0,
        "step_index": 1,
        "current_serving_cell": "cell-a",
        "selected_target_cell": target,
        "decision_type": "handover" if target else "stay",
        "policy_name": policy_name,
        "policy_parameters": {},
        "serving_measurement_value": -82.0,
        "neighbour_measurements_considered": {"cell-b": -79.0},
        "trigger_condition_result": target is not None,
        "time_to_trigger_state": {},
        "cooldown_state": {},
        "reason": "unit-test",
        "debug": debug,
    }


def ranker_debug(bucket="high", source="candidate_ranker"):
    return {
        "decision_source": source,
        "ml_backend": "candidate_ranker",
        "ranker_candidate_scores": {"cell-b": 3.0},
        "ranker_best_candidate": "cell-b",
        "ranker_best_candidate_score": 3.0,
        "ranker_selected_candidate": "cell-b",
        "ranker_selected_score": 3.0,
        "ranker_score_threshold": 2.0,
        "ranker_stay_score": 0.0,
        "ranker_margin_vs_stay": 3.0,
        "ranker_min_margin": 2.0,
        "dwell_guard_applied": False,
        "ranker_artifact_sha256": "abc123",
        "ranker_model_family": "candidate_ranker",
        "ranker_metadata": {
            "model_type": "candidate_ranker_lightgbm_regressor",
            "model_family": "candidate_ranker",
            "target": "utility_margin_vs_stay",
            "selected_features": ["delta_rsrp_db"],
            "validation_metrics": {"validation_rmse": 0.1},
            "threshold_tuning_result": {"selected_threshold": 2.0},
            "seed_split": {"validation_group_count": 1},
            "dataset_size": 4,
            "scenario_seeds": [41],
            "model_sha256": "abc123",
            "complexity_bucket_counts": {"high": 4},
            "high_complexity_row_count": 4,
            "min_high_complexity_rows": 1,
            "trace_complexity_summaries": [
                {
                    "trace": "trace.jsonl",
                    "record_count": 2,
                    "thresholds": {"3": {"high": 2, "high_fraction": 1.0}},
                }
            ],
        },
        "candidate_complexity": {
            "viable_candidate_count": 3 if bucket == "high" else 1,
            "complexity_bucket": bucket,
            "viable_candidates": ["cell-b"],
        },
        "ml_target_resolution": {
            "raw_target": "cell-b",
            "resolved_target": "cell-b",
            "method": "candidate_ranker_score",
        },
        "qos_compliance": {"evaluated": False, "service_priority_ok": True, "violations": []},
        "raw_ml_response_metadata": {
            "ml_backend": "candidate_ranker",
            "ranker_artifact_sha256": "abc123",
        },
    }


def write_decision_log(run_dir, policy, records):
    path = run_dir / "decisions" / f"{policy}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )


def write_run(
    root,
    *,
    seed,
    comp_high,
    tuned_high,
    comp_total,
    ml_total,
    tuned_total,
):
    run_dir = root / f"offline_replay_seed{seed}"
    write_json(
        run_dir / "summary.json",
        {
            "scenario": "highway",
            "seed": seed,
            "topology_hash": "topology",
            "policy_results": {
                "tuned_a3_baseline": {
                    "summary": {
                        "handover_count": 3,
                        "ping_pong_count": 1,
                        "qos_violation_proxy_count": 0,
                        "composite_cost": tuned_total,
                        "complexity_high_composite_cost": tuned_high,
                        "complexity_bucket_counts": {"high": 1},
                    }
                },
                "ml_policy": {
                    "summary": {
                        "handover_count": 4,
                        "ping_pong_count": 1,
                        "qos_violation_proxy_count": 0,
                        "composite_cost": ml_total,
                        "complexity_high_composite_cost": comp_high,
                        "complexity_bucket_counts": {"high": 1},
                    }
                },
                "complexity_aware_ml_a3": {
                    "summary": {
                        "handover_count": 2,
                        "ping_pong_count": 1,
                        "qos_violation_proxy_count": 0,
                        "composite_cost": comp_total,
                        "complexity_high_composite_cost": comp_high,
                        "complexity_bucket_counts": {"high": 1},
                    }
                },
            },
        },
    )
    write_json(run_dir / "manifest.json", {"scenario": "highway"})
    write_json(
        run_dir / "tuned_a3_config.json",
        {
            "selected_parameters": {
                "a3_offset_db": 0.0,
                "hysteresis_db": 2.0,
                "time_to_trigger_s": 1.0,
                "cooldown_s": 2.0,
            },
            "evaluated_configuration_scores": [{"score": 1.0}],
        },
    )
    write_decision_log(
        run_dir,
        "tuned_a3_baseline",
        [decision("tuned_a3_baseline", {"candidate_complexity": {"viable_candidate_count": 1, "complexity_bucket": "sparse"}})],
    )
    write_decision_log(
        run_dir,
        "ml_policy",
        [decision("ml_policy", ranker_debug(), target="cell-b")],
    )
    comp_debug = ranker_debug(bucket="high", source="ml_high_complexity")
    comp_debug["delegated_policy"] = "ml_policy"
    write_decision_log(
        run_dir,
        "complexity_aware_ml_a3",
        [decision("complexity_aware_ml_a3", comp_debug, target="cell-b")],
    )
    return run_dir


def args(root, output):
    return SimpleNamespace(
        sweep_root=str(root),
        output_dir=str(output),
        required_seeds="42,43",
        expected_policies="tuned_a3_baseline,ml_policy,complexity_aware_ml_a3",
        min_high_improvement=0.05,
    )


def test_threshold_sweep_summary_selects_passing_threshold(tmp_path):
    sweep = tmp_path / "sweep"
    write_run(
        sweep / "threshold_3",
        seed=42,
        comp_high=8.0,
        tuned_high=10.0,
        comp_total=20.0,
        ml_total=25.0,
        tuned_total=24.0,
    )
    write_run(
        sweep / "threshold_3",
        seed=43,
        comp_high=7.0,
        tuned_high=10.0,
        comp_total=19.0,
        ml_total=25.0,
        tuned_total=24.0,
    )
    write_run(
        sweep / "threshold_4",
        seed=42,
        comp_high=11.0,
        tuned_high=10.0,
        comp_total=26.0,
        ml_total=25.0,
        tuned_total=24.0,
    )
    write_run(
        sweep / "threshold_4",
        seed=43,
        comp_high=11.0,
        tuned_high=10.0,
        comp_total=26.0,
        ml_total=25.0,
        tuned_total=24.0,
    )

    report = summarize_threshold_sweep(args(sweep, tmp_path / "summary"))

    assert report["pass"] is True
    assert report["selected_threshold"] == 3
    assert (tmp_path / "summary" / "threshold_sweep_summary.json").exists()


def test_threshold_sweep_summary_fails_when_high_complexity_loses(tmp_path):
    sweep = tmp_path / "sweep"
    for seed in (42, 43):
        write_run(
            sweep / "threshold_3",
            seed=seed,
            comp_high=12.0,
            tuned_high=10.0,
            comp_total=20.0,
            ml_total=25.0,
            tuned_total=24.0,
        )

    report = summarize_threshold_sweep(args(sweep, tmp_path / "summary"))

    assert report["pass"] is False
    assert report["selected_threshold"] is None
    assert report["thresholds"][0]["fail_reasons"]
