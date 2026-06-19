import json
from types import SimpleNamespace

from scripts.policy_comparison.segment_controller_artifact import (
    load_segment_controller_artifact,
)
from scripts.policy_comparison.train_segment_controller_artifact import (
    grouped_split,
    train_segment_controller_artifact,
)


def segment_rows():
    rows = []
    for index in range(24):
        positive = int(index % 2 == 0)
        base = {
            "scenario": "highway_dense",
            "seed": 51,
            "topology_hash": "topology",
            "ue_id": f"ue-{index % 4}",
            "step_index": index,
            "timestamp_s": float(index),
            "serving_cell": "A",
            "candidate_count": 3,
            "complexity_bucket": "high",
            "feature_value": float(index),
            "speed_mps": 20.0,
            "serving_rsrp_dbm": -90.0,
            "snapshot_group": f"highway_dense:51:ue-{index % 4}:{index}",
        }
        rows.append(
            {
                **base,
                "row_type": "entry",
                "segment_group": f"{base['snapshot_group']}:entry",
                "best_candidate": "B",
                "best_candidate_margin": 20.0 if positive else -5.0,
                "enter_ml_segment": positive,
            }
        )
        for candidate, offset in (("B", 3.0), ("C", 2.0), ("D", 1.0)):
            rows.append(
                {
                    **base,
                    "row_type": "candidate",
                    "segment_group": f"{base['snapshot_group']}:candidate",
                    "candidate_cell": candidate,
                    "delta_rsrp_db": offset,
                    "segment_utility_margin_vs_stay": (
                        float(index + offset) if positive else float(-index - offset)
                    ),
                    "selected_label": int(positive and candidate == "B"),
                }
            )
        rows.append(
            {
                **base,
                "row_type": "exit",
                "segment_group": f"{base['snapshot_group']}:segment",
                "candidate_cell": "B",
                "segment_age_s": float(index % 6),
                "best_non_segment_margin_db": float(index % 5),
                "exit_segment_to_a3": int(index % 3 == 0),
            }
        )
    return rows


def test_train_segment_controller_artifact_writes_metadata(tmp_path):
    dataset = tmp_path / "segment.jsonl"
    manifest = tmp_path / "segment.manifest.json"
    artifact = tmp_path / "segment_controller.joblib"
    dataset.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in segment_rows()),
        encoding="utf-8",
    )
    manifest.write_text(
        json.dumps(
            {
                "label_policy": {"version": "segment_policy_v1"},
                "trace_hashes": {"trace.jsonl": "abc"},
                "topology_hash": "topology",
                "high_complexity_snapshot_count": 24,
                "high_complexity_candidate_row_count": 72,
                "segment_entry_label_distribution": {"0": 12, "1": 12},
                "segment_exit_label_distribution": {"0": 16, "1": 8},
            }
        ),
        encoding="utf-8",
    )

    report = train_segment_controller_artifact(
        SimpleNamespace(
            dataset=str(dataset),
            dataset_manifest=str(manifest),
            output_artifact=str(artifact),
            forbid_evaluation_seed="61,62,63,64,65",
            validation_split=0.25,
            seed=7,
            n_estimators=5,
            learning_rate=0.1,
            max_depth=-1,
            num_leaves=7,
            min_child_samples=1,
            min_target_std=0.0,
            min_prediction_std=-1.0,
            max_target_selection_error=1.0,
            min_entry_precision=0.0,
            min_exit_precision=0.0,
            min_high_complexity_candidate_rows=1,
            min_high_complexity_snapshot_groups=1,
            default_entry_threshold=0.5,
            default_candidate_margin_min=20.0,
            default_exit_threshold=0.7,
            default_consecutive_exit_votes=3,
            default_min_segment_duration_s=6.0,
            default_max_segment_duration_s=45.0,
            default_emergency_rsrp_floor_dbm=-112.0,
            overwrite=False,
        )
    )

    assert artifact.exists()
    loaded = load_segment_controller_artifact(artifact)
    assert loaded.model_family == "segment_controller"
    assert loaded.decision_parameters["candidate_margin_min"] == 20.0
    assert report["metadata"]["model_type"] == "segment_controller_lightgbm_v1"
    assert "ue_id" not in loaded.candidate_feature_columns
    assert "serving_cell" not in loaded.candidate_feature_columns
    assert "candidate_cell" not in loaded.candidate_feature_columns


def test_exit_grouped_split_keeps_one_simulated_segment_together():
    rows = []
    for segment_index in range(6):
        segment_group = f"highway_dense:51:ue-1:{segment_index}:segment"
        for future_step in range(4):
            rows.append(
                {
                    "row_type": "exit",
                    "scenario": "highway_dense",
                    "seed": 51,
                    "ue_id": "ue-1",
                    "step_index": segment_index * 10 + future_step,
                    "snapshot_group": (
                        f"highway_dense:51:ue-1:{segment_index * 10 + future_step}"
                    ),
                    "segment_group": segment_group,
                }
            )

    train_indices, validation_indices, split = grouped_split(
        rows,
        validation_split=0.5,
        seed=13,
    )

    train_groups = {rows[index]["segment_group"] for index in train_indices}
    validation_groups = {rows[index]["segment_group"] for index in validation_indices}
    assert train_groups.isdisjoint(validation_groups)
    assert split["grouping"] == "segment_group"
