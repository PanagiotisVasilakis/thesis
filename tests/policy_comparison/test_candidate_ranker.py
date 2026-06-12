import json
from types import SimpleNamespace

import pytest

from scripts.policy_comparison.candidate_ranker import (
    build_candidate_ranker_dataset,
    build_candidate_ranker_features,
    build_labeled_candidate_ranker_dataset,
)
from scripts.policy_comparison.export_candidate_ranker_dataset import export_ranker_dataset
from scripts.policy_comparison.nef_trace import feature_vector_to_trace_record
from scripts.policy_comparison.trace_io import write_trace_jsonl


def test_candidate_ranker_features_include_rf_deltas_complexity_and_qos():
    record = feature_vector_to_trace_record(
        {
            "ue_id": "ue-1",
            "latitude": 10.0,
            "longitude": 20.0,
            "speed": 12.0,
            "connected_to": "cell-a",
            "neighbor_rsrp_dbm": {
                "cell-a": -84.0,
                "cell-b": -78.0,
                "cell-c": -76.0,
                "cell-d": -118.0,
            },
            "neighbor_sinrs": {
                "cell-a": 5.0,
                "cell-b": 9.0,
                "cell-c": 11.0,
                "cell-d": 12.0,
            },
            "neighbor_rsrqs": {
                "cell-a": -10.0,
                "cell-b": -8.0,
                "cell-c": -7.0,
                "cell-d": -6.0,
            },
            "neighbor_cell_loads": {
                "cell-a": 0.2,
                "cell-b": 0.6,
                "cell-c": 0.1,
                "cell-d": 0.1,
            },
            "cell_distances_m": {"cell-b": 120.0, "cell-c": 240.0},
            "moving_toward_cells": {"cell-b": 1.0, "cell-c": -0.5},
            "handover_count": 2,
            "time_since_handover": 15.0,
            "signal_trend": -0.3,
            "service_priority": 8,
            "observed_qos": {
                "latest": {
                    "latency_ms": 4.0,
                    "throughput_mbps": 80.0,
                    "packet_loss_rate": 0.1,
                }
            },
        },
        scenario="highway",
        seed=42,
        step_index=3,
        timestamp_s=7.5,
    )

    rows = build_candidate_ranker_features(record)

    assert [row["candidate_cell"] for row in rows] == ["cell-b", "cell-c"]
    first = rows[0]
    assert first["candidate_count"] == 2
    assert first["complexity_bucket"] == "moderate"
    assert first["delta_rsrp_db"] == 6.0
    assert first["delta_sinr_db"] == 4.0
    assert first["delta_rsrq_db"] == 2.0
    assert first["delta_load"] == 0.39999999999999997
    assert first["distance_to_candidate_m"] == 120.0
    assert first["moving_toward_candidate"] == 1.0
    assert first["recent_handover_count"] == 2
    assert first["time_since_last_handover_s"] == 15.0
    assert first["current_dwell_time_s"] == 0.0
    assert first["last_handover_source_ml"] == 0.0
    assert first["has_prior_handover"] == 1.0
    assert first["service_priority"] == 8
    assert first["latency_ms"] == 4.0


def test_candidate_ranker_dataset_flattens_records():
    record = feature_vector_to_trace_record(
        {
            "ue_id": "ue-1",
            "latitude": 10.0,
            "longitude": 20.0,
            "connected_to": "A",
            "neighbor_rsrp_dbm": {"A": -80.0, "B": -78.0},
        },
        scenario="highway",
        seed=42,
        step_index=0,
        timestamp_s=0.0,
    )

    rows = build_candidate_ranker_dataset([record, record])

    assert len(rows) == 2
    assert all(row["candidate_cell"] == "B" for row in rows)


def test_labeled_candidate_ranker_uses_sequence_window_not_greedy_signal():
    first = feature_vector_to_trace_record(
        {
            "ue_id": "ue-1",
            "latitude": 10.0,
            "longitude": 20.0,
            "connected_to": "A",
            "neighbor_rsrp_dbm": {"A": -90.0, "B": -70.0, "C": -74.0},
            "neighbor_sinrs": {"A": 5.0, "B": 5.0, "C": 5.0},
        },
        scenario="highway",
        seed=41,
        step_index=0,
        timestamp_s=0.0,
    )
    second = feature_vector_to_trace_record(
        {
            "ue_id": "ue-1",
            "latitude": 10.0,
            "longitude": 20.0,
            "connected_to": "A",
            "neighbor_rsrp_dbm": {"A": -90.0, "B": -120.0, "C": -73.0},
            "neighbor_sinrs": {"A": 5.0, "B": 5.0, "C": 5.0},
        },
        scenario="highway",
        seed=41,
        step_index=1,
        timestamp_s=1.0,
    )

    rows = build_labeled_candidate_ranker_dataset(
        [first, second],
        sequence_window_steps=2,
        stay_margin_db=2.0,
        handover_penalty_db=0.0,
        load_penalty_db=0.0,
        sinr_weight=0.0,
        rsrq_weight=0.0,
    )

    first_step_rows = {row["candidate_cell"]: row for row in rows if row["step_index"] == 0}
    assert first_step_rows["B"]["rank_label"] == 2
    assert first_step_rows["B"]["selected_label"] == 0
    assert first_step_rows["C"]["rank_label"] == 1
    assert first_step_rows["C"]["selected_label"] == 1
    assert first_step_rows["C"]["utility_margin_vs_stay"] > 2.0
    assert first_step_rows["C"]["stay_sequence_score"] == first_step_rows["C"]["serving_sequence_score"]
    assert "total_decision_penalty" in first_step_rows["C"]


