import json
import math

from scripts.policy_comparison.oracle_policy import action_features, solve_cost_to_go
from scripts.policy_comparison.oracle_ranker_artifact import load_oracle_ranker_artifact
from scripts.policy_comparison.train_oracle_model_ladder import _evaluate, train_ladder
from scripts.policy_comparison.qos_model import estimate_counterfactual_qos
from scripts.policy_comparison.schemas import MeasurementTraceRecord, VisibleCellMeasurement
from scripts.policy_comparison.trace_io import write_trace_jsonl
from scripts.policy_comparison.validate_physical_trace import validate_trace
from scripts.policy_comparison.v3_protocol import require_capture_allowed
from scripts.scenarios.highway_handover import (
    DenseHighwayV2Scenario,
    ModerateHighwayV2Scenario,
    SparseHighwayV2Scenario,
)


def _record(step=0, serving="120000001", seed=101):
    cells = [
        VisibleCellMeasurement(
            cell_id=f"12{index:07X}",
            rsrp_dbm=-80.0 - index,
            sinr_db=10.0 - index,
            rsrq_db=-8.0 - index / 10.0,
            load=float(index % 3),
        )
        for index in range(1, 9)
    ]
    return MeasurementTraceRecord(
        scenario="highway_sparse_v2",
        seed=seed,
        timestamp_s=float(step),
        step_index=step,
        ue_id="ue-1",
        serving_cell=serving,
        initial_serving_cell="120000001",
        topology_cell_ids=[cell.cell_id for cell in cells],
        ue_position={"latitude": float(step), "longitude": 0.0},
        visible_cells=cells,
        speed_mps=33.3,
        topology_hash="topology",
        service_type="embb",
        qos_requirements={
            "latency_requirement_ms": 30.0,
            "throughput_requirement_mbps": 20.0,
            "reliability_pct": 99.0,
            "jitter_ms": 10.0,
        },
        observed_qos={
            "latency_ms": 8.0,
            "throughput_mbps": 100.0,
            "packet_loss_rate": 0.1,
            "jitter_ms": 2.0,
        },
        trace_schema_version=3,
        metadata={
            "rf_provenance": {
                "fallback": False,
                "strict_mode": True,
                "path_loss_model": "3gpp_tr_38_901_rma",
                "all_topology_cells_exposed": True,
            },
            "qos_provenance": {"simulated": True, "model_version": "sinr_cqi_v1"},
            "movement_provenance": {
                "model": "distance_over_elapsed_time_ping_pong_v1",
                "coordinate_frame": "local_cartesian_m",
                "configured_speed_mps": 33.3,
                "path_distance_m": float(step),
                "path_length_m": 1000.0,
                "path_direction": 1,
                "elapsed_s": 1.0,
                "endpoint_reversal": False,
            },
            "ml_features": {"velocity": 33.3},
        },
    )


def test_physical_density_profiles_share_corridor_and_scale_cells():
    scenarios = [
        SparseHighwayV2Scenario(nef_url="http://nef.local", username="u", password="p"),
        ModerateHighwayV2Scenario(nef_url="http://nef.local", username="u", password="p"),
        DenseHighwayV2Scenario(nef_url="http://nef.local", username="u", password="p"),
    ]
    assert [len(scenario.generate_cells()) for scenario in scenarios] == [8, 16, 24]
    for scenario in scenarios:
        cells = scenario.generate_cells()
        assert len({cell.cell_id for cell in cells}) == len(cells)
        assert all(cell.horizontal_beamwidth_deg == 65.0 for cell in cells)
        assert set(cell.frequency_reuse_group for cell in cells).issubset({1, 2, 3})
        assert cells[0].latitude == cells[1].latitude
        assert (cells[0].azimuth_deg - cells[1].azimuth_deg) % 360.0 == 180.0
        start = scenario._interpolate_highway_point(0.0)
        end = scenario._interpolate_highway_point(1.0)
        assert 9_950.0 <= _haversine_m(start, end) <= 10_050.0


def test_physical_trace_validator_passes_complete_v3_trace(tmp_path):
    path = tmp_path / "trace.jsonl"
    write_trace_jsonl([_record(step) for step in range(3)], path)
    report = validate_trace(path)
    assert report["pass"] is True
    assert report["expected_cell_count"] == 8


def test_physical_trace_validator_blocks_rf_fallback(tmp_path):
    record = _record()
    metadata = dict(record.metadata)
    metadata["rf_provenance"] = {**metadata["rf_provenance"], "fallback": True}
    path = tmp_path / "trace.jsonl"
    write_trace_jsonl([record.__class__(**{**record.__dict__, "metadata": metadata})], path)
    report = validate_trace(path)
    assert report["pass"] is False
    assert "rf_fallback_active" in report["errors"]


def test_physical_trace_validator_requires_all_cell_measurements(tmp_path):
    record = _record()
    path = tmp_path / "trace.jsonl"
    write_trace_jsonl(
        [
            record.__class__(
                **{
                    **record.__dict__,
                    "visible_cells": record.visible_cells[:-1],
                }
            )
        ],
        path,
    )
    report = validate_trace(path)
    assert report["pass"] is False
    assert "incomplete_counterfactual_cell_measurements" in report["errors"]


def test_physical_trace_validator_requires_movement_provenance(tmp_path):
    record = _record()
    metadata = dict(record.metadata)
    metadata.pop("movement_provenance")
    path = tmp_path / "trace.jsonl"
    write_trace_jsonl(
        [record.__class__(**{**record.__dict__, "metadata": metadata})], path
    )
    report = validate_trace(path)
    assert report["pass"] is False
    assert "missing_movement_provenance" in report["errors"]


