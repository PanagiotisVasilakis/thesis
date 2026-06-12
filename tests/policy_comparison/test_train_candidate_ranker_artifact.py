import json
from types import SimpleNamespace

import pytest

from scripts.policy_comparison.candidate_ranker_artifact import (
    NON_FEATURE_COLUMNS,
    load_candidate_ranker_artifact,
)
from scripts.policy_comparison.train_candidate_ranker_artifact import (
    train_ranker_artifact,
)


def make_row(group, candidate, *, seed=41, margin=3.0, selected=False):
    return {
        "scenario": "highway",
        "seed": seed,
        "topology_hash": "topology",
        "ue_id": "ue-1",
        "step_index": group,
        "timestamp_s": float(group),
        "serving_cell": "cell-a",
        "candidate_cell": candidate,
        "candidate_count": 2,
        "complexity_bucket": "moderate",
        "rsrp_dbm": -80.0 + margin,
        "serving_rsrp_dbm": -85.0,
        "delta_rsrp_db": margin,
        "sinr_db": 10.0,
        "serving_sinr_db": 7.0,
        "delta_sinr_db": 3.0,
        "rsrq_db": -8.0,
        "serving_rsrq_db": -10.0,
        "delta_rsrq_db": 2.0,
        "candidate_load": 0.2,
        "serving_load": 0.1,
        "delta_load": 0.1,
        "speed_mps": 20.0,
        "signal_trend": 0.2,
        "distance_to_candidate_m": 100.0,
        "moving_toward_candidate": 1.0,
        "recent_handover_count": 0,
        "time_since_last_handover_s": 30.0,
        "service_priority": 5,
        "latency_ms": 10.0,
        "throughput_mbps": 100.0,
        "packet_loss_rate": 0.0,
        "candidate_sequence_score": -70.0 + margin,
        "serving_sequence_score": -80.0,
        "stay_sequence_score": -80.0,
        "utility_margin_vs_serving": margin,
        "utility_margin_vs_stay": margin,
        "handover_action_penalty": 1.0,
        "same_site_penalty": 0.0,
        "rf_regression_penalty": 0.0,
        "short_dwell_penalty": 0.0,
        "ping_pong_risk_penalty": 0.0,
        "total_decision_penalty": 1.0,
        "rank_label": 1 if selected else 2,
        "selected_label": 1 if selected else 0,
        "selected_label_tie_count": 1 if selected else 0,
        "handover_desirable": selected,
    }


def write_dataset(path, rows):
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    manifest = {
        "scenario_seeds": sorted({row["seed"] for row in rows}),
        "trace_hashes": {"trace.jsonl": "abc"},
        "trace_complexity_summaries": [
            {
                "trace": "trace.jsonl",
                "record_count": len(rows),
                "candidate_count_histogram": {"2": len(rows)},
                "thresholds": {"3": {"high": 0, "high_fraction": 0.0}},
            }
        ],
    }
    path.with_suffix(path.suffix + ".manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )


def train_args(dataset, artifact, **overrides):
    values = {
        "dataset": str(dataset),
        "output_artifact": str(artifact),
        "dataset_manifest": None,
        "forbid_evaluation_seed": "42,43,44",
        "seed": 41,
        "validation_split": 0.5,
        "n_estimators": 10,
        "learning_rate": 0.1,
        "max_depth": -1,
        "num_leaves": 7,
        "min_child_samples": 1,
        "default_threshold": 2.0,
        "min_target_std": 1e-9,
        "min_prediction_std": 1e-9,
        "min_high_complexity_rows": 0,
        "min_high_complexity_groups": 0,
        "max_target_selection_error": 1.0,
        "min_handover_precision": 0.0,
        "overwrite": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_train_candidate_ranker_artifact_writes_complete_metadata(tmp_path):
    dataset = tmp_path / "ranker.jsonl"
    artifact = tmp_path / "ranker.joblib"
    rows = []
    for group in range(4):
        rows.append(make_row(group, "cell-b", margin=3.0 + group, selected=True))
        rows.append(make_row(group, "cell-c", margin=-1.0 - group, selected=False))
    write_dataset(dataset, rows)

    report = train_ranker_artifact(train_args(dataset, artifact))

    metadata = json.loads((tmp_path / "ranker.joblib.meta.json").read_text())
    loaded = load_candidate_ranker_artifact(artifact)
    assert report["metadata"]["model_type"] == "candidate_ranker_lightgbm_regressor"
    assert metadata["target"] == "utility_margin_vs_stay"
    assert metadata["decision_objective"] == "stay_aware_candidate_margin"
    assert metadata["ranker_decision_parameters"]["selected_min_margin"] >= 5.0
    assert metadata["model_sha256"] == loaded.artifact_sha256
    assert metadata["threshold_tuning_result"]["selected_threshold"] is not None
    assert metadata["seed_split"]["validation_group_count"] >= 1
    assert metadata["trace_complexity_summaries"]
    assert not set(metadata["selected_features"]).intersection(NON_FEATURE_COLUMNS)


def test_train_candidate_ranker_rejects_evaluation_seed_leakage(tmp_path):
    dataset = tmp_path / "ranker.jsonl"
    artifact = tmp_path / "ranker.joblib"
    rows = [
        make_row(0, "cell-b", seed=42, margin=3.0, selected=True),
        make_row(1, "cell-b", seed=42, margin=4.0, selected=True),
    ]
    write_dataset(dataset, rows)

    with pytest.raises(ValueError, match="overlap"):
        train_ranker_artifact(train_args(dataset, artifact, forbid_evaluation_seed="42"))


def test_train_candidate_ranker_rejects_constant_target(tmp_path):
    dataset = tmp_path / "ranker.jsonl"
    artifact = tmp_path / "ranker.joblib"
    rows = [
        make_row(0, "cell-b", margin=1.0, selected=False),
        make_row(1, "cell-b", margin=1.0, selected=False),
    ]
    write_dataset(dataset, rows)

    with pytest.raises(ValueError, match="constant"):
        train_ranker_artifact(train_args(dataset, artifact))


def test_train_candidate_ranker_rejects_missing_high_complexity_rows(tmp_path):
    dataset = tmp_path / "ranker.jsonl"
    artifact = tmp_path / "ranker.joblib"
    rows = [
        make_row(0, "cell-b", margin=3.0, selected=True),
        make_row(1, "cell-b", margin=4.0, selected=True),
    ]
    write_dataset(dataset, rows)

    with pytest.raises(ValueError, match="insufficient high-complexity"):
        train_ranker_artifact(
            train_args(dataset, artifact, min_high_complexity_rows=1)
        )
