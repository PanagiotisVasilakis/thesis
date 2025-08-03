from pydantic import BaseModel
from types import SimpleNamespace
import json
import pytest
from fastapi import Request
from pathlib import Path
from fastapi.responses import JSONResponse
import importlib.util
import types
import sys

# Dynamically load the utils module under test
UTILS_PATH = Path(__file__).resolve(
).parents[2] / "backend" / "app" / "app" / "api" / "api_v1" / "endpoints" / "utils.py"
# Stub optional external dependency 'requests' before loading the module
requests_stub = sys.modules.setdefault(
    "requests", types.ModuleType("requests"))
setattr(requests_stub, "post", lambda *a, **k: None)
# Minimal "app" package structure required by utils module
app_pkg = types.ModuleType("app")
crud_mod = types.ModuleType("app.crud")
crud_mod.gnb = types.SimpleNamespace()
crud_mod.cell = types.SimpleNamespace()
crud_mod.ue = types.SimpleNamespace()
crud_mod.path = types.SimpleNamespace()
crud_mod.points = types.SimpleNamespace()
app_pkg.crud = crud_mod

models_mod = types.ModuleType("app.models")


class User(SimpleNamespace):
    id: int = 1
    is_superuser: bool = False


models_mod.User = User

schemas_mod = types.ModuleType("app.schemas")

monitoringevent_mod = types.ModuleType("monitoringevent")


class MonitoringNotification(BaseModel):
    pass


monitoringevent_mod.MonitoringNotification = MonitoringNotification


class UserPlaneNotificationData(BaseModel):
    pass


class scenario(BaseModel):
    pass


schemas_mod.monitoringevent = monitoringevent_mod
schemas_mod.UserPlaneNotificationData = UserPlaneNotificationData
schemas_mod.scenario = scenario
api_pkg = types.ModuleType("app.api")
deps_mod = types.ModuleType("app.api.deps")
deps_mod.get_db = lambda: None
deps_mod.get_current_active_user = lambda: None
api_pkg.deps = deps_mod
api_v1_pkg = types.ModuleType("app.api.api_v1")
endpoints_pkg = types.ModuleType("app.api.api_v1.endpoints")
paths_mod = types.ModuleType("app.api.api_v1.endpoints.paths")
paths_mod.get_random_point = lambda *a, **k: {}
ue_move_mod = types.ModuleType("app.api.api_v1.endpoints.ue_movement")
ue_move_mod.retrieve_ue_state = lambda *a, **k: False
state_manager_mod = types.ModuleType("app.api.api_v1.state_manager")


class DummySM:
    def __init__(self):
        self._event_notifications = []
        self._counter = 0

    def add_notification(self, n):
        n["id"] = self._counter
        self._counter += 1
        self._event_notifications.append(n)
        return n

    def get_notifications(self, *a, **k):
        return list(self._event_notifications)

    def all_notifications(self):
        return list(self._event_notifications)


state_manager_mod.state_manager = DummySM()
endpoints_pkg.paths = paths_mod
endpoints_pkg.ue_movement = ue_move_mod
api_v1_pkg.endpoints = endpoints_pkg
api_v1_pkg.state_manager = state_manager_mod
api_pkg.api_v1 = api_v1_pkg
app_pkg.api = api_pkg

core_pkg = types.ModuleType("app.core")
config_mod = types.ModuleType("app.core.config")
config_mod.settings = types.SimpleNamespace(CAPIF_HOST="", CAPIF_HTTPS_PORT=0)
core_pkg.config = config_mod
# Provide constants expected by utils module
constants_mod = types.ModuleType("app.core.constants")
constants_mod.DEFAULT_TIMEOUT = 5
core_pkg.constants = constants_mod
app_pkg.core = core_pkg
app_pkg.models = models_mod
app_pkg.schemas = schemas_mod
for name, mod in {
    "app": app_pkg,
    "app.crud": crud_mod,
    "app.models": models_mod,
    "app.schemas": schemas_mod,
    "app.api": api_pkg,
    "app.api.deps": deps_mod,
    "app.api.api_v1": api_v1_pkg,
    "app.api.api_v1.endpoints": endpoints_pkg,
    "app.api.api_v1.endpoints.paths": paths_mod,
    "app.api.api_v1.endpoints.ue_movement": ue_move_mod,
    "app.api.api_v1.state_manager": state_manager_mod,
    "app.core": core_pkg,
    "app.core.config": config_mod,
    "app.core.constants": constants_mod,
}.items():
    sys.modules[name] = mod
# Stub optional SQLAlchemy dependency
sqlalchemy_mod = types.ModuleType("sqlalchemy")
sqlalchemy_mod.orm = types.ModuleType("sqlalchemy.orm")
sqlalchemy_mod.orm.session = types.ModuleType("sqlalchemy.orm.session")
sqlalchemy_mod.orm.session.Session = object
sys.modules.setdefault("sqlalchemy", sqlalchemy_mod)
sys.modules.setdefault("sqlalchemy.orm", sqlalchemy_mod.orm)
sys.modules.setdefault("sqlalchemy.orm.session", sqlalchemy_mod.orm.session)
spec = importlib.util.spec_from_file_location("utils", UTILS_PATH)
utils = importlib.util.module_from_spec(spec)
spec.loader.exec_module(utils)


