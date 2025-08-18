import json
from unittest.mock import MagicMock

from ml_service.app.data import nef_collector
from ml_service.app.data.nef_collector import NEFDataCollector


def test_login_success(monkeypatch):
    mock_client = MagicMock()
    mock_client.login.return_value = True
    mock_client.token = "tok"
    mock_client.get_headers.return_value = {"Authorization": "Bearer tok"}
    monkeypatch.setattr(nef_collector, "NEFClient",
                        lambda *a, **k: mock_client)
    collector = NEFDataCollector(
        nef_url="http://nef", username="u", password="p")
    assert collector.login() is True
    assert collector.client.token == "tok"
    assert collector.client.get_headers()["Authorization"] == "Bearer tok"


def test_collect_training_data(monkeypatch, tmp_path):
    sample_state = {"ue1": {"latitude": 0,
                            "longitude": 0, "speed": 1.0, "Cell_id": "A"}}
    mock_client = MagicMock()
    # Simulate available NEF service
    mock_client.get_status.return_value = type("Resp", (), {"status_code": 200})()
    mock_client.get_ue_movement_state.return_value = sample_state
    mock_client.get_feature_vector.return_value = {
        "neighbor_rsrp_dbm": {"A": -70},
        "neighbor_sinrs": {"A": 8},
        "neighbor_rsrqs": {"A": -11},
    }
    monkeypatch.setattr(nef_collector, "NEFClient",
                        lambda *a, **k: mock_client)
    collector = NEFDataCollector(nef_url="http://nef")
    collector.data_dir = str(tmp_path)
    monkeypatch.setattr(nef_collector.time, "sleep", lambda x: None)
    # Provide a deterministic but sufficiently long sequence of timestamps for
    # all internal time.time() calls executed during collection. Most calls use
    # the same value (0.2) so that derived metrics like time_since_handover
    # evaluate to zero. The final value (>1.0) ensures the loop terminates.
    import itertools
    # Yield 0 and 0.1 for start/end calculation, a small number of 0.2 values
    # during the first collection iteration, then 1.1 for all subsequent calls to
    # terminate the loop.
    times = itertools.chain([0, 0.1], [0.2] * 5, [1.1], itertools.repeat(1.1))
    monkeypatch.setattr(nef_collector.time, "time", lambda: next(times))

    import asyncio
    data = asyncio.run(collector.collect_training_data(duration=1, interval=1))
    assert len(data) == 1
    assert data[0]["ue_id"] == "ue1"
    assert data[0]["altitude"] is None
    assert data[0]["rf_metrics"] == {"A": {"rsrp": -70, "sinr": 8, "rsrq": -11}}
    assert data[0]["time_since_handover"] == 0.0
    saved = list(tmp_path.iterdir())
    with open(saved[0]) as f:
        loaded = json.load(f)
    assert loaded == data
