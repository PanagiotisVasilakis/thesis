import json

from scripts.policy_comparison.calibrate_tuned_a3 import (
    calibrate_tuned_a3_config,
    main,
)
from scripts.policy_comparison.nef_trace import feature_vector_to_trace_record
from scripts.policy_comparison.trace_io import write_trace_jsonl


def make_record(seed=41, step=0, scenario="highway", topology_hash="topology"):
    return feature_vector_to_trace_record(
        {
            "ue_id": "ue-1",
            "latitude": 37.1,
            "longitude": 23.2,
            "connected_to": "cell-a",
            "neighbor_rsrp_dbm": {"cell-a": -84.0, "cell-b": -78.0},
        },
        scenario=scenario,
        seed=seed,
        step_index=step,
        timestamp_s=float(step),
        topology_hash=topology_hash,
    )


def write_trace(path, records):
    write_trace_jsonl(records, path)
    return path


def test_calibrate_tuned_a3_writes_reusable_config(tmp_path):
    trace = write_trace(
        tmp_path / "calibration.jsonl",
        [make_record(step=0), make_record(step=1)],
    )
    output = tmp_path / "tuned_a3_config.json"

    result = calibrate_tuned_a3_config(trace, output)

    assert result == output
    config = json.loads(output.read_text(encoding="utf-8"))
    assert config["selected_parameters"]["a3_offset_db"] is not None
    assert "hysteresis_db" in config["selected_parameters"]
    assert "time_to_trigger_s" in config["selected_parameters"]
    assert "cooldown_s" in config["selected_parameters"]
    assert config["objective"]
    assert config["calibration"]["seed"] == 41
    assert config["calibration"]["scenario"] == "highway"
    assert config["calibration"]["topology_hash"] == "topology"
    assert config["record_count"] == 2
    assert config["evaluated_configuration_scores"]
    assert config["uses_ml_outputs"] is False
    assert "decisions" not in config["evaluated_configuration_scores"][0]


def test_calibrate_tuned_a3_accepts_multiple_calibration_traces(tmp_path):
    trace_a = write_trace(
        tmp_path / "calibration_seed41.jsonl",
        [make_record(seed=41, step=0), make_record(seed=41, step=1)],
    )
    trace_b = write_trace(
        tmp_path / "calibration_seed42.jsonl",
        [make_record(seed=42, step=0), make_record(seed=42, step=1)],
    )
    output = tmp_path / "tuned_a3_config.json"

    result = calibrate_tuned_a3_config([trace_a, trace_b], output)

    assert result == output
    config = json.loads(output.read_text(encoding="utf-8"))
    assert config["calibration"]["seed"] == 41
    assert config["calibration_seeds"] == [41, 42]
    assert len(config["calibrations"]) == 2
    assert config["record_count"] == 4
    assert config["calibration_trace_count"] == 2
    assert set(config["trace_hashes"]) == {str(trace_a), str(trace_b)}


def test_calibrate_tuned_a3_rejects_empty_trace(tmp_path):
    trace = tmp_path / "empty.jsonl"
    trace.write_text("", encoding="utf-8")

    code = main(
        [
            "--calibration-trace",
            str(trace),
            "--output",
            str(tmp_path / "config.json"),
        ]
    )

    assert code == 1


def test_calibrate_tuned_a3_rejects_mixed_seed_trace(tmp_path):
    trace = write_trace(
        tmp_path / "mixed.jsonl",
        [make_record(seed=41, step=0), make_record(seed=42, step=1)],
    )

    code = main(
        [
            "--calibration-trace",
            str(trace),
            "--output",
            str(tmp_path / "config.json"),
        ]
    )

    assert code == 1


def test_calibrate_tuned_a3_rejects_mixed_scenario_trace(tmp_path):
    trace = write_trace(
        tmp_path / "mixed.jsonl",
        [make_record(scenario="highway", step=0), make_record(scenario="smart_city", step=1)],
    )

    code = main(
        [
            "--calibration-trace",
            str(trace),
            "--output",
            str(tmp_path / "config.json"),
        ]
    )

    assert code == 1


def test_calibrate_tuned_a3_rejects_missing_topology_hash(tmp_path):
    trace = write_trace(
        tmp_path / "missing_topology.jsonl",
        [make_record(topology_hash=None, step=0), make_record(topology_hash=None, step=1)],
    )

    code = main(
        [
            "--calibration-trace",
            str(trace),
            "--output",
            str(tmp_path / "config.json"),
        ]
    )

    assert code == 1


def test_calibrate_tuned_a3_rejects_missing_rsrp(tmp_path):
    trace = tmp_path / "bad.jsonl"
    trace.write_text(
        json.dumps(
            {
                "scenario": "highway",
                "seed": 41,
                "timestamp_s": 0.0,
                "step_index": 0,
                "ue_id": "ue-1",
                "serving_cell": "cell-a",
                "ue_position": {"latitude": 37.1, "longitude": 23.2},
                "visible_cells": [{"cell_id": "cell-a"}],
                "topology_hash": "topology",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    code = main(
        [
            "--calibration-trace",
            str(trace),
            "--output",
            str(tmp_path / "config.json"),
        ]
    )

    assert code == 1
