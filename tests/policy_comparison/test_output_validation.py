import json

from scripts.policy_comparison.output_validation import validate_comparison_output
from scripts.policy_comparison.validate_comparison_outputs import main as validate_main


def decision(
    policy_name="fixed_a3_baseline",
    neighbours=None,
    confidence=None,
    debug=None,
    selected_target=None,
):
    if debug is None and policy_name == "ml_policy":
        debug = {
            "ml_response_keys": ["confidence", "predicted_antenna", "qos_compliance"],
            "qos_compliance": {"checked": True, "passed": True},
            "raw_ml_response_metadata": {},
            "ml_target_resolution": {
                "raw_target": "cell-b",
                "resolved_target": "cell-b",
                "method": "direct",
            },
            "candidate_complexity": {
                "viable_candidate_count": 1,
                "complexity_bucket": "sparse",
                "viable_candidates": ["cell-b"],
                "thresholds": {
                    "min_rsrp_dbm": -115.0,
                    "min_sinr_db": -5.0,
                    "high_complexity_threshold": 3.0,
                },
            },
        }
    payload = {
        "ue_id": "ue-1",
        "timestamp_s": 1.0,
        "step_index": 1,
        "current_serving_cell": "cell-a",
        "selected_target_cell": selected_target,
        "decision_type": "handover" if selected_target is not None else "stay",
        "policy_name": policy_name,
        "policy_parameters": {"a3_offset_db": 0.0},
        "serving_measurement_value": -82.0,
        "neighbour_measurements_considered": (
            {"cell-b": -79.0} if neighbours is None else neighbours
        ),
        "trigger_condition_result": selected_target is not None,
        "time_to_trigger_state": {},
        "cooldown_state": {},
        "reason": "threshold_not_met",
        "debug": debug or {},
        "confidence": confidence,
    }
    if confidence is None:
        payload.pop("confidence")
    return payload


