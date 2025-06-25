import sys
import types
from types import SimpleNamespace
from pathlib import Path as PathLib
import importlib.util

try:
    import sqlalchemy
except ImportError:
    sqlalchemy = types.ModuleType("sqlalchemy")
    sys.modules["sqlalchemy"] = sqlalchemy
    sqlalchemy.orm = types.ModuleType("sqlalchemy.orm")
    sqlalchemy.orm.Session = object
    sys.modules["sqlalchemy.orm"] = sqlalchemy.orm
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel
from typing import List, Optional


def _setup_client(monkeypatch, user=None):
    if user is None:
        user = SimpleNamespace(id=1, is_superuser=True)

    def fake_get_db():
        yield None

    app_pkg = types.ModuleType("app")
    app_pkg.__path__ = []
    crud_mod = types.ModuleType("app.crud")
    crud_mod.path = SimpleNamespace()
    crud_mod.points = SimpleNamespace()
    crud_mod.user = SimpleNamespace(is_superuser=lambda u: u.is_superuser)

    models_mod = types.ModuleType("app.models")

    class User(BaseModel):
        id: int = 1
        is_superuser: bool = False

    models_mod.User = User

    schemas_mod = types.ModuleType("app.schemas")

    class Point(BaseModel):
        latitude: float
        longitude: float

    class PathBase(BaseModel):
        description: Optional[str] = None
        start_point: Optional[Point] = None
        end_point: Optional[Point] = None
        color: Optional[str] = None

    class PathCreate(PathBase):
        points: Optional[List[Point]] = None

    class PathUpdate(PathBase):
        points: Optional[List[Point]] = None

    class PathInDBBase(PathBase):
        id: int

        class Config:
            orm_mode = True

    class Paths(PathInDBBase):
        pass

    class Path(PathInDBBase):
        points: Optional[List[Point]] = None

    for name_, obj in locals().items():
        if name_ in {"Point", "PathBase", "PathCreate", "PathUpdate", "PathInDBBase", "Paths", "Path"}:
            setattr(schemas_mod, name_, obj)

    api_pkg = types.ModuleType("app.api")
    deps_mod = types.ModuleType("app.api.deps")
    deps_mod.get_db = fake_get_db
    deps_mod.get_current_active_user = lambda: user
    api_pkg.deps = deps_mod
    api_v1_pkg = types.ModuleType("app.api.api_v1")
    endpoints_pkg = types.ModuleType("app.api.api_v1.endpoints")
    api_v1_pkg.endpoints = endpoints_pkg
    api_pkg.api_v1 = api_v1_pkg

    app_pkg.crud = crud_mod
    app_pkg.api = api_pkg
    app_pkg.models = models_mod
    app_pkg.schemas = schemas_mod

    monkeypatch.setitem(sys.modules, "app", app_pkg)
    monkeypatch.setitem(sys.modules, "app.crud", crud_mod)
    monkeypatch.setitem(sys.modules, "app.api", api_pkg)
    monkeypatch.setitem(sys.modules, "app.api.deps", deps_mod)
    monkeypatch.setitem(sys.modules, "app.api.api_v1", api_v1_pkg)
    monkeypatch.setitem(sys.modules, "app.api.api_v1.endpoints", endpoints_pkg)
    monkeypatch.setitem(sys.modules, "app.models", models_mod)
    monkeypatch.setitem(sys.modules, "app.schemas", schemas_mod)

    endpoints_dir = PathLib(__file__).resolve().parents[2] / "backend" / "app" / "app" / "api" / "api_v1" / "endpoints"
    spec = importlib.util.spec_from_file_location("paths", endpoints_dir / "paths.py")
    paths_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(paths_mod)

    app_instance = FastAPI()
    app_instance.include_router(paths_mod.router, prefix="/api/v1/paths")

    client = TestClient(app_instance)
    return client, crud_mod, paths_mod


def _dummy_path(owner_id=1):
    return SimpleNamespace(
        id=1,
        description="p1",
        start_lat=0.0,
        start_long=0.0,
        end_lat=1.0,
        end_long=1.0,
        color="blue",
        owner_id=owner_id,
    )


def test_get_random_point(monkeypatch):
    client, crud, paths_mod = _setup_client(monkeypatch)
    points = [SimpleNamespace(latitude=0.0, longitude=0.0), SimpleNamespace(latitude=1.0, longitude=1.0)]
    monkeypatch.setattr(crud.points, "get_points", lambda db, path_id: points, raising=False)
    monkeypatch.setattr(paths_mod.random, "randrange", lambda a, b: 1)
    pt = paths_mod.get_random_point(db=None, path_id=1)
    assert pt == {"latitude": 1.0, "longitude": 1.0}


def test_read_paths(monkeypatch):
    client, crud, _ = _setup_client(monkeypatch)
    monkeypatch.setattr(crud.path, "get_multi", lambda db, skip=0, limit=100: [_dummy_path()], raising=False)
    resp = client.get("/api/v1/paths")
    assert resp.status_code == 200
    data = resp.json()
    assert data[0]["description"] == "p1"
    assert data[0]["start_point"]["latitude"] == 0.0


def test_create_path(monkeypatch):
    client, crud, _ = _setup_client(monkeypatch)
    monkeypatch.setattr(crud.path, "get_description", lambda db, description: None, raising=False)
    monkeypatch.setattr(crud.path, "create_with_owner", lambda db, obj_in, owner_id: _dummy_path(), raising=False)
    monkeypatch.setattr(crud.points, "create", lambda db, obj_in, path_id: None, raising=False)
    payload = {"description": "p1", "start_point": {"latitude": 0.0, "longitude": 0.0}, "end_point": {"latitude": 1.0, "longitude": 1.0}, "color": "blue", "points": []}
    resp = client.post("/api/v1/paths", json=payload)
    assert resp.status_code == 200
    assert resp.json()["description"] == "p1"


def test_update_path(monkeypatch):
    client, crud, _ = _setup_client(monkeypatch)
    original = _dummy_path()
    monkeypatch.setattr(crud.path, "get", lambda db, id: original, raising=False)

    def fake_update(db, db_obj, obj_in):
        if isinstance(obj_in, dict):
            db_obj.description = obj_in["description"]
        else:
            db_obj.description = obj_in.description
        return db_obj
    monkeypatch.setattr(crud.path, "update", fake_update, raising=False)

    payload = {"description": "new", "start_point": {"latitude": 0.0, "longitude": 0.0}, "end_point": {"latitude": 1.0, "longitude": 1.0}, "color": "blue", "points": []}
    resp = client.put("/api/v1/paths/1", json=payload)
    assert resp.status_code == 200
    assert resp.json()["description"] == "new"


def test_read_path(monkeypatch):
    client, crud, _ = _setup_client(monkeypatch)
    monkeypatch.setattr(crud.path, "get", lambda db, id: _dummy_path(), raising=False)
    monkeypatch.setattr(crud.points, "get_points", lambda db, path_id: [SimpleNamespace(latitude=0.0, longitude=0.0)], raising=False)
    resp = client.get("/api/v1/paths/1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["points"][0]["latitude"] == 0.0
