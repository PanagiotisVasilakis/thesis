import json
import asyncio
from unittest.mock import MagicMock

import pytest

from ml_service.app.clients.nef_client import NEFClientError
from ml_service.app.data import nef_collector
from ml_service.app.data.nef_collector import NEFDataCollector


def test_login(monkeypatch, mock_nef_client):
    mock_nef_client.login.return_value = True
    mock_nef_client.token = "tok"
    mock_nef_client.get_headers.return_value = {"Authorization": "Bearer tok"}
    monkeypatch.setattr(nef_collector, "NEFClient", lambda *a, **k: mock_nef_client)
    collector = NEFDataCollector(nef_url="http://nef", username="u", password="p")
    assert collector.login() is True
    assert collector.client.token == "tok"
    assert collector.client.get_headers()["Authorization"] == "Bearer tok"


def test_get_ue_movement_state(mock_nef_client):
    collector = NEFDataCollector(nef_url="http://nef")
    mock_nef_client.get_ue_movement_state.return_value = {"ue1": {"latitude": 1}}
    collector.client = mock_nef_client
    state = collector.get_ue_movement_state()
    assert state == {"ue1": {"latitude": 1}}


@pytest.mark.asyncio
@pytest.mark.parametrize("status_obj", [None, MagicMock(status_code=500), object()])
async def test_collect_training_data_bad_status(mock_nef_client, status_obj):
    collector = NEFDataCollector(nef_url="http://nef")
    collector.client = mock_nef_client
    mock_nef_client.get_status.return_value = status_obj

    with pytest.raises(NEFClientError):
        await collector.collect_training_data(duration=1, interval=1)


@pytest.mark.asyncio
async def test_collect_training_data(tmp_path, monkeypatch, mock_nef_client):
    collector = NEFDataCollector(nef_url="http://nef")
    collector.data_dir = str(tmp_path)

    sample_state = {"ue1": {"latitude": 0, "longitude": 0, "speed": 1.0, "Cell_id": "A"}}
    mock_nef_client.get_ue_movement_state.return_value = sample_state
    mock_nef_client.get_feature_vector.return_value = {
        "neighbor_rsrp_dbm": {"A": -75},
        "neighbor_sinrs": {"A": 12},
        "neighbor_rsrqs": {"A": -10},
        "neighbor_cell_loads": {"A": 2},
    }
    collector.client = mock_nef_client

    async def fake_sleep(_):
        return None

    monkeypatch.setattr(nef_collector.asyncio, "sleep", fake_sleep)
    times = iter([0, 0.1, 1.1, 1.2, 1.3])
    monkeypatch.setattr(nef_collector.time, "time", lambda: next(times, 999999))

    data = await collector.collect_training_data(duration=1, interval=1)
    assert len(data) == 1
    assert data[0]["ue_id"] == "ue1"
    assert data[0]["altitude"] is None
    assert data[0]["rf_metrics"] == {"A": {"rsrp": -75, "sinr": 12, "rsrq": -10, "cell_load": 2}}
    assert data[0]["optimal_antenna"] == "A"
    assert data[0]["rsrp_stddev"] == 0.0
    assert data[0]["sinr_stddev"] == 0.0
    assert data[0]["time_since_handover"] == 0.0
    assert data[0]["heading_change_rate"] == 0.0
    assert data[0]["path_curvature"] == 0.0

    files = list(tmp_path.iterdir())
    assert len(files) == 1
    with open(files[0]) as f:
        saved = json.load(f)
    assert saved == data


def test_collect_training_data_invalid():
    collector = NEFDataCollector(nef_url="http://nef")
    with pytest.raises(ValueError):
        asyncio.run(collector.collect_training_data(duration=0, interval=1))


def test_collect_sample_missing_cell_id(mock_nef_client):
    collector = NEFDataCollector(nef_url="http://nef")
    collector.client = mock_nef_client

    result = collector._collect_sample("ue1", {"latitude": 0})

    assert result is None
    mock_nef_client.get_feature_vector.assert_not_called()


def test_collect_sample_selects_best_antenna(mock_nef_client):
    collector = NEFDataCollector(nef_url="http://nef")
    fv = {
        "neighbor_rsrp_dbm": {"A": -80, "B": -75},
        "neighbor_sinrs": {"A": 10, "B": 5},
        "neighbor_rsrqs": {"A": -12, "B": -9},
        "neighbor_cell_loads": {"A": 3, "B": 1},
    }
    mock_nef_client.get_feature_vector.return_value = fv
    collector.client = mock_nef_client

    ue_data = {"Cell_id": "A", "latitude": 0, "longitude": 0, "speed": 1.0}
    sample = collector._collect_sample("ue1", ue_data)

    assert "altitude" in sample
    assert sample["altitude"] is None
    assert sample["connected_to"] == "A"
    assert sample["optimal_antenna"] == "B"
    assert sample["altitude"] is None
    assert sample["rf_metrics"] == {
        "A": {"rsrp": -80, "sinr": 10, "rsrq": -12, "cell_load": 3},
        "B": {"rsrp": -75, "sinr": 5, "rsrq": -9, "cell_load": 1},
    }
    assert sample["rsrp_stddev"] == 0.0
    assert sample["sinr_stddev"] == 0.0
    assert sample["time_since_handover"] == 0.0
    assert sample["heading_change_rate"] == 0.0
    assert sample["path_curvature"] == 0.0
    mock_nef_client.get_feature_vector.assert_called_once_with("ue1")


@pytest.mark.asyncio
async def test_collect_training_data_empty(tmp_path, monkeypatch, mock_nef_client):
    """When no samples are collected, an empty JSON file should be written."""
    collector = NEFDataCollector(nef_url="http://nef")
    collector.data_dir = str(tmp_path)

    mock_nef_client.get_ue_movement_state.return_value = {}
    collector.client = mock_nef_client

    async def fake_sleep(_):
        return None

    monkeypatch.setattr(nef_collector.asyncio, "sleep", fake_sleep)
    times = iter([0, 0.1, 1.1, 1.2, 1.3])
    monkeypatch.setattr(nef_collector.time, "time", lambda: next(times, 999999))

    data = await collector.collect_training_data(duration=1, interval=1)
    assert data == []

    files = list(tmp_path.iterdir())
    assert len(files) == 1
    with open(files[0]) as f:
        saved = json.load(f)
    assert saved == []
