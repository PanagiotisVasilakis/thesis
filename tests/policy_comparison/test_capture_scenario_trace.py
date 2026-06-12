import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.policy_comparison import capture_scenario_trace as runner
from scripts.policy_comparison.nef_trace import feature_vector_to_trace_record


def test_fresh_output_dir_rejects_nonempty_directory(tmp_path):
    output_dir = tmp_path / "trace"
    output_dir.mkdir()
    (output_dir / "old.txt").write_text("old", encoding="utf-8")

    with pytest.raises(ValueError, match="not empty"):
        runner.ensure_fresh_output_dir(output_dir)


def test_default_highway_ue_ids_are_all_ten_highway_vehicles():
    assert runner.default_ue_ids_for_scenario("highway") == [
        "202010000002001",
        "202010000002002",
        "202010000002003",
        "202010000002004",
        "202010000002005",
        "202010000002006",
        "202010000002007",
        "202010000002008",
        "202010000002009",
        "202010000002010",
    ]


def test_default_dense_highway_ue_ids_are_all_ten_highway_vehicles():
    assert runner.default_ue_ids_for_scenario("highway_dense") == [
        "202010000002001",
        "202010000002002",
        "202010000002003",
        "202010000002004",
        "202010000002005",
        "202010000002006",
        "202010000002007",
        "202010000002008",
        "202010000002009",
        "202010000002010",
    ]


def test_non_highway_requires_explicit_ue_ids():
    with pytest.raises(ValueError, match="--ue-id is required"):
        runner.default_ue_ids_for_scenario("smart_city")


class FakeUE:
    def __init__(self, supi):
        self.supi = supi


class FakeScenario:
    def __init__(self):
        self.ues = [FakeUE("ue-1")]
        self.started = []
        self.stopped = []

    def deploy(self):
        return True

    def save_topology(self, path: Path):
        path.write_text(
            json.dumps(
                {
                    "metadata": {"name": "Highway", "created_at": "volatile"},
                    "cells": [],
                    "ues": [{"supi": "ue-1"}],
                    "paths": [],
                }
            ),
            encoding="utf-8",
        )

    def start_ue_movement(self, ue_id):
        self.started.append(ue_id)
        return True

    def stop_ue_movement(self, ue_id):
        self.stopped.append(ue_id)
        return True


def test_capture_scenario_trace_uses_shared_nef_trace_capture_mode(tmp_path, monkeypatch):
    compose_file = tmp_path / "docker-compose.yml"
    compose_file.write_text("services: {}\n", encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    output_dir = tmp_path / "trace-output"
    fake_scenario = FakeScenario()
    calls = {"modes": [], "compose": []}

    monkeypatch.setenv("NEF_URL", "http://nef.local")
    monkeypatch.setenv("NEF_USERNAME", "user")
    monkeypatch.setenv("NEF_PASSWORD", "pass")
    monkeypatch.setattr(runner, "cleanup_docker", lambda compose: None)
    monkeypatch.setattr(runner, "load_env_file", lambda path: None)
    monkeypatch.setattr(runner, "normalize_runtime_env", lambda: None)
    monkeypatch.setattr(runner, "wait_for_nef_service", lambda nef_url: True)
    monkeypatch.setattr(
        runner,
        "set_handover_mode",
        lambda mode, nef_url: calls["modes"].append((mode, nef_url)) or True,
    )
    monkeypatch.setattr(runner, "get_scenario", lambda scenario_name, seed: fake_scenario)
    monkeypatch.setattr(runner, "topology_hash", lambda path: "topology-hash")
    monkeypatch.setattr(runner.time, "sleep", lambda seconds: None)

    def fake_capture(**kwargs):
        assert kwargs["nef_url"] == "http://nef.local"
        assert kwargs["ue_ids"] == ["ue-1"]
        assert kwargs["topology_hash"] == "topology-hash"
        return [
            feature_vector_to_trace_record(
                {
                    "ue_id": "ue-1",
                    "latitude": 37.1,
                    "longitude": 23.2,
                    "connected_to": "cell-a",
                    "neighbor_rsrp_dbm": {"cell-a": -80.0, "cell-b": -75.0},
                },
                scenario="highway",
                seed=41,
                step_index=0,
                timestamp_s=0.0,
                topology_hash="topology-hash",
            )
        ]

    monkeypatch.setattr(runner, "capture_nef_trace_records", fake_capture)

    def fake_run(command, **kwargs):
        calls["compose"].append((command, kwargs.get("env", {})))
        stdout = kwargs.get("stdout")
        if stdout is not None:
            stdout.write("docker logs\n")
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    trace_path = runner.capture_scenario_trace(
        scenario_name="highway",
        seed=41,
        output_dir=output_dir,
        ue_ids=["ue-1"],
        samples=1,
        interval_s=0.0,
        timeout_s=1.0,
        env_file=env_file,
        compose_file=compose_file,
        nef_url="http://nef.local",
        start_delay_s=0.0,
        warmup_s=0.0,
    )

    assert trace_path == output_dir / "trace.jsonl"
    assert trace_path.exists()
    assert calls["modes"] == [("trace_capture", "http://nef.local")]
    assert fake_scenario.started == ["ue-1"]
    assert fake_scenario.stopped == ["ue-1"]
    assert calls["compose"][0][0][-2:] == ["up", "-d"]
    assert calls["compose"][0][1]["COMPOSE_PROFILES"] == ""
    assert calls["compose"][-1][0][-2:] == ["down", "-v"]

    metadata = json.loads((output_dir / "trace.metadata.json").read_text(encoding="utf-8"))
    assert metadata["handover_mode"] == "trace_capture"
    assert metadata["policy_free"] is True
    assert metadata["topology_hash"] == "topology-hash"
