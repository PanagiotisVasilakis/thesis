import json
import asyncio
from unittest.mock import MagicMock

from ml_service.app.data import nef_collector
from ml_service.app.data.nef_collector import NEFDataCollector


def test_login_success(monkeypatch):
    mock_client = MagicMock()
    mock_client.login.return_value = True
    mock_client.token = "tok"
    mock_client.get_headers.return_value = {"Authorization": "Bearer tok"}
    monkeypatch.setattr(nef_collector, "NEFClient", lambda *a, **k: mock_client)
    collector = NEFDataCollector(nef_url="http://nef", username="u", password="p")
    assert collector.login() is True
    assert collector.client.token == "tok"
    assert collector.client.get_headers()["Authorization"] == "Bearer tok"


def test_collect_training_data(monkeypatch, tmp_path):
    sample_state = {"ue1": {"latitude": 0, "longitude": 0, "speed": 1.0, "Cell_id": "A"}}
    mock_client = MagicMock()
    mock_client.get_ue_movement_state.return_value = sample_state
    mock_client.get_feature_vector.return_value = {
        "neighbor_rsrp_dbm": {"A": -70},
        "neighbor_sinrs": {"A": 8}
    }
    monkeypatch.setattr(nef_collector, "NEFClient", lambda *a, **k: mock_client)
    collector = NEFDataCollector(nef_url="http://nef")
    collector.data_dir = str(tmp_path)
    monkeypatch.setattr(nef_collector.time, "sleep", lambda x: None)
    times = iter([0, 0.1, 1.1])
    monkeypatch.setattr(nef_collector.time, "time", lambda: next(times))

    import asyncio
    data = asyncio.run(collector.collect_training_data(duration=1, interval=1))
    assert len(data) == 1
    assert data[0]["ue_id"] == "ue1"
    assert data[0]["rf_metrics"] == {"A": {"rsrp": -70, "sinr": 8}}
    saved = list(tmp_path.iterdir())
    with open(saved[0]) as f:
        loaded = json.load(f)
    assert loaded == data
