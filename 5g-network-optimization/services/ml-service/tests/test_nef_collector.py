import json
from unittest.mock import MagicMock

from ml_service.app.data import nef_collector
from ml_service.app.data.nef_collector import NEFDataCollector


def test_login(monkeypatch):
    mock_client = MagicMock()
    mock_client.login.return_value = True
    mock_client.token = "tok"
    mock_client.get_headers.return_value = {"Authorization": "Bearer tok"}
    monkeypatch.setattr(nef_collector, "NEFClient", lambda *a, **k: mock_client)
    collector = NEFDataCollector(nef_url="http://nef", username="u", password="p")
    assert collector.login() is True
    assert collector.client.token == "tok"
    assert collector.client.get_headers()["Authorization"] == "Bearer tok"


def test_get_ue_movement_state(monkeypatch):
    collector = NEFDataCollector(nef_url="http://nef")
    mock_client = MagicMock(get_ue_movement_state=lambda: {"ue1": {"latitude": 1}})
    collector.client = mock_client
    state = collector.get_ue_movement_state()
    assert state == {"ue1": {"latitude": 1}}


import pytest


@pytest.mark.asyncio
async def test_collect_training_data(tmp_path, monkeypatch):
    collector = NEFDataCollector(nef_url="http://nef")
    collector.data_dir = str(tmp_path)

    sample_state = {"ue1": {"latitude": 0, "longitude": 0, "speed": 1.0, "Cell_id": "A"}}
    mock_client = MagicMock()
    mock_client.get_ue_movement_state.return_value = sample_state
    mock_client.get_feature_vector.return_value = {
        "neighbor_rsrp_dbm": {"A": -75},
        "neighbor_sinrs": {"A": 12}
    }
    collector.client = mock_client
    async def fake_sleep(_):
        return None

    monkeypatch.setattr(nef_collector.asyncio, "sleep", fake_sleep)
    times = iter([0, 0.1, 1.1])
    monkeypatch.setattr(nef_collector.time, "time", lambda: next(times))

    data = await collector.collect_training_data(duration=1, interval=1)
    assert len(data) == 1
    assert data[0]["ue_id"] == "ue1"
    assert data[0]["rf_metrics"] == {"A": {"rsrp": -75, "sinr": 12}}
    assert data[0]["optimal_antenna"] == "A"

    files = list(tmp_path.iterdir())
    assert len(files) == 1
    with open(files[0]) as f:
        saved = json.load(f)
    assert saved == data
