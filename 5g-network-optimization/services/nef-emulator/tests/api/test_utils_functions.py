from types import SimpleNamespace
from pathlib import Path
from fastapi.responses import JSONResponse
import importlib.util
import types
import sys

# Dynamically load the utils module under test
UTILS_PATH = Path(__file__).resolve().parents[2] / "backend" / "app" / "app" / "api" / "api_v1" / "endpoints" / "utils.py"
# Stub optional external dependency 'requests' before loading the module
requests_stub = sys.modules.setdefault("requests", types.ModuleType("requests"))
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
from pydantic import BaseModel

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
endpoints_pkg.paths = paths_mod
endpoints_pkg.ue_movement = ue_move_mod
api_v1_pkg.endpoints = endpoints_pkg
api_pkg.api_v1 = api_v1_pkg
app_pkg.api = api_pkg

core_pkg = types.ModuleType("app.core")
config_mod = types.ModuleType("app.core.config")
config_mod.settings = types.SimpleNamespace(CAPIF_HOST="", CAPIF_HTTPS_PORT=0)
core_pkg.config = config_mod
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
    "app.core": core_pkg,
    "app.core.config": config_mod,
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


def test_ccf_logs(monkeypatch):
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

    req = SimpleNamespace(method="POST",
                          url=SimpleNamespace(path="/monitoring/event", hostname="localhost"),
                          _body=b"{}")

    utils.ccf_logs(req, {"status_code": 200, "response": {}}, "service.json", "invoker")

    logger = DummyLogger.instances[0]
    assert logger.desc_path.endswith("service.json")
    assert logger.saved[0][0] == "invoker"
    assert len(logger.saved[0][1]) == 1


def test_add_notifications(monkeypatch):
    monkeypatch.setattr(utils, "event_notifications", [], raising=False)
    monkeypatch.setattr(utils, "counter", 0, raising=False)

    req = SimpleNamespace(method="POST",
                          url=SimpleNamespace(path="/monitoring", hostname="localhost"),
                          _body=b"{\"foo\": 1}")
    resp = JSONResponse(content={"ack": "ok"}, status_code=201)

    data = utils.add_notifications(req, resp, False)

    assert utils.event_notifications[0] == data
    assert data["isNotification"] is False
    assert data["endpoint"] == "/monitoring"
    assert data["status_code"] == 201


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
