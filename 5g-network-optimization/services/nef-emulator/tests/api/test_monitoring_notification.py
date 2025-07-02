import importlib.util
import sys
import types
from types import SimpleNamespace
from pathlib import Path

import pytest
from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel


def _setup_module(monkeypatch, user=None):
    if user is None:
        user = SimpleNamespace(id=1, is_superuser=True)

    for name in list(sys.modules.keys()):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]

    app_pkg = types.ModuleType("app")
    crud_mod = types.ModuleType("app.crud")
    crud_mod.crud_mongo = SimpleNamespace()
    crud_mod.user = SimpleNamespace()
    crud_mod.ue = SimpleNamespace()
    app_pkg.crud = crud_mod

    models_mod = types.ModuleType("app.models")

    class User(BaseModel):
        id: int
        is_superuser: bool = False

    models_mod.User = User
    app_pkg.models = models_mod

    schemas_mod = types.ModuleType("app.schemas")

    class MonitoringEventSubscriptionCreate(BaseModel):
        externalId: str = "ue"
        notificationDestination: str = "http://cb"
        monitoringType: str = "LOCATION_REPORTING"
        maximumNumberOfReports: int = 1

    class MonitoringEventSubscription(MonitoringEventSubscriptionCreate):
        link: str | None = None
        ipv4Addr: str | None = None

        class Config:
            orm_mode = True

    class MonitoringEventReport(BaseModel):
        externalId: str | None = None
        monitoringType: str

    class MonitoringNotification(BaseModel):
        subscription: str
        monitoringType: str

    class MonitoringEventReportReceived(BaseModel):
        ok: bool

    schemas_mod.MonitoringEventSubscriptionCreate = MonitoringEventSubscriptionCreate
    schemas_mod.MonitoringEventSubscription = MonitoringEventSubscription
    schemas_mod.MonitoringEventReport = MonitoringEventReport
    schemas_mod.MonitoringNotification = MonitoringNotification
    schemas_mod.MonitoringEventReportReceived = MonitoringEventReportReceived
    app_pkg.schemas = schemas_mod

    tools_mod = types.ModuleType("app.tools")
    tools_mod.check_expiration_time = lambda expire: True
    app_pkg.tools = tools_mod

    api_mod = types.ModuleType("app.api")
    deps_mod = types.ModuleType("app.api.deps")
    deps_mod.get_current_active_user = lambda: user
    deps_mod.verify_with_public_key = lambda: {"sub": str(user.id)}
    def fake_get_db():
        yield None
    deps_mod.get_db = fake_get_db
    api_mod.deps = deps_mod
    api_v1_pkg = types.ModuleType("app.api.api_v1")
    endpoints_pkg = types.ModuleType("app.api.api_v1.endpoints")
    utils_mod = types.ModuleType("app.api.api_v1.endpoints.utils")
    utils_mod.add_notifications = lambda *a, **k: None
    utils_mod.ccf_logs = lambda *a, **k: None
    ue_move_mod = types.ModuleType("app.api.api_v1.endpoints.ue_movement")
    ue_move_mod.retrieve_ue_state = lambda *a, **k: False
    ue_move_mod.retrieve_ue = lambda *a, **k: {}
    endpoints_pkg.utils = utils_mod
    endpoints_pkg.ue_movement = ue_move_mod
    api_v1_pkg.endpoints = endpoints_pkg
    api_mod.api_v1 = api_v1_pkg
    app_pkg.api = api_mod

    db_pkg = types.ModuleType("app.db")
    session_mod = types.ModuleType("app.db.session")
    session_mod.client = SimpleNamespace(fastapi=None)
    db_pkg.session = session_mod
    app_pkg.db = db_pkg

    sys.modules.update({
        "app": app_pkg,
        "app.crud": crud_mod,
        "app.models": models_mod,
        "app.schemas": schemas_mod,
        "app.api": api_mod,
        "app.api.deps": deps_mod,
        "app.api.api_v1": api_v1_pkg,
        "app.api.api_v1.endpoints": endpoints_pkg,
        "app.api.api_v1.endpoints.utils": utils_mod,
        "app.api.api_v1.endpoints.ue_movement": ue_move_mod,
        "app.tools": tools_mod,
        "app.db": db_pkg,
        "app.db.session": session_mod,
    })

    endpoints_dir = Path(__file__).resolve().parents[2] / "backend" / "app" / "app" / "api" / "api_v1" / "endpoints"
    spec = importlib.util.spec_from_file_location(
        "app.api.api_v1.endpoints.monitoringevent", endpoints_dir / "monitoringevent.py"
    )
    monitoring_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(monitoring_mod)
    return monitoring_mod, crud_mod, utils_mod


def _make_request():
    scope = {"type": "http", "method": "POST", "path": "/cb", "headers": []}
    req = Request(scope)
    req._body = b"{}"
    return req


def test_monitoring_notification_success(monkeypatch):
    mod, crud, utils = _setup_module(monkeypatch)
    stored = {}
    crud.crud_mongo.create = lambda db, coll, data: stored.update(data)
    utils.add_notifications = lambda *a, **k: None

    body = mod.schemas.MonitoringNotification(subscription="sub", monitoringType="LOCATION_REPORTING")
    resp: JSONResponse = mod.monitoring_notification(body, http_request=_make_request())
    assert resp.status_code == 200
    assert resp.body == b'{"ok":true}'
    assert stored == {"subscription": "sub", "monitoringType": "LOCATION_REPORTING"}


def test_monitoring_notification_error(monkeypatch):
    mod, crud, utils = _setup_module(monkeypatch)

    def raise_error(db, coll, data):
        raise Exception("db fail")

    crud.crud_mongo.create = raise_error
    utils.add_notifications = lambda *a, **k: None

    body = mod.schemas.MonitoringNotification(subscription="sub", monitoringType="LOCATION_REPORTING")
    with pytest.raises(mod.HTTPException) as exc:
        mod.monitoring_notification(body, http_request=_make_request())
    assert exc.value.status_code == 400
