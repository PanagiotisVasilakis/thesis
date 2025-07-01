import json
from unittest.mock import MagicMock
import importlib.util
import sys

try:
    import seaborn  # noqa: F401
except ImportError:  # pragma: no cover
    sys.modules["seaborn"] = importlib.util.module_from_spec(
        importlib.util.spec_from_loader("seaborn", loader=None)
    )

from ml_service.data.nef_collector import NEFDataCollector
import ml_service.data.nef_collector as nef_collector


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
    monkeypatch.setattr(nef_collector, "NEFClient", lambda *a, **k: mock_client)
    collector = NEFDataCollector(nef_url="http://nef")
    collector.data_dir = str(tmp_path)
    monkeypatch.setattr(nef_collector.time, "sleep", lambda x: None)
    times = iter([0, 0.1, 1.1])
    monkeypatch.setattr(nef_collector.time, "time", lambda: next(times))

    data = collector.collect_training_data(duration=1, interval=1)
    assert len(data) == 1
    assert data[0]["ue_id"] == "ue1"
    saved = list(tmp_path.iterdir())
    with open(saved[0]) as f:
        loaded = json.load(f)
    assert loaded == data
