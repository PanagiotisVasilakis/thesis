import json

import joblib
from sklearn.linear_model import LinearRegression

from scripts.policy_comparison.calibrate_tuned_a3 import calibrate_tuned_a3_config
from scripts.policy_comparison.candidate_ranker_artifact import sha256_file
from scripts.policy_comparison.nef_trace import feature_vector_to_trace_record
from scripts.policy_comparison import run_offline_replay as replay_cli
from scripts.policy_comparison.run_offline_replay import main
from scripts.policy_comparison.trace_io import write_trace_jsonl


def make_record(seed, step, rsrp_b=-78.0):
    return feature_vector_to_trace_record(
        {
            "ue_id": "ue-1",
            "latitude": 37.1,
            "longitude": 23.2,
            "connected_to": "cell-a",
            "neighbor_rsrp_dbm": {"cell-a": -84.0, "cell-b": rsrp_b},
        },
        scenario="highway",
        seed=seed,
        step_index=step,
        timestamp_s=float(step),
        topology_hash="topology",
    )


def write_trace(path, seed):
    records = [make_record(seed, 0), make_record(seed, 1)]
    write_trace_jsonl(records, path)
    return records


def test_offline_replay_cli_writes_summary_manifest_and_decisions(tmp_path):
    trace_path = tmp_path / "eval.jsonl"
    output_dir = tmp_path / "out"
    write_trace(trace_path, seed=10)

    code = main(
        [
            "--trace",
            str(trace_path),
            "--output-dir",
            str(output_dir),
            "--policies",
            "fixed_a3_baseline",
        ]
    )

    assert code == 0
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["scenario"] == "highway"
    assert "fixed_a3_baseline" in summary["policy_results"]
    assert (output_dir / "manifest.json").exists()
    assert (output_dir / "decisions" / "fixed_a3_baseline.jsonl").exists()


def test_offline_replay_cli_rejects_nonempty_output_dir(tmp_path):
    trace_path = tmp_path / "eval.jsonl"
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    (output_dir / "old.json").write_text("{}", encoding="utf-8")
    write_trace(trace_path, seed=10)

    code = main(
        [
            "--trace",
            str(trace_path),
            "--output-dir",
            str(output_dir),
            "--policies",
            "fixed_a3_baseline",
        ]
    )

    assert code == 1


def test_offline_replay_cli_requires_tuned_calibration_trace(tmp_path):
    trace_path = tmp_path / "eval.jsonl"
    output_dir = tmp_path / "out"
    write_trace(trace_path, seed=10)

    code = main(
        [
            "--trace",
            str(trace_path),
            "--output-dir",
            str(output_dir),
            "--policies",
            "tuned_a3_baseline",
        ]
    )

    assert code == 1
    assert not output_dir.exists()


def test_offline_replay_cli_rejects_same_seed_calibration_trace(tmp_path):
    eval_path = tmp_path / "eval.jsonl"
    calibration_path = tmp_path / "calibration.jsonl"
    output_dir = tmp_path / "out"
    write_trace(eval_path, seed=10)
    write_trace(calibration_path, seed=10)

    code = main(
        [
            "--trace",
            str(eval_path),
            "--calibration-trace",
            str(calibration_path),
            "--output-dir",
            str(output_dir),
            "--policies",
            "tuned_a3_baseline",
        ]
    )

    assert code == 1
    assert not output_dir.exists()


def test_offline_replay_cli_writes_real_tuned_result_for_separate_calibration(tmp_path):
    eval_path = tmp_path / "eval.jsonl"
    calibration_path = tmp_path / "calibration.jsonl"
    output_dir = tmp_path / "out"
    write_trace(eval_path, seed=10)
    write_trace(calibration_path, seed=9)

    code = main(
        [
            "--trace",
            str(eval_path),
            "--calibration-trace",
            str(calibration_path),
            "--output-dir",
            str(output_dir),
            "--policies",
            "tuned_a3_baseline",
        ]
    )

    assert code == 0
    tuning = json.loads(
        (output_dir / "tuned_a3_tuning_result.json").read_text(encoding="utf-8")
    )
    assert "selected_parameters" in tuning
    assert tuning["evaluated_configurations"]


def test_offline_replay_cli_uses_generated_tuned_config(tmp_path):
    eval_path = tmp_path / "eval.jsonl"
    calibration_path = tmp_path / "calibration.jsonl"
    config_path = tmp_path / "tuned_a3_config.json"
    output_dir = tmp_path / "out"
    write_trace(eval_path, seed=10)
    write_trace(calibration_path, seed=9)
    calibrate_tuned_a3_config(calibration_path, config_path)

    code = main(
        [
            "--trace",
            str(eval_path),
            "--tuned-a3-config",
            str(config_path),
            "--output-dir",
            str(output_dir),
            "--policies",
            "tuned_a3_baseline",
        ]
    )

    assert code == 0
    assert (output_dir / "tuned_a3_config.json").exists()
    assert not (output_dir / "tuned_a3_tuning_result.json").exists()
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["notes"]["tuned_a3_config"] == str(config_path)


