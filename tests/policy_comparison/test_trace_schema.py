import json

import pytest

from scripts.policy_comparison.nef_trace import feature_vector_to_trace_record
from scripts.policy_comparison.schemas import MeasurementTraceRecord, TraceSchemaError
from scripts.policy_comparison.trace_io import (
    read_trace_jsonl,
    topology_hash_from_path,
    write_trace_jsonl,
)


def feature_vector():
    return {
        "ue_id": "ue-1",
        "latitude": 37.1,
        "longitude": 23.2,
        "altitude": 10.0,
        "speed": 33.0,
        "connected_to": "cell-a",
        "neighbor_rsrp_dbm": {"cell-a": -84.0, "cell-b": -78.0},
        "neighbor_sinrs": {"cell-a": 8.0, "cell-b": 12.0},
        "neighbor_rsrqs": {"cell-a": -11.0, "cell-b": -9.0},
        "neighbor_cell_loads": {"cell-a": 4, "cell-b": 2},
    }


def test_feature_vector_to_trace_record_preserves_required_measurements():
    record = feature_vector_to_trace_record(
        feature_vector(),
        scenario="highway",
        seed=42,
        step_index=3,
        timestamp_s=12.5,
        topology_hash="topology-hash",
    )

    assert record.scenario == "highway"
    assert record.seed == 42
    assert record.step_index == 3
    assert record.timestamp_s == 12.5
    assert record.ue_position == {
        "latitude": 37.1,
        "longitude": 23.2,
        "altitude": 10.0,
    }
    assert record.serving_cell == "cell-a"
    assert record.visible_cell_map["cell-b"].rsrp_dbm == -78.0
    assert record.visible_cell_map["cell-b"].sinr_db == 12.0
    assert record.visible_cell_map["cell-b"].rsrq_db == -9.0
    assert record.visible_cell_map["cell-b"].load == 2.0


@pytest.mark.parametrize(
    "missing_field",
    ["ue_id", "latitude", "longitude", "connected_to", "neighbor_rsrp_dbm"],
)
def test_feature_vector_to_trace_record_fails_on_missing_required_fields(missing_field):
    payload = feature_vector()
    payload.pop(missing_field)

    with pytest.raises(TraceSchemaError):
        feature_vector_to_trace_record(
            payload,
            scenario="highway",
            seed=42,
            step_index=0,
            timestamp_s=0.0,
        )


def test_trace_record_rejects_policy_decision_fields():
    record = feature_vector_to_trace_record(
        feature_vector(),
        scenario="highway",
        seed=42,
        step_index=0,
        timestamp_s=0.0,
    ).to_dict()
    record["decision_type"] = "handover"

    with pytest.raises(TraceSchemaError, match="policy decision fields"):
        MeasurementTraceRecord.from_dict(record)


def test_trace_jsonl_round_trip(tmp_path):
    record = feature_vector_to_trace_record(
        feature_vector(),
        scenario="highway",
        seed=42,
        step_index=0,
        timestamp_s=0.0,
    )
    path = tmp_path / "trace.jsonl"

    write_trace_jsonl([record], path)

    raw = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert "policy_name" not in raw[0]
    assert read_trace_jsonl(path) == [record]


def test_topology_hash_ignores_volatile_created_at(tmp_path):
    left = tmp_path / "left_topology.json"
    right = tmp_path / "right_topology.json"
    payload = {
        "metadata": {"name": "highway", "created_at": "2026-01-01T00:00:00"},
        "cells": [{"cell_id": "100000001", "latitude": 1.0, "longitude": 2.0}],
    }
    left.write_text(json.dumps(payload), encoding="utf-8")
    payload["metadata"]["created_at"] = "2026-01-02T00:00:00"
    right.write_text(json.dumps(payload), encoding="utf-8")

    assert topology_hash_from_path(left) == topology_hash_from_path(right)