def ranker_debug():
    return {
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
            "viable_candidate_count": 1,
            "complexity_bucket": "sparse",
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


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_decision_log(root, policy_name, records):
    path = root / "decisions" / f"{policy_name}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )


def write_valid_offline_output(root):
    root.mkdir()
    write_json(
        root / "summary.json",
        {
            "scenario": "highway",
            "seed": 42,
            "topology_hash": "topology-hash",
            "policy_results": {
                "fixed_a3_baseline": {
                    "summary": {"handover_count": 0, "ping_pong_count": 0},
                },
                "ml_policy": {
                    "summary": {"handover_count": 1, "ping_pong_count": 0},
                },
            },
        },
    )
    write_json(root / "manifest.json", {"scenario": "highway"})
    write_decision_log(root, "fixed_a3_baseline", [decision()])
    write_decision_log(root, "ml_policy", [decision("ml_policy", confidence=0.87)])
    return root


def write_topology(root, policy):
    write_json(
        root / "topology" / f"{policy}_topology.json",
        {
            "metadata": {"name": "Highway"},
            "cells": [{"cell_id": "cell-a"}],
            "ues": [{"supi": "ue-1"}],
            "paths": [{"description": "path"}],
        },
    )


def write_valid_live_output(root, policies=("ml", "fixed_a3_baseline")):
    root.mkdir()
    write_json(
        root / "experiment_summary.json",
        {
            "experiment": {
                "scenario": "highway",
                "seed": 42,
                "policies": list(policies),
                "topology_hash": "topology-hash",
            },
            "policy_metrics": {
                policy: (
                    {
                        "total_handovers": index,
                        "skipped_handovers": 10 + index,
                        "pingpong_suppressions": 0,
                        "qos_compliance_ok": 1,
                        "qos_compliance_failed": 0,
                        "avg_confidence": 0.8,
                    }
                    if policy in {"ml", "complexity_aware_ml_a3"}
                    else {"total_handovers": index, "skipped_handovers": 10 + index}
                )
                for index, policy in enumerate(policies, start=1)
            },
        },
    )
    write_json(
        root / "live_experiment_plan.json",
        [
            {
                "policy": policy,
                "scenario": "highway",
                "seed": 42,
                "duration_minutes": 1,
                "requires_ml_service": policy in {"ml", "complexity_aware_ml_a3"},
            }
            for policy in policies
        ],
    )
    for policy in policies:
        write_topology(root, policy)
        log_path = root / "logs" / f"{policy}_docker.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("service started\n", encoding="utf-8")
    return root


def test_valid_offline_output_passes(tmp_path):
    run_dir = write_valid_offline_output(tmp_path / "offline")

    report = validate_comparison_output(
        run_dir,
        expected_policies=["fixed_a3_baseline", "ml_policy"],
    )

    assert report.ok is True
    assert report.artifact_type == "offline_replay"
    assert report.issues == []


def test_offline_output_missing_decisions_fails(tmp_path):
    run_dir = write_valid_offline_output(tmp_path / "offline")
    (run_dir / "decisions" / "fixed_a3_baseline.jsonl").unlink()

    report = validate_comparison_output(run_dir)

    assert report.ok is False
    assert "missing_decision_log" in {issue.code for issue in report.issues}


def test_offline_output_rejects_fake_a3_confidence(tmp_path):
    run_dir = write_valid_offline_output(tmp_path / "offline")
    write_decision_log(
        run_dir,
        "fixed_a3_baseline",
        [decision("fixed_a3_baseline", confidence=0.9)],
    )

    report = validate_comparison_output(run_dir)

    assert report.ok is False
    assert "fake_a3_confidence" in {issue.code for issue in report.issues}


def test_offline_output_rejects_missing_neighbour_measurements(tmp_path):
    run_dir = write_valid_offline_output(tmp_path / "offline")
    write_decision_log(
        run_dir,
        "fixed_a3_baseline",
        [decision("fixed_a3_baseline", neighbours={})],
    )

    report = validate_comparison_output(run_dir)

    assert report.ok is False
    assert "missing_decision_measurements" in {issue.code for issue in report.issues}


def test_offline_output_rejects_ml_decision_without_qos_debug(tmp_path):
    run_dir = write_valid_offline_output(tmp_path / "offline")
    write_decision_log(
        run_dir,
        "ml_policy",
        [decision("ml_policy", confidence=0.9, debug={})],
    )

    report = validate_comparison_output(run_dir)

    assert report.ok is False
    assert "missing_ml_decision_debug" in {issue.code for issue in report.issues}


def test_offline_output_accepts_ranker_backed_ml_debug(tmp_path):
    run_dir = write_valid_offline_output(tmp_path / "offline")
    write_decision_log(
        run_dir,
        "ml_policy",
        [decision("ml_policy", debug=ranker_debug(), selected_target="cell-b")],
    )

    report = validate_comparison_output(
        run_dir,
        expected_policies=["fixed_a3_baseline", "ml_policy"],
    )

    assert report.ok is True


def test_offline_output_rejects_ranker_ml_missing_metadata(tmp_path):
    run_dir = write_valid_offline_output(tmp_path / "offline")
    debug = ranker_debug()
    debug["ranker_metadata"] = {"model_family": "candidate_ranker"}
    write_decision_log(
        run_dir,
        "ml_policy",
        [decision("ml_policy", debug=debug, selected_target="cell-b")],
    )

    report = validate_comparison_output(run_dir)

    assert report.ok is False
    assert "missing_ml_decision_debug" in {issue.code for issue in report.issues}


def test_offline_output_rejects_invalid_selected_target(tmp_path):
    run_dir = write_valid_offline_output(tmp_path / "offline")
    write_decision_log(
        run_dir,
        "ml_policy",
        [
            decision(
                "ml_policy",
                neighbours={"cell-b": -79.0},
                debug=ranker_debug(),
                selected_target="cell-c",
            )
        ],
    )

    report = validate_comparison_output(run_dir)

    assert report.ok is False
    assert "invalid_selected_target" in {issue.code for issue in report.issues}


def test_offline_output_rejects_pure_ml_with_hidden_fallback_metadata(tmp_path):
    run_dir = write_valid_offline_output(tmp_path / "offline")
    bad_debug = decision("ml_policy", confidence=0.9)["debug"]
    bad_debug["raw_ml_response_metadata"] = {
        "fallback_reason": "geographic_override",
        "geographic_override": True,
    }
    write_decision_log(
        run_dir,
        "ml_policy",
        [decision("ml_policy", confidence=0.9, debug=bad_debug)],
    )

    report = validate_comparison_output(run_dir)

    assert report.ok is False
    assert "hidden_ml_fallback" in {issue.code for issue in report.issues}


def test_offline_output_rejects_complexity_gate_high_bucket_to_a3(tmp_path):
    run_dir = tmp_path / "offline"
    run_dir.mkdir()
    write_json(
        run_dir / "summary.json",
        {
            "scenario": "highway",
            "seed": 42,
            "topology_hash": "topology-hash",
            "policy_results": {
                "complexity_aware_ml_a3": {
                    "summary": {"handover_count": 0, "composite_cost": 0.0},
                },
            },
        },
    )
    write_json(root := run_dir / "manifest.json", {"scenario": "highway"})
    assert root.is_file()
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
        "complexity_aware_ml_a3",
        [
            decision(
                "complexity_aware_ml_a3",
                debug={
                    "decision_source": "a3_complexity_gate",
                    "delegated_policy": "tuned_a3_baseline",
                    "candidate_complexity": {
                        "viable_candidate_count": 3,
                        "complexity_bucket": "high",
                        "viable_candidates": ["cell-b", "cell-c", "cell-d"],
                    },
                },
            )
        ],
    )

    report = validate_comparison_output(run_dir)

    assert report.ok is False
    assert "complexity_gate_bucket_mismatch" in {issue.code for issue in report.issues}