def test_export_candidate_ranker_dataset_writes_manifest(tmp_path):
    trace_path = tmp_path / "trace.jsonl"
    output_path = tmp_path / "ranker.jsonl"
    manifest_path = tmp_path / "ranker.manifest.json"
    record = feature_vector_to_trace_record(
        {
            "ue_id": "ue-1",
            "latitude": 10.0,
            "longitude": 20.0,
            "connected_to": "A",
            "neighbor_rsrp_dbm": {"A": -90.0, "B": -70.0},
        },
        scenario="highway",
        seed=41,
        step_index=0,
        timestamp_s=0.0,
    )
    write_trace_jsonl([record], trace_path)

    manifest = export_ranker_dataset(
        SimpleNamespace(
            trace=[str(trace_path)],
            output=str(output_path),
            manifest=str(manifest_path),
            forbid_evaluation_seed="42,43,44",
            sequence_window_steps=1,
            stay_margin_db=2.0,
            handover_penalty_db=0.0,
            load_penalty_db=0.0,
            sinr_weight=0.0,
            rsrq_weight=0.0,
            missing_future_cell_score=-160.0,
            same_site_penalty_db=6.0,
            rf_regression_penalty_db=4.0,
            short_dwell_penalty_db=4.0,
            ping_pong_risk_penalty_db=5.0,
            min_dwell_time_s=10.0,
            min_high_complexity_rows=0,
            overwrite=False,
        )
    )

    assert output_path.exists()
    assert manifest_path.exists()
    loaded_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["row_count"] == 1
    assert loaded_manifest["dataset_type"] == "candidate_ranker_jsonl"
    assert loaded_manifest["scenario_seeds"] == [41]
    assert loaded_manifest["label_policy"]["name"] == "sequence_stay_aware_margin_ranker"
    assert loaded_manifest["label_policy"]["version"] == 2
    assert loaded_manifest["trace_complexity_summaries"]


def test_export_candidate_ranker_dataset_rejects_seed_leakage(tmp_path):
    trace_path = tmp_path / "trace.jsonl"
    record = feature_vector_to_trace_record(
        {
            "ue_id": "ue-1",
            "latitude": 10.0,
            "longitude": 20.0,
            "connected_to": "A",
            "neighbor_rsrp_dbm": {"A": -90.0, "B": -70.0},
        },
        scenario="highway",
        seed=42,
        step_index=0,
        timestamp_s=0.0,
    )
    write_trace_jsonl([record], trace_path)

    with pytest.raises(ValueError, match="overlap"):
        export_ranker_dataset(
            SimpleNamespace(
                trace=[str(trace_path)],
                output=str(tmp_path / "ranker.jsonl"),
                manifest=None,
                forbid_evaluation_seed="42",
                sequence_window_steps=1,
                stay_margin_db=2.0,
                handover_penalty_db=0.0,
                load_penalty_db=0.0,
                sinr_weight=0.0,
                rsrq_weight=0.0,
                missing_future_cell_score=-160.0,
                same_site_penalty_db=6.0,
                rf_regression_penalty_db=4.0,
                short_dwell_penalty_db=4.0,
                ping_pong_risk_penalty_db=5.0,
                min_dwell_time_s=10.0,
                min_high_complexity_rows=0,
                overwrite=False,
            )
        )


def test_export_candidate_ranker_dataset_rejects_missing_high_complexity_rows(tmp_path):
    trace_path = tmp_path / "trace.jsonl"
    record = feature_vector_to_trace_record(
        {
            "ue_id": "ue-1",
            "latitude": 10.0,
            "longitude": 20.0,
            "connected_to": "A",
            "neighbor_rsrp_dbm": {"A": -90.0, "B": -70.0},
        },
        scenario="highway",
        seed=41,
        step_index=0,
        timestamp_s=0.0,
    )
    write_trace_jsonl([record], trace_path)

    with pytest.raises(ValueError, match="insufficient high-complexity"):
        export_ranker_dataset(
            SimpleNamespace(
                trace=[str(trace_path)],
                output=str(tmp_path / "ranker.jsonl"),
                manifest=None,
                forbid_evaluation_seed="42,43,44",
                sequence_window_steps=1,
                stay_margin_db=2.0,
                handover_penalty_db=0.0,
                load_penalty_db=0.0,
                sinr_weight=0.0,
                rsrq_weight=0.0,
                missing_future_cell_score=-160.0,
                same_site_penalty_db=6.0,
                rf_regression_penalty_db=4.0,
                short_dwell_penalty_db=4.0,
                ping_pong_risk_penalty_db=5.0,
                min_dwell_time_s=10.0,
                min_high_complexity_rows=1,
                overwrite=False,
            )
        )
