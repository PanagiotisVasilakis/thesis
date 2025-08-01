import importlib.util
import sys
import types
from types import SimpleNamespace
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.testclient import TestClient as FastAPITestClient
from httpx import ASGITransport


class TestClient(FastAPITestClient):
    def __init__(self, *, transport: ASGITransport, **kwargs):
        super().__init__(transport.app, **kwargs)
from pydantic import BaseModel


def _setup_client(monkeypatch, user=None):
    if user is None:
        user = SimpleNamespace(id=1, is_superuser=True)

    def fake_get_db():
        yield None

    for name in list(sys.modules.keys()):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]

    app_pkg = types.ModuleType("app")
    crud_mod = types.ModuleType("app.crud")
    crud_mod.crud_mongo = SimpleNamespace()
    crud_mod.ue = SimpleNamespace()
    crud_mod.user = SimpleNamespace(
        is_superuser=lambda u: getattr(u, "is_superuser", False))
    app_pkg.crud = crud_mod

    tools_mod = types.ModuleType("app.tools")
    tools_mod.check_expiration_time = lambda expire: True
    app_pkg.tools = tools_mod

    models_mod = types.ModuleType("app.models")

    class User(BaseModel):
        id: int
        is_superuser: bool = False

    models_mod.User = User
    app_pkg.models = models_mod

    schemas_mod = types.ModuleType("app.schemas")

    class MonitoringEventSubscriptionCreate(BaseModel):
        externalId: str
        notificationDestination: str
        monitoringType: str
        maximumNumberOfReports: int
        monitorExpireTime: Optional[str] = None

    class MonitoringEventSubscription(MonitoringEventSubscriptionCreate):
        link: Optional[str] = None
        ipv4Addr: Optional[str] = None

        class Config:
            orm_mode = True

    class MonitoringEventReport(BaseModel):
        externalId: Optional[str] = None
        monitoringType: str

    class MonitoringNotification(BaseModel):
        subscription: str
        monitoringType: str

    class MonitoringEventReportReceived(BaseModel):
        ok: bool

    for name, obj in locals().items():
        if name in {
            "MonitoringEventSubscriptionCreate",
            "MonitoringEventSubscription",
            "MonitoringEventReport",
            "MonitoringNotification",
            "MonitoringEventReportReceived",
        }:
            setattr(schemas_mod, name, obj)

    app_pkg.schemas = schemas_mod

    api_mod = types.ModuleType("app.api")
    deps_mod = types.ModuleType("app.api.deps")
    deps_mod.get_db = fake_get_db
    deps_mod.get_current_active_user = lambda: user
    deps_mod.verify_with_public_key = lambda: {"sub": str(user.id)}
    api_mod.deps = deps_mod
    api_v1_pkg = types.ModuleType("app.api.api_v1")
    endpoints_pkg = types.ModuleType("app.api.api_v1.endpoints")
    utils_mod = types.ModuleType("app.api.api_v1.endpoints.utils")
    async def _noop(*a, **k):
        return None
    utils_mod.add_notifications = _noop
    utils_mod.ccf_logs = _noop
    ue_move_mod = types.ModuleType("app.api.api_v1.endpoints.ue_movement")
    ue_move_mod.retrieve_ue_state = lambda *a, **k: False
    ue_move_mod.retrieve_ue = lambda *a, **k: {}
    endpoints_pkg.utils = utils_mod
    api_v1_pkg.endpoints = endpoints_pkg
    api_mod.api_v1 = api_v1_pkg
    app_pkg.api = api_mod

    db_pkg = types.ModuleType("app.db")
    session_mod = types.ModuleType("app.db.session")
    session_mod.client = SimpleNamespace(fastapi=None)
    db_pkg.session = session_mod
    app_pkg.db = db_pkg

    sys.modules["app"] = app_pkg
    sys.modules["app.crud"] = crud_mod
    sys.modules["app.tools"] = tools_mod
    sys.modules["app.models"] = models_mod
    sys.modules["app.schemas"] = schemas_mod
    sys.modules["app.api"] = api_mod
    sys.modules["app.api.deps"] = deps_mod
    sys.modules["app.api.api_v1"] = api_v1_pkg
    sys.modules["app.api.api_v1.endpoints"] = endpoints_pkg
    sys.modules["app.api.api_v1.endpoints.utils"] = utils_mod
    sys.modules["app.api.api_v1.endpoints.ue_movement"] = ue_move_mod
    sys.modules["app.db"] = db_pkg
    sys.modules["app.db.session"] = session_mod

    endpoints_dir = Path(__file__).resolve(
    ).parents[2] / "backend" / "app" / "app" / "api" / "api_v1" / "endpoints"
    spec = importlib.util.spec_from_file_location(
        "app.api.api_v1.endpoints.monitoringevent", endpoints_dir / "monitoringevent.py"
    )
    monitoring_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(monitoring_mod)

    app_instance = FastAPI()
    app_instance.include_router(
        monitoring_mod.router, prefix="/api/v1/monitoring-event")
    client = TestClient(transport=ASGITransport(app=app_instance))
    return client, crud_mod, tools_mod


def test_read_active_subscriptions(monkeypatch):
    client, crud, tools = _setup_client(monkeypatch)

    items = [
        {"externalId": "ue1", "monitorExpireTime": "valid"},
        {"externalId": "ue2", "monitorExpireTime": "expired"},
    ]

    crud.crud_mongo.read_all = lambda db, coll, owner: items
    crud.crud_mongo.delete_by_item = lambda *a, **k: None
    tools.check_expiration_time = lambda *a, **kw: (
        kw.get("expire_time") or (a[0] if a else None)) == "valid"

    resp = client.get("/api/v1/monitoring-event/myNetapp/subscriptions")
    assert resp.status_code == 200
    assert resp.json() == [{"externalId": "ue1", "monitorExpireTime": "valid"}]


def test_create_subscription(monkeypatch):
    client, crud, tools = _setup_client(monkeypatch)

    ue_obj = SimpleNamespace(
        ip_address_v4="10.0.0.1",
        supi="supi1",
        Cell=SimpleNamespace(cell_id="A1", gNB=SimpleNamespace(gNB_id=1)),
    )
    crud.ue.get_externalId = lambda db, externalId, owner_id: ue_obj
    crud.crud_mongo.read_by_multiple_pairs = lambda *a, **k: None

    stored = {}

    def create(db, coll, data):
        stored.update(data)
        return SimpleNamespace(inserted_id="abc")

    def update_new_field(db, coll, ident, data):
        stored.update(data)

    def read_uuid(db, coll, ident):
        return dict(stored)

    crud.crud_mongo.create = create
    crud.crud_mongo.update_new_field = update_new_field
    crud.crud_mongo.read_uuid = read_uuid

    payload = {
        "externalId": "ue1@domain.com",
        "notificationDestination": "http://localhost/callback",
        "monitoringType": "LOCATION_REPORTING",
        "maximumNumberOfReports": 2,
        "monitorExpireTime": "valid",
    }

    resp = client.post(
        "/api/v1/monitoring-event/myNetapp/subscriptions", json=payload)
    assert resp.status_code == 201
    location = "http://testserver/api/v1/monitoring-event/myNetapp/subscriptions/abc"
    assert resp.headers["location"] == location

    expected = payload.copy()
    expected.update({"ipv4Addr": "10.0.0.1", "link": location})
    assert resp.json() == expected
