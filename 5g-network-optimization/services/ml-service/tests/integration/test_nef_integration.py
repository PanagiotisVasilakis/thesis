import json
from unittest.mock import patch, AsyncMock, MagicMock
import pytest

from ml_service.app.data import nef_collector
from ml_service.app.data.nef_collector import NEFDataCollector

# Data collection requires a healthy NEF service; `get_status` must return HTTP 200.

def test_login_success(mock_nef_client):
    mock_nef_client.login.return_value = True
    mock_nef_client.token = "tok"
    mock_nef_client.get_headers.return_value = {"Authorization": "Bearer tok"}
    with patch.object(nef_collector, "NEFClient", lambda *a, **k: mock_nef_client):
        collector = NEFDataCollector(nef_url="http://nef", username="u", password="p")
        assert collector.login() is True
        assert collector.client.token == "tok"
        mock_nef_client.login.assert_called_once()


def test_get_ue_movement_state(mock_nef_client):
    mock_nef_client.get_ue_movement_state.return_value = {"ue1": {"latitude": 1, "longitude": 2}}
    with patch.object(nef_collector, "NEFClient", lambda *a, **k: mock_nef_client):
        collector = NEFDataCollector(nef_url="http://nef")
        state = collector.get_ue_movement_state()
        assert state["ue1"]["latitude"] == 1
        mock_nef_client.get_ue_movement_state.assert_called_once()


@pytest.mark.asyncio
async def test_collect_training_data(mock_nef_client):
    sample_state = {"ue1": {"latitude": 0, "longitude": 0, "speed": 1.0, "Cell_id": "A"}}
    mock_nef_client.get_ue_movement_state.return_value = sample_state
    mock_nef_client.get_feature_vector.return_value = {}
    # Simulate a healthy NEF service by returning HTTP 200 from get_status
    mock_nef_client.get_status.return_value = MagicMock(status_code=200)
    times = iter([0, 0.1, 0.2, 1.1, 1.2])
    with patch.object(nef_collector, "NEFClient", lambda *a, **k: mock_nef_client), \
         patch("asyncio.sleep", new=AsyncMock()), \
         patch("time.time", side_effect=lambda: next(times, 999999)):
        collector = NEFDataCollector(nef_url="http://nef")
        # Provide deterministic time progression only during data collection
        def time_gen():
            for t in [0, 0.1, 0.2]:
                yield t
            while True:
                yield 2
        time_iter = time_gen()
        with patch("time.time", side_effect=lambda: next(time_iter)):
            data = await collector.collect_training_data(duration=1, interval=1)
        assert len(data) == 1
        assert data[0]["ue_id"] == "ue1"
        assert data[0]["altitude"] is None
        assert data[0]["time_since_handover"] == 0.0


@pytest.mark.asyncio
async def test_collect_training_data_file(tmp_path, mock_nef_client):
    """Verify collected data is saved under collected_data."""
    sample_state = {"ue1": {"latitude": 0, "longitude": 0, "speed": 1.0, "Cell_id": "A"}}
    mock_nef_client.get_ue_movement_state.return_value = sample_state
    mock_nef_client.get_feature_vector.return_value = {}
    # Simulate a healthy NEF service by returning HTTP 200 from get_status
    mock_nef_client.get_status.return_value = MagicMock(status_code=200)
    times = iter([0, 0.1, 0.2, 1.1, 1.2])
    with patch.object(nef_collector, "NEFClient", lambda *a, **k: mock_nef_client), \
         patch("asyncio.sleep", new=AsyncMock()), \
         patch("time.time", side_effect=lambda: next(times, 999999)):
        collector = NEFDataCollector(nef_url="http://nef")
        collector.data_dir = str(tmp_path / "collected_data")
        def time_gen():
            for t in [0, 0.1, 0.2]:
                yield t
            while True:
                yield 2
        time_iter = time_gen()
        with patch("time.time", side_effect=lambda: next(time_iter)):
            data = await collector.collect_training_data(duration=1, interval=1)

        files = list((tmp_path / "collected_data").iterdir())
        assert len(files) == 1
        with open(files[0]) as f:
            saved = json.load(f)
        assert saved == data
        assert "altitude" in saved[0]
        assert saved[0]["altitude"] is None