def test_offline_output_rejects_tuned_a3_without_artifact(tmp_path):
    run_dir = tmp_path / "offline"
    run_dir.mkdir()
    write_json(
        run_dir / "summary.json",
        {
            "scenario": "highway",
            "seed": 42,
            "topology_hash": "topology-hash",
            "policy_results": {
                "tuned_a3_baseline": {
                    "summary": {"handover_count": 0, "ping_pong_count": 0},
                },
            },
        },
    )
    write_json(run_dir / "manifest.json", {"scenario": "highway"})
    write_decision_log(run_dir, "tuned_a3_baseline", [decision("tuned_a3_baseline")])

    report = validate_comparison_output(run_dir)

    assert report.ok is False
    assert "missing_tuned_a3_artifact" in {issue.code for issue in report.issues}


def test_valid_live_output_passes(tmp_path):
    run_dir = write_valid_live_output(tmp_path / "live")

    report = validate_comparison_output(
        run_dir,
        expected_policies=["ml", "fixed_a3_baseline"],
    )

    assert report.ok is True
    assert report.artifact_type == "live_experiment"


def test_live_output_rejects_metric_collection_warnings(tmp_path):
    run_dir = write_valid_live_output(tmp_path / "live")
    summary_path = run_dir / "experiment_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["policy_metrics"]["ml"]["avg_confidence"] = None
    summary["policy_metric_warnings"] = {
        "ml": ["Prometheus query returned no series for avg_confidence"]
    }
    write_json(summary_path, summary)

    report = validate_comparison_output(run_dir)

    assert report.ok is False
    assert "metric_collection_warning" in {issue.code for issue in report.issues}


def test_live_output_rejects_partial_topology(tmp_path):
    run_dir = write_valid_live_output(tmp_path / "live")
    write_json(
        run_dir / "topology" / "ml_topology.json",
        {"metadata": {"name": "Highway"}, "cells": [], "ues": [], "paths": []},
    )

    report = validate_comparison_output(run_dir)

    assert report.ok is False
    assert "partial_topology" in {issue.code for issue in report.issues}


def test_live_output_rejects_unlabeled_ml_fallback(tmp_path):
    run_dir = write_valid_live_output(tmp_path / "live")
    (run_dir / "logs" / "ml_docker.log").write_text(
        '{"fallback_to_a3": true}\n',
        encoding="utf-8",
    )

    report = validate_comparison_output(run_dir)

    assert report.ok is False
    assert "unlabeled_ml_fallback" in {issue.code for issue in report.issues}


def test_live_output_rejects_ml_throttling_or_server_error_logs(tmp_path):
    run_dir = write_valid_live_output(tmp_path / "live")
    (run_dir / "logs" / "ml_docker.log").write_text(
        "ML service returned status 429 Too Many Requests\n",
        encoding="utf-8",
    )

    report = validate_comparison_output(run_dir)

    assert report.ok is False
    assert "ml_error_signature_in_logs" in {issue.code for issue in report.issues}


def test_live_output_allows_429_digits_inside_telemetry_values(tmp_path):
    run_dir = write_valid_live_output(tmp_path / "live")
    (run_dir / "logs" / "ml_docker.log").write_text(
        'HANDOVER_DECISION {"observed_qos": {"timestamp": 42539.79}}\n'
        '172.18.0.4 - - "POST /api/predict-with-qos HTTP/1.1" 200 2429\n',
        encoding="utf-8",
    )

    report = validate_comparison_output(run_dir)

    assert report.ok is True


def test_live_output_rejects_zero_ml_qos_compliance_checks(tmp_path):
    run_dir = write_valid_live_output(tmp_path / "live")
    summary_path = run_dir / "experiment_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["policy_metrics"]["ml"]["qos_compliance_ok"] = 0
    summary["policy_metrics"]["ml"]["qos_compliance_failed"] = 0
    write_json(summary_path, summary)

    report = validate_comparison_output(run_dir)

    assert report.ok is False
    assert "missing_ml_qos_compliance_counters" in {
        issue.code for issue in report.issues
    }


