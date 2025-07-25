import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

from test_helpers import load_module

SERVICE_ROOT = Path(__file__).resolve().parents[1]
APP_ENTRY = SERVICE_ROOT / "app.py"
COLLECT_ENTRY = SERVICE_ROOT / "collect_training_data.py"


def _load_app_package():
    """Return the ml_service.app package with seaborn stubbed."""
    sys.modules.setdefault(
        "seaborn",
        importlib.util.module_from_spec(
            importlib.util.spec_from_loader("seaborn", loader=None)
        ),
    )
    import ml_service.app as module
    return module




def test_app_entrypoint_calls_create_app(monkeypatch):
    app_pkg = _load_app_package()
    mock_create = MagicMock(return_value="instance")
    monkeypatch.setattr(app_pkg, "create_app", mock_create)
    module = load_module(APP_ENTRY, "app_entry")
    assert module.app == "instance"
    mock_create.assert_called_once()


def test_collect_training_data_main_success(monkeypatch):
    module = load_module(COLLECT_ENTRY, "collect_script")
    collector = MagicMock()
    collector.login.return_value = True
    collector.get_ue_movement_state.return_value = {"ue": {"Cell_id": "A", "latitude": 0, "longitude": 0, "speed": 1}}
    collector.collect_training_data = AsyncMock(return_value=[{"dummy": 1}])
    monkeypatch.setattr(module, "NEFDataCollector", lambda **kw: collector)
    response = MagicMock(status_code=200, json=lambda: {"metrics": {}})
    monkeypatch.setitem(sys.modules, "requests", MagicMock(post=MagicMock(return_value=response)))
    monkeypatch.setattr(sys, "argv", ["collect_training_data", "--train"])
    assert module.main() == 0
    collector.login.assert_called_once()
    collector.collect_training_data.assert_awaited_once()


def test_collect_training_data_main_failure(monkeypatch):
    module = load_module(COLLECT_ENTRY, "collect_script_fail")
    collector = MagicMock()
    collector.login.return_value = False
    monkeypatch.setattr(module, "NEFDataCollector", lambda **kw: collector)
    monkeypatch.setattr(sys, "argv", ["collect_training_data"])
    assert module.main() == 1


def test_collect_training_data_remote(monkeypatch):
    module = load_module(COLLECT_ENTRY, "collect_script_remote")
    response = MagicMock(status_code=200, json=lambda: {"samples": 3})
    mock_requests = MagicMock(post=MagicMock(return_value=response))
    monkeypatch.setitem(sys.modules, "requests", mock_requests)
    monkeypatch.setattr(sys, "argv", ["collect_training_data", "--ml-service-url", "http://ml"]) 
    assert module.main() == 0
    mock_requests.post.assert_called_once()
