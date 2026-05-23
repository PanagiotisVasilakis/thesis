import logging
from pathlib import Path
import types
import sys

UE_MOVEMENT_PATH = (
    Path(__file__).resolve().parents[1]
    / "backend/app/app/api/api_v1/endpoints/ue_movement.py"
)

with open(UE_MOVEMENT_PATH) as f:
    lines = [next(f) for _ in range(22)]
SOURCE = ''.join(lines)


def load_helper(monkeypatch):
    monkeypatch.setenv("TESTING", "1")
    app_pkg = types.ModuleType("app")
    app_pkg.core = types.ModuleType("app.core")
    app_pkg.core.env_utils = types.ModuleType("app.core.env_utils")
    app_pkg.core.env_utils.parse_env_float = lambda *a, **k: a[1] if len(a) > 1 else 1.0
    app_pkg.crud = types.ModuleType("app.crud")
    app_pkg.crud.crud_mongo = types.ModuleType("crud_mongo")
    app_pkg.tools = types.ModuleType("app.tools")
    app_pkg.tools.distance = types.ModuleType("app.tools.distance")
    app_pkg.tools.distance.check_distance = lambda *a, **k: None
    app_pkg.tools.qos_callback = types.ModuleType("app.tools.qos_callback")
    app_pkg.models = types.ModuleType("app.models")
    schemas_mod = types.ModuleType("app.schemas")

    class Msg:
        ...
    schemas_mod.Msg = Msg
    app_pkg.api = types.ModuleType("app.api")
    app_pkg.api.deps = types.ModuleType("app.api.deps")
    websocket_auth_mod = types.ModuleType("app.api.websocket_auth")
    websocket_auth_mod.require_websocket_user = lambda *a, **k: True
    api_v1_pkg = types.ModuleType("app.api.api_v1")
    state_mod = types.ModuleType("app.api.api_v1.state_manager")

    class DummySM:
        def __init__(self):
            self.count = 0

        def increment_timer_error(self):
            self.count += 1
            return self.count

        def get_timer_error_counter(self):
            return self.count

    state_mod.state_manager = DummySM()
    api_v1_pkg.state_manager = state_mod
    db_pkg = types.ModuleType("app.db")
    session_mod = types.ModuleType("app.db.session")
    session_mod.SessionLocal = object
    session_mod.client = object
    db_pkg.session = session_mod
    app_pkg.db = db_pkg

    modules = {
        "app": app_pkg,
        "app.core": app_pkg.core,
        "app.core.env_utils": app_pkg.core.env_utils,
        "app.crud": app_pkg.crud,
        "app.tools": app_pkg.tools,
        "app.tools.distance": app_pkg.tools.distance,
        "app.tools.qos_callback": app_pkg.tools.qos_callback,
        "app.models": app_pkg.models,
        "app.api": app_pkg.api,
        "app.api.deps": app_pkg.api.deps,
        "app.api.websocket_auth": websocket_auth_mod,
        "app.api.api_v1": api_v1_pkg,
        "app.api.api_v1.state_manager": state_mod,
        "app.schemas": schemas_mod,
        "app.db": db_pkg,
        "app.db.session": session_mod,
    }

    for name, mod in modules.items():
        monkeypatch.setitem(sys.modules, name, mod)

    ue_module = types.ModuleType("ue_partial")
    exec(SOURCE, ue_module.__dict__)
    return ue_module


def test_log_timer_exception_increments_counter_and_logs(caplog, monkeypatch):
    ue_module = load_helper(monkeypatch)
    caplog.set_level(logging.WARNING)
    original = ue_module.state_manager.get_timer_error_counter()
    ue_module.log_timer_exception(Exception("boom"))
    assert ue_module.state_manager.get_timer_error_counter() == original + 1
    assert any("Timer error" in rec.getMessage() for rec in caplog.records)