def test_live_output_rejects_missing_tuned_config(tmp_path):
    run_dir = write_valid_live_output(
        tmp_path / "live",
        policies=("tuned_a3_baseline",),
    )

    report = validate_comparison_output(run_dir)

    assert report.ok is False
    assert "missing_tuned_a3_config" in {issue.code for issue in report.issues}


def test_live_output_rejects_tuned_config_without_scores(tmp_path):
    config = tmp_path / "tuned_a3_config.json"
    write_json(
        config,
        {
            "selected_parameters": {
                "a3_offset_db": 0.0,
                "hysteresis_db": 2.0,
                "time_to_trigger_s": 1.0,
                "cooldown_s": 2.0,
            }
        },
    )
    run_dir = write_valid_live_output(
        tmp_path / "live",
        policies=("tuned_a3_baseline",),
    )
    write_json(
        run_dir / "live_experiment_plan.json",
        [
            {
                "policy": "tuned_a3_baseline",
                "scenario": "highway",
                "seed": 42,
                "duration_minutes": 1,
                "requires_ml_service": False,
                "tuned_a3_config": str(config),
            }
        ],
    )

    report = validate_comparison_output(run_dir)

    assert report.ok is False
    assert "missing_tuned_a3_scores" in {issue.code for issue in report.issues}


def test_valid_live_tuned_a3_output_passes_with_staged_config(tmp_path):
    run_dir = write_valid_live_output(
        tmp_path / "live",
        policies=("ml", "fixed_a3_baseline", "tuned_a3_baseline"),
    )
    config = run_dir / "config" / "tuned_a3_config.json"
    write_json(
        config,
        {
            "selected_parameters": {
                "a3_offset_db": -2.0,
                "hysteresis_db": 1.0,
                "time_to_trigger_s": 1.0,
                "cooldown_s": 5.0,
            },
            "evaluated_configuration_scores": [{"score": 497.0}],
            "calibration": {
                "scenario": "highway",
                "seed": 41,
                "topology_hash": "topology-hash",
            },
        },
    )
    write_json(
        run_dir / "live_experiment_plan.json",
        [
            {
                "policy": "ml",
                "scenario": "highway",
                "seed": 42,
                "duration_minutes": 1,
                "requires_ml_service": True,
            },
            {
                "policy": "fixed_a3_baseline",
                "scenario": "highway",
                "seed": 42,
                "duration_minutes": 1,
                "requires_ml_service": False,
            },
            {
                "policy": "tuned_a3_baseline",
                "scenario": "highway",
                "seed": 42,
                "duration_minutes": 1,
                "requires_ml_service": False,
                "tuned_a3_config": str(config),
            },
        ],
    )

    report = validate_comparison_output(
        run_dir,
        expected_policies=["ml", "fixed_a3_baseline", "tuned_a3_baseline"],
    )

    assert report.ok is True


def test_valid_live_complexity_aware_output_passes_with_staged_config(tmp_path):
    run_dir = write_valid_live_output(
        tmp_path / "live",
        policies=("complexity_aware_ml_a3",),
    )
    config = run_dir / "config" / "tuned_a3_config.json"
    write_json(
        config,
        {
            "selected_parameters": {
                "a3_offset_db": -2.0,
                "hysteresis_db": 1.0,
                "time_to_trigger_s": 1.0,
                "cooldown_s": 5.0,
            },
            "evaluated_configuration_scores": [{"score": 497.0}],
            "calibration": {
                "scenario": "highway",
                "seed": 41,
                "topology_hash": "topology-hash",
            },
        },
    )
    write_json(
        run_dir / "live_experiment_plan.json",
        [
            {
                "policy": "complexity_aware_ml_a3",
                "scenario": "highway",
                "seed": 42,
                "duration_minutes": 1,
                "requires_ml_service": True,
                "tuned_a3_config": str(config),
            },
        ],
    )

    report = validate_comparison_output(run_dir)

    assert report.ok is True


def test_live_output_rejects_invalid_policy(tmp_path):
    run_dir = write_valid_live_output(tmp_path / "live", policies=("made_up_policy",))

    report = validate_comparison_output(run_dir)

    assert report.ok is False
    assert "invalid_policy" in {issue.code for issue in report.issues}


def test_validation_cli_writes_report_and_sets_exit_code(tmp_path):
    valid_dir = write_valid_offline_output(tmp_path / "offline")
    report_path = tmp_path / "validation.json"

    ok_exit = validate_main(
        [
            "--path",
            str(valid_dir),
            "--expected-policies",
            "fixed_a3_baseline,ml_policy",
            "--report-json",
            str(report_path),
        ]
    )
    bad_exit = validate_main(["--path", str(tmp_path / "missing")])

    assert ok_exit == 0
    assert report_path.is_file()
    assert bad_exit == 1
