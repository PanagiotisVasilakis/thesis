import importlib.util
from pathlib import Path
import json
from unittest.mock import MagicMock
import sys

SERVICE_ROOT = Path(__file__).resolve().parents[1]
spec_app = importlib.util.spec_from_file_location(
    "app", SERVICE_ROOT / "app" / "__init__.py", submodule_search_locations=[str(SERVICE_ROOT / "app")]
)
app_module = importlib.util.module_from_spec(spec_app)
sys.modules["app"] = app_module
sys.modules.setdefault(
    "seaborn",
    importlib.util.module_from_spec(importlib.util.spec_from_loader("seaborn", loader=None)),
)
spec_app.loader.exec_module(app_module)

NEF_COLLECTOR_PATH = SERVICE_ROOT / "app" / "data" / "nef_collector.py"
spec = importlib.util.spec_from_file_location("nef_collector", NEF_COLLECTOR_PATH)
nef_collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nef_collector)
NEFDataCollector = nef_collector.NEFDataCollector


def test_login(monkeypatch):
    mock_client = MagicMock()
    mock_client.login.return_value = True
    mock_client.token = "tok"
    mock_client.get_headers.return_value = {"Authorization": "Bearer tok"}
    monkeypatch.setattr(nef_collector, "NEFClient", lambda *a, **k: mock_client)
    collector = NEFDataCollector(nef_url="http://nef", username="u", password="p")
    assert collector.login() is True
    assert collector.token == "tok"
    assert collector.headers["Authorization"] == "Bearer tok"


def test_get_ue_movement_state(monkeypatch):
    collector = NEFDataCollector(nef_url="http://nef")
    mock_client = MagicMock(get_ue_movement_state=lambda: {"ue1": {"latitude": 1}})
    collector.client = mock_client
    state = collector.get_ue_movement_state()
    assert state == {"ue1": {"latitude": 1}}


def test_collect_training_data(tmp_path, monkeypatch):
    collector = NEFDataCollector(nef_url="http://nef")
    collector.data_dir = str(tmp_path)

    sample_state = {"ue1": {"latitude": 0, "longitude": 0, "speed": 1.0, "Cell_id": "A"}}
    mock_client = MagicMock(get_ue_movement_state=lambda: sample_state)
    collector.client = mock_client
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
