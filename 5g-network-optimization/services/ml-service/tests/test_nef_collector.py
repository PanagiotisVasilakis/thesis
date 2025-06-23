import importlib.util
from pathlib import Path
import json
from unittest.mock import MagicMock

NEF_COLLECTOR_PATH = Path(__file__).resolve().parents[1] / "app" / "data" / "nef_collector.py"
spec = importlib.util.spec_from_file_location("nef_collector", NEF_COLLECTOR_PATH)
nef_collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nef_collector)
NEFDataCollector = nef_collector.NEFDataCollector


def test_login(monkeypatch):
    collector = NEFDataCollector(nef_url="http://nef", username="u", password="p")
    mock_resp = MagicMock(status_code=200, json=lambda: {"access_token": "tok"})
    monkeypatch.setattr(nef_collector.requests, "post", lambda *a, **k: mock_resp)
    assert collector.login() is True
    assert collector.token == "tok"
    assert collector.headers["Authorization"] == "Bearer tok"


def test_get_ue_movement_state(monkeypatch):
    collector = NEFDataCollector(nef_url="http://nef")
    collector.headers = {"Authorization": "Bearer tok"}
    mock_resp = MagicMock(status_code=200, json=lambda: {"ue1": {"latitude": 1}})
    monkeypatch.setattr(nef_collector.requests, "get", lambda *a, **k: mock_resp)
    state = collector.get_ue_movement_state()
    assert state == {"ue1": {"latitude": 1}}


def test_collect_training_data(tmp_path, monkeypatch):
    collector = NEFDataCollector(nef_url="http://nef")
    collector.data_dir = str(tmp_path)

    sample_state = {"ue1": {"latitude": 0, "longitude": 0, "speed": 1.0, "Cell_id": "A"}}
    mock_resp = MagicMock(status_code=200, json=lambda: sample_state)
    monkeypatch.setattr(nef_collector.requests, "get", lambda *a, **k: mock_resp)
    monkeypatch.setattr(nef_collector.time, "sleep", lambda x: None)
    times = iter([0, 0.1, 1.1])
    monkeypatch.setattr(nef_collector.time, "time", lambda: next(times))

    data = collector.collect_training_data(duration=1, interval=1)
    assert len(data) == 1
    assert data[0]["ue_id"] == "ue1"

    files = list(tmp_path.iterdir())
    assert len(files) == 1
    with open(files[0]) as f:
        saved = json.load(f)
    assert saved == data
