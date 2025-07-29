import importlib.util
import sys
import types
from types import SimpleNamespace
from pathlib import Path
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel


def _setup_client(monkeypatch, user=None):
    if user is None:
        user = SimpleNamespace(id=1, is_superuser=True)

    def fake_get_db():
        yield None

    # Remove previously loaded app modules
    for name in list(sys.modules.keys()):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]

    app_pkg = types.ModuleType("app")

    try:
        import sqlalchemy  # pragma: no cover - optional dependency
    except ImportError:
        sqlalchemy = types.ModuleType("sqlalchemy")
        sys.modules["sqlalchemy"] = sqlalchemy
    if not hasattr(sqlalchemy, "orm"):
        sqlalchemy.orm = types.ModuleType("sqlalchemy.orm")
        sys.modules["sqlalchemy.orm"] = sqlalchemy.orm
    sqlalchemy.orm.session = types.ModuleType("sqlalchemy.orm.session")
    sqlalchemy.orm.session.Session = object
    sys.modules["sqlalchemy.orm.session"] = sqlalchemy.orm.session

    try:
        import pymongo  # pragma: no cover - optional dependency
    except ImportError:
        pymongo = types.ModuleType("pymongo")
        sys.modules["pymongo"] = pymongo
    pymongo.database = types.ModuleType("pymongo.database")
    pymongo.database.Database = object
    sys.modules["pymongo.database"] = pymongo.database

    crud_mod = types.ModuleType("app.crud")
    crud_mod.crud_mongo = SimpleNamespace()
    crud_mod.gnb = SimpleNamespace()
    crud_mod.ue = SimpleNamespace()
    crud_mod.user = SimpleNamespace(
        is_superuser=lambda u: getattr(u, "is_superuser", False))
    app_pkg.crud = crud_mod

    models_mod = types.ModuleType("app.models")

    class User(BaseModel):
        id: int
        is_superuser: bool = False

    models_mod.User = User
    app_pkg.models = models_mod

    api_mod = types.ModuleType("app.api")
    deps_mod = types.ModuleType("app.api.deps")
    deps_mod.get_db = fake_get_db
    deps_mod.get_current_active_user = lambda: user
    api_mod.deps = deps_mod
    api_v1_pkg = types.ModuleType("app.api.api_v1")
    endpoints_pkg = types.ModuleType("app.api.api_v1.endpoints")
    api_v1_pkg.endpoints = endpoints_pkg
    api_mod.api_v1 = api_v1_pkg
    app_pkg.api = api_mod

    db_pkg = types.ModuleType("app.db")
    session_mod = types.ModuleType("app.db.session")
    session_mod.client = SimpleNamespace(fastapi=None)
    db_pkg.session = session_mod
    app_pkg.db = db_pkg

    core_pkg = types.ModuleType("app.core")
    config_mod = types.ModuleType("app.core.config")

    class DummyQoSSettings:
        def retrieve_settings(self):
            return {}

    config_mod.qosSettings = DummyQoSSettings()
    core_pkg.config = config_mod
    app_pkg.core = core_pkg

    modules = {
        "app": app_pkg,
        "app.crud": crud_mod,
        "app.crud.crud_mongo": crud_mod.crud_mongo,
        "app.crud.gnb": crud_mod.gnb,
        "app.crud.ue": crud_mod.ue,
        "app.crud.user": crud_mod.user,
        "app.models": models_mod,
        "app.api": api_mod,
        "app.api.deps": deps_mod,
        "app.api.api_v1": api_v1_pkg,
        "app.api.api_v1.endpoints": endpoints_pkg,
        "app.db": db_pkg,
        "app.db.session": session_mod,
        "app.core": core_pkg,
        "app.core.config": config_mod,
    }
    for name, mod in modules.items():
        sys.modules[name] = mod

    endpoints_dir = Path(__file__).resolve(
    ).parents[2] / "backend" / "app" / "app" / "api" / "api_v1" / "endpoints"
    spec = importlib.util.spec_from_file_location(
        "qosInformation", endpoints_dir / "qosInformation.py")
    qos_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(qos_mod)

    app_instance = FastAPI()
    app_instance.include_router(qos_mod.router, prefix="/api/v1")
    client = TestClient(app_instance)
    return client, crud_mod, qos_mod


def test_qos_reference_match(monkeypatch):
    client, crud, qos_mod = _setup_client(monkeypatch)

    monkeypatch.setattr(
        qos_mod.qosSettings,
        "retrieve_settings",
        lambda: {"5qi": [{"value": 1, "type": "NonGBR"}]},
        raising=False,
    )

    with pytest.raises(HTTPException):
        qos_mod.qos_reference_match(99)

    result = qos_mod.qos_reference_match(1)
    assert result["value"] == 1


def test_read_qos_characteristics(monkeypatch):
    client, crud, qos_mod = _setup_client(monkeypatch)

    data = {"5qi": [{"value": 1}]}
    monkeypatch.setattr(qos_mod.qosSettings,
                        "retrieve_settings", lambda: data, raising=False)

    resp = client.get("/api/v1/qosCharacteristics")
    assert resp.status_code == 200
    assert resp.json() == data


def test_read_qos_profiles(monkeypatch):
    user = SimpleNamespace(id=1, is_superuser=False)
    client, crud, qos_mod = _setup_client(monkeypatch, user=user)

    gnb_obj = SimpleNamespace(gNB_id="G1", owner_id=1)
    monkeypatch.setattr(crud.gnb, "get_gNB_id", lambda db,
                        id: gnb_obj, raising=False)
    profiles = [{"value": 1}]
    monkeypatch.setattr(crud.crud_mongo, "read_all_gNB_profiles",
                        lambda db, coll, gid: profiles, raising=False)

    resp = client.get("/api/v1/qosProfiles/G1")
    assert resp.status_code == 200
    assert resp.json() == profiles


def test_read_qos_rules(monkeypatch):
    user = SimpleNamespace(id=1, is_superuser=False)
    client, crud, qos_mod = _setup_client(monkeypatch, user=user)

    ue_obj = SimpleNamespace(supi="S1", owner_id=1, ip_address_v4="10.0.0.1")
    monkeypatch.setattr(crud.ue, "get_supi", lambda db,
                        supi: ue_obj, raising=False)
    rules = {"rule": "a"}
    monkeypatch.setattr(crud.crud_mongo, "read", lambda db,
                        coll, key, value: rules, raising=False)

    resp = client.get("/api/v1/qosRules/S1")
    assert resp.status_code == 200
    assert resp.json() == rules


def test_read_qos_rules_not_found(monkeypatch):
    user = SimpleNamespace(id=1, is_superuser=False)
    client, crud, qos_mod = _setup_client(monkeypatch, user=user)

    ue_obj = SimpleNamespace(supi="S1", owner_id=1, ip_address_v4="10.0.0.1")
    monkeypatch.setattr(crud.ue, "get_supi", lambda db,
                        supi: ue_obj, raising=False)
    monkeypatch.setattr(crud.crud_mongo, "read", lambda db,
                        coll, key, value: None, raising=False)

    resp = client.get("/api/v1/qosRules/S1")
    assert resp.status_code == 404