def _make_request(data: bytes, path: str = "/cb"):
    scope = {"type": "http", "method": "POST", "path": path, "headers": [(b"content-type", b"application/json"), (b"host", b"testserver")]} 
    async def receive():
        return {"type": "http.request", "body": data, "more_body": False}
    return Request(scope, receive)


@pytest.mark.asyncio
async def test_ccf_logs(monkeypatch):
    class DummyLogger:
        class LogEntry:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)
        instances = []

        def __init__(self, *args, **kwargs):
            self.saved = []
            DummyLogger.instances.append(self)

        def get_capif_service_description(self, capif_service_api_description_json_full_path):
            self.desc_path = capif_service_api_description_json_full_path
            return {"apiId": "abc"}

        def save_log(self, api_invoker_id, log_entries):
            self.saved.append((api_invoker_id, log_entries))

    monkeypatch.setattr(utils, "CAPIFLogger", DummyLogger)

    req = _make_request(b"{}", path="/monitoring/event")

    await utils.ccf_logs(req, {"status_code": 200, "response": {}},
                         "service.json", "invoker")

    logger = DummyLogger.instances[0]
    assert logger.desc_path.endswith("service.json")
    assert logger.saved[0][0] == "invoker"
    assert len(logger.saved[0][1]) == 1


@pytest.mark.asyncio
async def test_ccf_logs_invalid(monkeypatch):
    class DummyLogger:
        class LogEntry:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)
        def __init__(self, *a, **k):
            pass
        def get_capif_service_description(self, capif_service_api_description_json_full_path):
            return {"apiId": "abc"}
        def save_log(self, api_invoker_id, log_entries):
            pass

    monkeypatch.setattr(utils, "CAPIFLogger", DummyLogger)
    req = _make_request(b"{bad", path="/monitoring/event")
    with pytest.raises(utils.HTTPException):
        await utils.ccf_logs(req, {"status_code": 200, "response": {}}, "service.json", "inv")


@pytest.mark.asyncio
async def test_add_notifications(monkeypatch):
    monkeypatch.setattr(utils.state_manager,
                        "_event_notifications", [], raising=False)
    monkeypatch.setattr(utils.state_manager, "_counter", 0, raising=False)

    req = _make_request(b"{\"foo\": 1}", path="/monitoring")
    resp = JSONResponse(content={"ack": "ok"}, status_code=201)

    data = await utils.add_notifications(req, resp, False)

    assert utils.state_manager.all_notifications()[0] == data
    assert data["isNotification"] is False
    assert data["endpoint"] == "/monitoring"
    assert data["status_code"] == 201


@pytest.mark.asyncio
async def test_add_notifications_invalid(monkeypatch):
    monkeypatch.setattr(utils.state_manager, "_event_notifications", [], raising=False)
    monkeypatch.setattr(utils.state_manager, "_counter", 0, raising=False)

    req = _make_request(b"{invalid", path="/monitoring")
    resp = JSONResponse(content={}, status_code=200)
    with pytest.raises(utils.HTTPException):
        await utils.add_notifications(req, resp, False)


def test_get_scenario(monkeypatch):
    gnb = SimpleNamespace(id=1, gNB_id="GNB1", name="g1", owner_id=1)
    cell = SimpleNamespace(id=1, cell_id="CELL1", owner_id=1, gNB_id=1,
                           latitude=0.0, longitude=0.0, radius=1)
    ue = SimpleNamespace(id=1, supi="UE1", owner_id=1, path_id=1)
    path_obj = SimpleNamespace(id=1, start_lat=0.0, start_long=0.0,
                               end_lat=1.0, end_long=1.0, description="d")
    points = [SimpleNamespace(latitude=0.0, longitude=0.0),
              SimpleNamespace(latitude=1.0, longitude=1.0)]

    monkeypatch.setattr(utils.crud.gnb, "get_multi_by_owner",
                        lambda db, owner_id, skip=0, limit=100: [gnb],
                        raising=False)
    monkeypatch.setattr(utils.crud.cell, "get_multi_by_owner",
                        lambda db, owner_id, skip=0, limit=100: [cell],
                        raising=False)
    monkeypatch.setattr(utils.crud.ue, "get_multi_by_owner",
                        lambda db, owner_id, skip=0, limit=100: [ue],
                        raising=False)
    monkeypatch.setattr(utils.crud.path, "get_multi_by_owner",
                        lambda db, owner_id, skip=0, limit=100: [path_obj],
                        raising=False)
    monkeypatch.setattr(utils.crud.points, "get_points",
                        lambda db, path_id: points,
                        raising=False)

    result = utils.get_scenario(db=None, current_user=SimpleNamespace(id=1))

    assert result["gNBs"][0]["gNB_id"] == "GNB1"
    assert result["cells"][0]["cell_id"] == "CELL1"
    assert result["UEs"][0]["supi"] == "UE1"
    assert result["paths"][0]["points"] == [{"latitude": 0.0, "longitude": 0.0},
                                            {"latitude": 1.0, "longitude": 1.0}]
    assert result["ue_path_association"] == [{"supi": "UE1", "path": 1}]