def test_offline_replay_cli_rejects_tuned_config_seed_overlap(tmp_path):
    eval_path = tmp_path / "eval.jsonl"
    calibration_path = tmp_path / "calibration.jsonl"
    config_path = tmp_path / "tuned_a3_config.json"
    output_dir = tmp_path / "out"
    write_trace(eval_path, seed=10)
    write_trace(calibration_path, seed=10)
    calibrate_tuned_a3_config(calibration_path, config_path)

    code = main(
        [
            "--trace",
            str(eval_path),
            "--tuned-a3-config",
            str(config_path),
            "--output-dir",
            str(output_dir),
            "--policies",
            "tuned_a3_baseline",
        ]
    )

    assert code == 1
    assert not output_dir.exists()


def test_offline_replay_cli_rejects_both_tuned_config_and_calibration_trace(tmp_path):
    eval_path = tmp_path / "eval.jsonl"
    calibration_path = tmp_path / "calibration.jsonl"
    config_path = tmp_path / "tuned_a3_config.json"
    output_dir = tmp_path / "out"
    write_trace(eval_path, seed=10)
    write_trace(calibration_path, seed=9)
    calibrate_tuned_a3_config(calibration_path, config_path)

    code = main(
        [
            "--trace",
            str(eval_path),
            "--calibration-trace",
            str(calibration_path),
            "--tuned-a3-config",
            str(config_path),
            "--output-dir",
            str(output_dir),
            "--policies",
            "tuned_a3_baseline",
        ]
    )

    assert code == 1
    assert not output_dir.exists()


def test_offline_replay_cli_requires_ready_ml_model_health(tmp_path, monkeypatch):
    trace_path = tmp_path / "eval.jsonl"
    output_dir = tmp_path / "out"
    write_trace(trace_path, seed=10)

    class Response:
        status_code = 200

        def json(self):
            return {"ready": False}

    monkeypatch.setattr(replay_cli.requests, "get", lambda *args, **kwargs: Response())

    code = main(
        [
            "--trace",
            str(trace_path),
            "--output-dir",
            str(output_dir),
            "--policies",
            "ml",
            "--ml-base-url",
            "http://ml.local",
        ]
    )

    assert code == 1
    assert not output_dir.exists()


def test_fetch_ml_model_health_strips_secret_like_fields(monkeypatch):
    class Response:
        status_code = 200

        def json(self):
            return {
                "ready": True,
                "model_version": "test",
                "access_token": "do-not-record",
                "password_hint": "do-not-record",
            }

    monkeypatch.setattr(replay_cli.requests, "get", lambda *args, **kwargs: Response())

    health = replay_cli.fetch_ml_model_health("http://ml.local")

    assert health == {"ready": True, "model_version": "test"}


def write_linear_ranker_artifact(path):
    model = LinearRegression()
    model.fit([[1.0], [5.0]], [1.0, 5.0])
    metadata = {
        "model_type": "candidate_ranker_lightgbm_regressor",
        "model_family": "candidate_ranker",
        "target": "utility_margin_vs_stay",
        "selected_features": ["delta_rsrp_db"],
        "validation_metrics": {"validation_rmse": 0.0},
        "threshold_tuning_result": {"selected_threshold": 0.0},
        "ranker_decision_parameters": {
            "selected_min_margin": 0.0,
            "min_ml_dwell_s": 10.0,
            "a3_reentry_extra_margin_db": 3.0,
        },
        "seed_split": {"validation_group_count": 1},
        "dataset_size": 2,
        "scenario_seeds": [9],
        "complexity_bucket_counts": {"high": 2},
        "high_complexity_row_count": 2,
        "min_high_complexity_rows": 1,
        "trace_complexity_summaries": [
            {
                "trace": "trace.jsonl",
                "record_count": 1,
                "thresholds": {"3": {"high": 1, "high_fraction": 1.0}},
            }
        ],
    }
    joblib.dump(
        {
            "model": model,
            "feature_columns": ["delta_rsrp_db"],
            "metadata": metadata,
        },
        path,
    )
    metadata["model_sha256"] = sha256_file(path)
    (path.parent / f"{path.name}.meta.json").write_text(
        json.dumps(metadata),
        encoding="utf-8",
    )


def test_offline_replay_cli_uses_candidate_ranker_backend(tmp_path, monkeypatch):
    trace_path = tmp_path / "eval.jsonl"
    output_dir = tmp_path / "out"
    artifact = tmp_path / "ranker.joblib"
    write_trace(trace_path, seed=10)
    write_linear_ranker_artifact(artifact)

    def fail_model_health(*args, **kwargs):
        raise AssertionError("candidate ranker replay must not call ML model health")

    monkeypatch.setattr(replay_cli.requests, "get", fail_model_health)

    code = main(
        [
            "--trace",
            str(trace_path),
            "--output-dir",
            str(output_dir),
            "--policies",
            "ml",
            "--ml-backend",
            "candidate_ranker",
            "--ranker-artifact",
            str(artifact),
        ]
    )

    assert code == 0
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert "ml_policy" in summary["policy_results"]
    decision_log = (output_dir / "decisions" / "ml_policy.jsonl").read_text(
        encoding="utf-8"
    )
    assert '"ml_backend": "candidate_ranker"' in decision_log
