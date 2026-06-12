import json

import scripts.policy_comparison.capture_nef_trace as capture_cli
from scripts.policy_comparison.capture_nef_trace import main, parse_ue_ids
from scripts.policy_comparison.nef_trace import capture_nef_trace_records
from scripts.policy_comparison.trace_io import read_trace_jsonl


def feature_vector(ue_id, connected_to="cell-a"):
    return {
        "ue_id": ue_id,
        "latitude": 37.1,
        "longitude": 23.2,
        "speed": 20.0,
        "connected_to": connected_to,
        "neighbor_rsrp_dbm": {"cell-a": -84.0, "cell-b": -78.0},
        "neighbor_sinrs": {"cell-a": 7.0, "cell-b": 10.0},
        "neighbor_rsrqs": {"cell-a": -12.0, "cell-b": -9.0},
        "neighbor_cell_loads": {"cell-a": 3, "cell-b": 1},
    }


def test_parse_ue_ids_accepts_repeated_and_comma_separated_values():
    assert parse_ue_ids(["ue-1,ue-2", "ue-3"]) == ["ue-1", "ue-2", "ue-3"]


def test_parse_ue_ids_rejects_duplicates():
    try:
        parse_ue_ids(["ue-1,ue-1"])
    except ValueError as exc:
        assert "duplicate" in str(exc)
    else:
        raise AssertionError("duplicate UE IDs should be rejected")


def test_capture_records_uses_existing_feature_fetcher_without_policy_decisions():
    calls = []
    monotonic_values = iter([100.0, 100.0, 101.0])

    def fake_fetcher(nef_url, ue_id, timeout_s):
        calls.append((nef_url, ue_id, timeout_s))
        return feature_vector(ue_id)

    records = capture_nef_trace_records(
        nef_url="http://nef.local",
        ue_ids=["ue-1", "ue-2"],
        scenario="highway",
        seed=42,
        samples=2,
        interval_s=0.0,
        timeout_s=3.0,
        topology_hash="topology",
        fetcher=fake_fetcher,
        monotonic_clock=lambda: next(monotonic_values),
    )

    assert len(records) == 4
    assert calls == [
        ("http://nef.local", "ue-1", 3.0),
        ("http://nef.local", "ue-2", 3.0),
        ("http://nef.local", "ue-1", 3.0),
        ("http://nef.local", "ue-2", 3.0),
    ]
    assert records[0].timestamp_s == 0.0
    assert records[2].timestamp_s == 1.0
    assert records[0].source == "nef_live_capture"
    assert "decision_type" not in records[0].to_dict()


def test_capture_records_hashes_topology_json(tmp_path):
    topology = tmp_path / "topology.json"
    topology.write_text('{"cells": [{"id": "cell-a"}]}', encoding="utf-8")

    records = capture_nef_trace_records(
        nef_url="http://nef.local",
        ue_ids=["ue-1"],
        scenario="highway",
        seed=42,
        samples=1,
        interval_s=0.0,
        topology_json=topology,
        fetcher=lambda nef_url, ue_id, timeout_s: feature_vector(ue_id),
        monotonic_clock=lambda: 0.0,
    )

    assert records[0].topology_hash is not None
    assert len(records[0].topology_hash) == 64


def test_capture_cli_rejects_invalid_sample_count_without_writing(tmp_path):
    output = tmp_path / "trace.jsonl"

    code = main(
        [
            "--scenario",
            "highway",
            "--seed",
            "42",
            "--ue-id",
            "ue-1",
            "--output",
            str(output),
            "--nef-url",
            "http://127.0.0.1:1",
            "--samples",
            "0",
        ]
    )

    assert code == 1
    assert not output.exists()


def test_capture_cli_rejects_nonempty_output(tmp_path):
    output = tmp_path / "trace.jsonl"
    output.write_text("old", encoding="utf-8")

    code = main(
        [
            "--scenario",
            "highway",
            "--seed",
            "42",
            "--ue-id",
            "ue-1",
            "--output",
            str(output),
            "--nef-url",
            "http://127.0.0.1:1",
        ]
    )

    assert code == 1


def test_capture_cli_resolves_nef_url_from_env_and_writes_files(tmp_path, monkeypatch):
    output = tmp_path / "trace.jsonl"
    monkeypatch.setenv("NEF_URL", "http://nef.local")

    def fake_capture(**kwargs):
        assert kwargs["nef_url"] == "http://nef.local"
        assert kwargs["ue_ids"] == ["ue-1"]
        return capture_nef_trace_records(
            nef_url="http://nef.local",
            ue_ids=["ue-1"],
            scenario="highway",
            seed=42,
            samples=1,
            interval_s=0.0,
            fetcher=lambda nef_url, ue_id, timeout_s: feature_vector(ue_id),
            monotonic_clock=lambda: 0.0,
        )

    monkeypatch.setattr(capture_cli, "capture_nef_trace_records", fake_capture)

    code = main(
        [
            "--scenario",
            "highway",
            "--seed",
            "42",
            "--ue-id",
            "ue-1",
            "--output",
            str(output),
        ]
    )

    assert code == 0
    records = read_trace_jsonl(output)
    assert len(records) == 1
    assert read_trace_jsonl(output) == records
    saved_metadata = json.loads(
        output.with_suffix(output.suffix + ".metadata.json").read_text(
            encoding="utf-8"
        )
    )
    assert saved_metadata["no_handover_applied"] is True