def test_physical_trace_validator_allows_ping_pong_endpoint_reversal(tmp_path):
    records = [_record(step) for step in range(5)]
    updates = {
        2: {"velocity": 4.0, "heading_change_rate": 0.0},
        3: {"velocity": 33.3, "heading_change_rate": 3.0},
    }
    adjusted = []
    for record in records:
        metadata = dict(record.metadata)
        metadata["ml_features"] = updates.get(
            record.step_index,
            {"velocity": 33.3, "heading_change_rate": 0.0},
        )
        adjusted.append(record.__class__(**{**record.__dict__, "metadata": metadata}))
    path = tmp_path / "trace.jsonl"
    write_trace_jsonl(adjusted, path)
    assert validate_trace(path)["pass"] is True


def test_physical_trace_validator_detects_reversal_between_feature_reads(tmp_path):
    records = [_record(step) for step in range(5)]
    positions = [0.0, 10.0, 19.0, 8.0, -2.0]
    adjusted = []
    for record, position in zip(records, positions):
        metadata = dict(record.metadata)
        metadata["ml_features"] = {
            "velocity": 20.0 if record.step_index == 2 else 33.3,
            "heading_change_rate": 0.0,
        }
        adjusted.append(
            record.__class__(
                **{
                    **record.__dict__,
                    "ue_position": {"latitude": position, "longitude": 0.0},
                    "metadata": metadata,
                }
            )
        )
    path = tmp_path / "trace.jsonl"
    write_trace_jsonl(adjusted, path)
    assert validate_trace(path)["pass"] is True


def test_physical_trace_validator_blocks_non_reversal_velocity_error(tmp_path):
    records = [_record(step) for step in range(5)]
    metadata = dict(records[2].metadata)
    metadata["ml_features"] = {"velocity": 20.0, "heading_change_rate": 0.0}
    records[2] = records[2].__class__(
        **{**records[2].__dict__, "metadata": metadata}
    )
    path = tmp_path / "trace.jsonl"
    write_trace_jsonl(records, path)
    report = validate_trace(path)
    assert report["pass"] is False
    assert "trajectory_velocity_mismatch" in report["errors"]


def test_counterfactual_qos_degrades_with_sinr_and_load():
    record = _record()
    good = estimate_counterfactual_qos(record, serving_cell="120000001", load=0.0)
    poor = estimate_counterfactual_qos(record, serving_cell="120000008", load=5.0)
    assert good["throughput_mbps"] > poor["throughput_mbps"]
    assert good["latency_ms"] < poor["latency_ms"]


def test_oracle_rows_include_stay_and_exclude_ids_from_features():
    rows = solve_cost_to_go([_record(step) for step in range(4)])
    first_group = [row for row in rows if row["step_index"] == 0]
    assert any(row["action_is_stay"] == 1.0 for row in first_group)
    assert sum(row["selected_label"] for row in first_group) == 1
    features = action_features(
        _record(), serving_cell="120000001", action_cell="120000002"
    )
    assert not {"ue_id", "serving_cell", "action_cell"}.intersection(features)


def test_model_ladder_uses_leave_one_seed_out_and_writes_hashed_artifact(tmp_path):
    rows = []
    for seed in (101, 102, 103):
        rows.extend(solve_cost_to_go([_record(step, seed=seed) for step in range(4)]))
    dataset = tmp_path / "oracle.jsonl"
    with dataset.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    columns = sorted(
        key
        for key, value in rows[0].items()
        if isinstance(value, (int, float))
        and key
        not in {
            "seed", "step_index", "selected_label", "oracle_action_cost",
            "oracle_regret", "oracle_utility", "relevance",
        }
    )
    manifest = tmp_path / "oracle.manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "feature_columns": columns,
                "forbidden_evaluation_seeds": list(range(201, 211)),
                "trace_hashes": {},
                "label_policy": "physical_cost_to_go_v1",
                "snapshot_group_count": 12,
            }
        ),
        encoding="utf-8",
    )
    artifact = tmp_path / "oracle.joblib"
    metadata = train_ladder(dataset, manifest, artifact)
    loaded = load_oracle_ranker_artifact(artifact)
    assert metadata["validation_split"] == "leave_one_seed_out_complete_trajectories"
    assert set(metadata["training_seeds"]) == {101, 102, 103}
    assert loaded.artifact_sha256 == metadata["model_sha256"]
    assert not {"ue_id", "serving_cell", "action_cell"}.intersection(
        loaded.feature_columns
    )


def test_oracle_model_evaluation_accepts_single_legal_action_group():
    class ConstantModel:
        @staticmethod
        def predict(matrix):
            return [0.0] * len(matrix)

    rows = [
        {
            "snapshot_group": "single",
            "feature": 1.0,
            "selected_label": 1,
            "oracle_regret": 0.0,
            "action_is_stay": 1.0,
            "relevance": 3,
        }
    ]
    metrics = _evaluate(ConstantModel(), rows, ["feature"])
    assert metrics["ndcg_at_5"] == 1.0
    assert metrics["top_action_accuracy"] == 1.0


def test_final_seed_is_blocked_until_protocol_is_frozen():
    protocol = {
        "final_seeds": [201],
        "metric_version": "v3_physical_qos_cost",
        "model_selection_frozen": False,
        "final_results_unlocked": False,
    }
    try:
        require_capture_allowed(201, protocol)
    except ValueError as exc:
        assert "blocked" in str(exc)
    else:
        raise AssertionError("final seed should be blocked before tuning passes")


def test_nonfinal_seed_does_not_require_unlock():
    require_capture_allowed(101, {"final_seeds": [201]})


def _haversine_m(first, second):
    lat1, lon1 = map(math.radians, first)
    lat2, lon2 = map(math.radians, second)
    value = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(value))
