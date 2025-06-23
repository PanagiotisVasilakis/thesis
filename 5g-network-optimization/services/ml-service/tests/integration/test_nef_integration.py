from unittest.mock import MagicMock, patch
import importlib.util
from pathlib import Path

NEF_COLLECTOR_PATH = Path(__file__).resolve().parents[2] / "app" / "data" / "nef_collector.py"
spec = importlib.util.spec_from_file_location("nef_collector", NEF_COLLECTOR_PATH)
nef_collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nef_collector)
NEFDataCollector = nef_collector.NEFDataCollector


def test_login_success():
    collector = NEFDataCollector(nef_url="http://nef", username="u", password="p")
    mock_resp = MagicMock(status_code=200, json=lambda: {"access_token": "tok"})
    with patch("requests.post", return_value=mock_resp) as mock_post:
        assert collector.login() is True
        assert collector.token == "tok"
        mock_post.assert_called_once()


def test_get_ue_movement_state():
    collector = NEFDataCollector(nef_url="http://nef")
    collector.headers = {"Authorization": "Bearer tok"}
    mock_resp = MagicMock(status_code=200, json=lambda: {"ue1": {"latitude": 1, "longitude": 2}})
    with patch("requests.get", return_value=mock_resp) as mock_get:
        state = collector.get_ue_movement_state()
        assert state["ue1"]["latitude"] == 1
        mock_get.assert_called_once()


def test_collect_training_data():
    collector = NEFDataCollector(nef_url="http://nef")
    sample_state = {"ue1": {"latitude": 0, "longitude": 0, "speed": 1.0, "Cell_id": "A"}}
    with patch.object(collector, "get_ue_movement_state", return_value=sample_state), \
         patch("time.sleep"), \
         patch("time.time", side_effect=[0, 0.1, 1.1]):
        data = collector.collect_training_data(duration=1, interval=1)
        assert len(data) == 1
        assert data[0]["ue_id"] == "ue1"
