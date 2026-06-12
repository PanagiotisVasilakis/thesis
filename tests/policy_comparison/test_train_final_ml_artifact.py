import json
from types import SimpleNamespace

import pytest

from scripts.policy_comparison.nef_trace import feature_vector_to_trace_record
from scripts.policy_comparison.train_final_ml_artifact import (
    build_training_dataset,
    label_record,
    validate_seed_split,
    write_final_metadata,
    sha256_file,
)


def make_record(seed=41, serving="cell-a", cell_b_rsrp=-70.0):
    return feature_vector_to_trace_record(
        {
            "ue_id": "ue-1",
            "latitude": 10.0,
            "longitude": 20.0,
            "speed": 25.0,
            "connected_to": serving,
            "neighbor_rsrp_dbm": {"cell-a": -80.0, "cell-b": cell_b_rsrp},
            "neighbor_sinrs": {"cell-a": 5.0, "cell-b": 10.0},
            "neighbor_rsrqs": {"cell-a": -9.0, "cell-b": -7.0},
            "neighbor_cell_loads": {"cell-a": 0.0, "cell-b": 0.0},
        },
        scenario="highway",
        seed=seed,
        step_index=0,
        timestamp_s=0.0,
    )


def test_label_record_prefers_better_rf_cell():
    selected, scores, margin, rank = label_record(
        make_record(),
        stay_margin_db=2.0,
        load_penalty_db=4.0,
        sinr_weight=0.2,
        rsrq_weight=0.1,
    )

    assert selected == "cell-b"
    assert scores["cell-b"] > scores["cell-a"]
    assert margin > 0
    assert rank == 2.0


def test_label_record_keeps_serving_cell_inside_stay_margin():
    selected, _, _, _ = label_record(
        make_record(cell_b_rsrp=-79.5),
        stay_margin_db=2.0,
        load_penalty_db=4.0,
        sinr_weight=0.0,
        rsrq_weight=0.0,
    )

    assert selected == "cell-a"


def test_build_training_dataset_preserves_ml_payload_context():
    sample, counts, max_neighbors = build_training_dataset(
        [make_record()],
        stay_margin_db=2.0,
        load_penalty_db=4.0,
        sinr_weight=0.2,
        rsrq_weight=0.1,
    )

    assert sample[0]["optimal_antenna"] == "cell-b"
    assert sample[0]["rf_metrics"]["cell-b"]["cell_load"] == 0.0
    assert sample[0]["antenna_selection_scores"]["cell-b"] > sample[0]["antenna_selection_scores"]["cell-a"]
    assert counts == {"cell-b": 1}
    assert max_neighbors == 1


def test_validate_seed_split_rejects_evaluation_seed_overlap():
    with pytest.raises(ValueError, match="overlap"):
        validate_seed_split([make_record(seed=42)], [42, 43, 44])


def test_write_final_metadata_records_required_manifest_fields(tmp_path):
    model_path = tmp_path / "antenna_selector_final.joblib"
    feature_config = tmp_path / "features.yaml"
    trace = tmp_path / "trace.jsonl"
    model_path.write_bytes(b"model")
    (tmp_path / "antenna_selector_final.joblib.scaler").write_bytes(b"scaler")
    (tmp_path / "antenna_selector_final.joblib.meta.json").write_text(
        json.dumps(
            {
                "model_type": "lightgbm",
                "trained_at": "2026-06-11T00:00:00+00:00",
                "version": "1.0.0",
            }
        ),
        encoding="utf-8",
    )
    feature_config.write_text("base_features: []\n", encoding="utf-8")
    trace.write_text("{}\n", encoding="utf-8")

    metadata = write_final_metadata(
        model_path=model_path,
        feature_config=feature_config,
        trace_paths=[trace],
        records=[make_record(seed=41)],
        selector=SimpleNamespace(feature_names=["latitude", "rsrp_current"]),
        training_metrics={"val_accuracy": 1.0, "confidence_calibrated": False},
        sanity_report={"unique_predictions": 1},
        label_counts={"cell-b": 1},
        label_policy={"name": "unit-test"},
    )

    assert metadata["training_data_source"]["mode"] == "policy_free_calibration_trace"
    assert metadata["scenario_seeds"] == [41]
    assert metadata["dataset_size"] == 1
    assert metadata["selected_features"] == ["latitude", "rsrp_current"]
    assert metadata["feature_config_sha256"] == sha256_file(feature_config)
    assert metadata["scaler_sha256"] == sha256_file(
        tmp_path / "antenna_selector_final.joblib.scaler"
    )
