from types import SimpleNamespace, ModuleType
import importlib
import sys
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    env = {
        "SERVER_NAME": "test",
        "SERVER_HOST": "localhost",
        "POSTGRES_SERVER": "localhost",
        "POSTGRES_USER": "user",
        "POSTGRES_PASSWORD": "pass",
        "POSTGRES_DB": "db",
        "SQLALCHEMY_DATABASE_URI": "postgresql://user:pass@localhost/db",
        "MONGO_CLIENT": "mongodb://localhost",
        "CAPIF_HOST": "localhost",
        "CAPIF_HTTP_PORT": "8080",
        "CAPIF_HTTPS_PORT": "8443",
        "FIRST_SUPERUSER": "admin@example.com",
        "FIRST_SUPERUSER_PASSWORD": "pass",
        "USE_PUBLIC_KEY_VERIFICATION": "0",
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    # Stub out modules that require heavy dependencies
    fake_session = ModuleType("app.db.session")
    fake_session.SessionLocal = lambda: None
    fake_session.client = None
    sys.modules["app.db.session"] = fake_session

    stub_emails = ModuleType("emails")
    stub_emails.Message = object
    sys.modules["emails"] = stub_emails
    tmpl_mod = ModuleType("emails.template")
    tmpl_mod.JinjaTemplate = lambda x: x
    sys.modules["emails.template"] = tmpl_mod

    for mod in ["app", "app.network", "app.network.state_manager", "app.crud"]:
        sys.modules.pop(mod, None)

    ue_mod = importlib.import_module("app.api.api_v1.endpoints.UE")
    from app import crud
    from app.api import deps

    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(ue_mod.router, prefix="/api/v1/UEs")

    def _get_db():
        yield None
    app.dependency_overrides[deps.get_db] = _get_db
    app.dependency_overrides[deps.get_current_active_user] = lambda: SimpleNamespace(id=1, is_superuser=True)

    # Basic stubs for unrelated CRUD calls
    monkeypatch.setattr(crud.cell, "get_Cell_id", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(crud.cell, "get_by_gNB_id", lambda *a, **k: [], raising=False)
    monkeypatch.setattr(crud.gnb, "get_gNB_id", lambda *a, **k: None, raising=False)

    client = TestClient(app)
    yield client
    app.dependency_overrides = {}


def _dummy_ue():
    cell = SimpleNamespace(cell_id="AAAAA1001", gNB_id=1)
    return SimpleNamespace(
        id=1,
        supi="202010000000001",
        name="ue1",
        description=None,
        ip_address_v4="10.0.0.1",
        ip_address_v6="2001:db8::1",
        mac_address="22-00-00-00-00-01",
        dnn="dnn",
        mcc=202,
        mnc=1,
        external_identifier="ue1@domain.com",
        speed="LOW",
        latitude=1.0,
        longitude=2.0,
        path_id=0,
        Cell_id=1,
        Cell=cell,
        owner_id=1,
    )


def test_list_ues(client, monkeypatch):
    from app import crud
    monkeypatch.setattr(crud.ue, "get_multi", lambda db, skip=0, limit=100: [_dummy_ue()])
    resp = client.get("/api/v1/UEs")
    assert resp.status_code == 200
    data = resp.json()
    assert data[0]["supi"] == "202010000000001"
    assert data[0]["cell_id_hex"] == "AAAAA1001"
    assert data[0]["gNB_id"] == 1


def test_create_ue_duplicate(client, monkeypatch):
    from app import crud
    monkeypatch.setattr(crud.ue, "get_supi", lambda *a, **k: _dummy_ue())
    for name in ["get_ipv4", "get_ipv6", "get_mac", "get_externalId"]:
        monkeypatch.setattr(crud.ue, name, lambda *a, **k: None)
    monkeypatch.setattr(crud.ue, "create_with_owner", lambda *a, **k: _dummy_ue())

    payload = {
        "supi": "202010000000001",
        "name": "ue1",
        "description": "desc",
        "ip_address_v4": "10.0.0.1",
        "ip_address_v6": "2001:db8::1",
        "mac_address": "22-00-00-00-00-01",
        "dnn": "dnn",
        "mcc": 202,
        "mnc": 1,
        "external_identifier": "ue1@domain.com",
        "speed": "LOW",
    }
    resp = client.post("/api/v1/UEs", json=payload)
    assert resp.status_code == 409


def test_create_update_delete_ue(client, monkeypatch):
    from app import crud
    monkeypatch.setattr(crud.ue, "get_supi", lambda *a, **k: None)
    for name in ["get_ipv4", "get_ipv6", "get_mac", "get_externalId"]:
        monkeypatch.setattr(crud.ue, name, lambda *a, **k: None)
    monkeypatch.setattr(crud.ue, "create_with_owner", lambda *a, **k: _dummy_ue())

    payload = {
        "supi": "202010000000002",
        "name": "ue2",
        "description": "desc",
        "ip_address_v4": "10.0.0.2",
        "ip_address_v6": "2001:db8::2",
        "mac_address": "22-00-00-00-00-02",
        "dnn": "dnn",
        "mcc": 202,
        "mnc": 1,
        "external_identifier": "ue2@domain.com",
        "speed": "LOW",
    }
    resp = client.post("/api/v1/UEs", json=payload)
    assert resp.status_code == 200
    assert resp.json()["supi"] == "202010000000002"

    created = _dummy_ue()
    created.supi = payload["supi"]
    monkeypatch.setattr(crud.ue, "get_supi", lambda *a, **k: created)
    monkeypatch.setattr(crud.ue, "update", lambda *a, **k: SimpleNamespace(path_id=0))

    update_payload = payload.copy()
    update_payload["ip_address_v4"] = "10.0.0.22"
    resp = client.put(f"/api/v1/UEs/{payload['supi']}", json=update_payload)
    assert resp.status_code == 200
    assert resp.json()["ip_address_v4"] == "10.0.0.22"

    monkeypatch.setattr(crud.ue, "remove_supi", lambda *a, **k: created)
    monkeypatch.setattr(crud.ue, "get_supi", lambda *a, **k: created)
    import app.api.api_v1.endpoints.UE as ue_endpoints
    monkeypatch.setattr(ue_endpoints, "retrieve_ue_state", lambda supi, uid: False)

    resp = client.delete(f"/api/v1/UEs/{payload['supi']}")
    assert resp.status_code == 200
    assert resp.json()["supi"] == payload["supi"]
