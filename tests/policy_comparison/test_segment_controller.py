import json
from types import SimpleNamespace

import pytest

from scripts.policy_comparison.export_segment_policy_dataset import (
    export_segment_dataset,
)
from scripts.policy_comparison.nef_trace import feature_vector_to_trace_record
from scripts.policy_comparison.segment_controller import (
    build_segment_policy_dataset,
    select_segment_feature_columns,
)
from scripts.policy_comparison.trace_io import write_trace_jsonl


def make_record(
    *,
    ue_id="ue-1",
    seed=51,
    step=0,
    serving="A",
    a=-100.0,
    b=-70.0,
    c=-72.0,
    d=-74.0,
):
    return feature_vector_to_trace_record(
        {
            "ue_id": ue_id,
            "latitude": 10.0,
            "longitude": 20.0,
            "speed": 25.0,
            "connected_to": serving,
            "neighbor_rsrp_dbm": {
                "A": a,
                "B": b,
                "C": c,
                "D": d,
            },
            "neighbor_sinrs": {
                "A": 5.0,
                "B": 8.0,
                "C": 8.0,
                "D": 8.0,
            },
        },
        scenario="highway_dense",
        seed=seed,
        step_index=step,
        timestamp_s=float(step),
        topology_hash="topology",
    )


def segment_records(seed=51):
    positive = [
        make_record(seed=seed, step=0, a=-100.0, b=-70.0, c=-72.0, d=-74.0),
        make_record(seed=seed, step=1, a=-100.0, b=-70.0, c=-72.0, d=-74.0),
        make_record(seed=seed, step=2, a=-100.0, b=-70.0, c=-72.0, d=-74.0),
        make_record(seed=seed, step=3, a=-100.0, b=-83.0, c=-60.0, d=-74.0),
        make_record(seed=seed, step=4, a=-100.0, b=-84.0, c=-59.0, d=-74.0),
    ]
    negative = [
        make_record(
            ue_id="ue-2",
            seed=seed,
            step=0,
            a=-80.0,
            b=-79.5,
            c=-79.0,
            d=-78.8,
        ),
        make_record(
            ue_id="ue-2",
            seed=seed,
            step=1,
            a=-80.0,
            b=-79.5,
            c=-79.0,
            d=-78.8,
        ),
    ]
    return positive + negative


def test_segment_dataset_has_entry_candidate_and_exit_labels():
    dataset = build_segment_policy_dataset(
        segment_records(),
        segment_horizon_steps=3,
        min_segment_duration_s=2.0,
        max_segment_duration_s=5.0,
        stay_margin=2.0,
        handover_action_penalty=0.0,
        load_penalty=0.0,
        sinr_weight=0.0,
        rsrq_weight=0.0,
    )

    assert dataset.candidate_rows
    assert dataset.entry_rows
    assert dataset.exit_rows
    assert {row["enter_ml_segment"] for row in dataset.entry_rows} == {0, 1}
    assert {row["exit_segment_to_a3"] for row in dataset.exit_rows} == {0, 1}
    assert dataset.metadata["label_policy_version"] == "segment_policy_v1"
    candidate_features = select_segment_feature_columns(
        dataset.rows,
        row_type="candidate",
    )
    assert "ue_id" not in candidate_features
    assert "serving_cell" not in candidate_features
    assert "candidate_cell" not in candidate_features
    assert "selected_label" not in candidate_features
    entry_features = select_segment_feature_columns(dataset.rows, row_type="entry")
    assert "best_candidate_margin" not in entry_features
    assert "best_candidate_score" not in entry_features
    assert "stay_score" not in entry_features
    assert "future_a3_recovery_trigger_count" not in candidate_features
    assert "future_sparse_a3_trigger_count" not in candidate_features
    assert "future_a3_reverse_churn_risk_count" not in entry_features


def test_export_segment_dataset_writes_manifest(tmp_path):
    trace = tmp_path / "trace.jsonl"
    output = tmp_path / "segment.jsonl"
    manifest = tmp_path / "segment.manifest.json"
    write_trace_jsonl(segment_records(), trace)

    result = export_segment_dataset(
        SimpleNamespace(
            trace=[str(trace)],
            output=str(output),
            manifest=str(manifest),
            forbid_evaluation_seed="61,62,63,64,65",
            segment_horizon_steps=3,
            min_segment_duration_s=2.0,
            max_segment_duration_s=5.0,
            stay_margin=2.0,
            handover_action_penalty=0.0,
            ping_pong_penalty=8.0,
            sparse_reentry_penalty=8.0,
            weak_serving_rsrp_dbm=-105.0,
            invalid_target_penalty=30.0,
            missing_future_cell_score=-160.0,
            load_penalty=0.0,
            sinr_weight=0.0,
            rsrq_weight=0.0,
            qos_violation_penalty=10.0,
            a3_recovery_margin_db=3.0,
            post_segment_churn_penalty=8.0,
            high_reject_recovery_risk_penalty=6.0,
            min_high_complexity_candidate_rows=1,
            min_high_complexity_snapshot_groups=1,
            overwrite=False,
        )
    )

    assert output.exists()
    loaded = json.loads(manifest.read_text(encoding="utf-8"))
    assert result["dataset_type"] == "segment_policy_jsonl"
    assert loaded["label_policy"]["version"] == "segment_policy_v1"
    assert loaded["feature_columns"]["candidate"]
    assert "future_a3_recovery_trigger_count" not in loaded["feature_columns"]["candidate"]
    assert loaded["label_policy"]["churn_feature_policy"]["a3_recovery_margin_db"] == 3.0
    assert loaded["calibration_seeds"] == [51]
    assert loaded["forbidden_evaluation_seeds"] == [61, 62, 63, 64, 65]


def test_export_segment_dataset_rejects_evaluation_seed_leakage(tmp_path):
    trace = tmp_path / "trace.jsonl"
    write_trace_jsonl(segment_records(seed=61), trace)

    with pytest.raises(ValueError, match="overlap"):
        export_segment_dataset(
            SimpleNamespace(
                trace=[str(trace)],
                output=str(tmp_path / "segment.jsonl"),
                manifest=None,
                forbid_evaluation_seed="61",
                segment_horizon_steps=3,
                min_segment_duration_s=2.0,
                max_segment_duration_s=5.0,
                stay_margin=2.0,
                handover_action_penalty=0.0,
                ping_pong_penalty=8.0,
                sparse_reentry_penalty=8.0,
                weak_serving_rsrp_dbm=-105.0,
                invalid_target_penalty=30.0,
                missing_future_cell_score=-160.0,
                load_penalty=0.0,
                sinr_weight=0.0,
                rsrq_weight=0.0,
                qos_violation_penalty=10.0,
                a3_recovery_margin_db=3.0,
                post_segment_churn_penalty=8.0,
                high_reject_recovery_risk_penalty=6.0,
                min_high_complexity_candidate_rows=1,
                min_high_complexity_snapshot_groups=1,
                overwrite=False,
            )
        )
