import types
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient



def _setup_client(monkeypatch, user=None):
    if user is None:
        user = SimpleNamespace(id=1, is_superuser=False)

    def fake_get_db():
        yield None

    import sys
    import types
    from fastapi import FastAPI

    for name in list(sys.modules.keys()):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]

    app_pkg = types.ModuleType("app")
    crud_mod = types.ModuleType("app.crud")
    crud_mod.gnb = types.SimpleNamespace()
    crud_mod.cell = types.SimpleNamespace()
    crud_mod.ue = types.SimpleNamespace()
    crud_mod.user = types.SimpleNamespace(is_superuser=lambda u: u.is_superuser)

    models_mod = types.ModuleType("app.models")
    from pydantic import BaseModel

    class User(BaseModel):
        id: int = 1
        is_superuser: bool = False

    models_mod.User = User

    schemas_mod = types.ModuleType("app.schemas")

    class gNB(BaseModel):
        gNB_id: str
        name: str | None = None
        description: str | None = None
        location: str | None = None
        id: int | None = None
        owner_id: int | None = None

    class gNBCreate(gNB):
        pass

    class gNBUpdate(gNB):
        pass

    class Cell(BaseModel):
        cell_id: str
        id: int | None = None
        owner_id: int | None = None
        gNB_id: int | None = None
        latitude: float = 0.0
        longitude: float = 0.0
        radius: float = 0.0

    class CellCreate(Cell):
        pass

    class CellUpdate(Cell):
        pass

    for name, obj in locals().items():
        if name in {"gNB", "gNBCreate", "gNBUpdate", "Cell", "CellCreate", "CellUpdate"}:
            setattr(schemas_mod, name, obj)

    api_mod = types.ModuleType("app.api")
    deps_mod = types.ModuleType("app.api.deps")
    deps_mod.get_db = fake_get_db
    deps_mod.get_current_active_user = lambda: user
    api_mod.deps = deps_mod
    api_v1_pkg = types.ModuleType("app.api.api_v1")
    endpoints_pkg = types.ModuleType("app.api.api_v1.endpoints")
    utils_mod = types.ModuleType("app.api.api_v1.endpoints.utils")
    utils_mod.retrieve_ue_state = lambda supi, owner_id: False
    endpoints_pkg.utils = utils_mod
    api_v1_pkg.endpoints = endpoints_pkg
    api_mod.api_v1 = api_v1_pkg
    app_pkg.crud = crud_mod
    app_pkg.api = api_mod
    app_pkg.models = models_mod
    app_pkg.schemas = schemas_mod
    sys.modules["app"] = app_pkg
    sys.modules["app.crud"] = crud_mod
    sys.modules["app.api"] = api_mod
    sys.modules["app.api.deps"] = deps_mod
    sys.modules["app.api.api_v1"] = api_v1_pkg
    sys.modules["app.api.api_v1.endpoints"] = endpoints_pkg
    sys.modules["app.api.api_v1.endpoints.utils"] = utils_mod
    sys.modules["app.models"] = models_mod
    sys.modules["app.schemas"] = schemas_mod

    import importlib.util
    from pathlib import Path

    endpoints_dir = Path(__file__).resolve().parents[2] / "backend" / "app" / "app" / "api" / "api_v1" / "endpoints"

    gnb_spec = importlib.util.spec_from_file_location("gNB", endpoints_dir / "gNB.py")
    gnb_mod = importlib.util.module_from_spec(gnb_spec)
    gnb_spec.loader.exec_module(gnb_mod)

    cell_spec = importlib.util.spec_from_file_location("Cell", endpoints_dir / "Cell.py")
    cell_mod = importlib.util.module_from_spec(cell_spec)
    cell_spec.loader.exec_module(cell_mod)

    gnb_router = gnb_mod.router
    cell_router = cell_mod.router

    app_instance = FastAPI()
    app_instance.include_router(gnb_router, prefix="/api/v1/gNBs")
    app_instance.include_router(cell_router, prefix="/api/v1/Cells")

    client = TestClient(app_instance)
    return client, crud_mod


def test_get_gnbs(monkeypatch):
    client, crud = _setup_client(monkeypatch)

    gnb_obj = {"id": 1, "gNB_id": "AAAAAA", "owner_id": 1, "name": "n"}
    crud.gnb.get_multi_by_owner = lambda db, owner_id, skip=0, limit=100: [gnb_obj]

    resp = client.get("/api/v1/gNBs")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list) and data[0]["gNB_id"] == "AAAAAA"


def test_create_gnb_duplicate(monkeypatch):
    client, crud = _setup_client(monkeypatch)

    crud.gnb.get_gNB_id = lambda db, id: object()
    resp = client.post("/api/v1/gNBs", json={"gNB_id": "AAAAAA", "name": "n"})
    assert resp.status_code == 409


def test_update_gnb_not_owner(monkeypatch):
    user = SimpleNamespace(id=1, is_superuser=False)
    client, crud = _setup_client(monkeypatch, user=user)

    gnb_obj = SimpleNamespace(id=1, gNB_id="AAAAAA", owner_id=2, name="n")
    crud.gnb.get_gNB_id = lambda db, id: gnb_obj

    resp = client.put("/api/v1/gNBs/AAAAAA", json={"gNB_id": "AAAAAA", "name": "n"})
    assert resp.status_code == 400


def test_update_gnb_as_owner(monkeypatch):
    user = SimpleNamespace(id=1, is_superuser=False)
    client, crud = _setup_client(monkeypatch, user=user)

    gnb_obj = SimpleNamespace(id=1, gNB_id="AAAAAA", owner_id=1, name="old_name")
    crud.gnb.get_gNB_id = lambda db, id: gnb_obj

    # Simulate successful update
    def fake_update(db, db_obj, obj_in):
        if isinstance(obj_in, dict):
            name = obj_in["name"]
        else:
            name = obj_in.name
        db_obj.name = name
        return {"id": db_obj.id, "gNB_id": db_obj.gNB_id, "owner_id": db_obj.owner_id, "name": db_obj.name}
    crud.gnb.update = fake_update

    resp = client.put("/api/v1/gNBs/AAAAAA", json={"gNB_id": "AAAAAA", "name": "new_name"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "new_name"


def test_update_gnb_as_superuser(monkeypatch):
    user = SimpleNamespace(id=99, is_superuser=True)
    client, crud = _setup_client(monkeypatch, user=user)

    gnb_obj = SimpleNamespace(id=1, gNB_id="AAAAAA", owner_id=2, name="old_name")
    crud.gnb.get_gNB_id = lambda db, id: gnb_obj

    # Simulate successful update
    def fake_update(db, db_obj, obj_in):
        if isinstance(obj_in, dict):
            name = obj_in["name"]
        else:
            name = obj_in.name
        db_obj.name = name
        return {"id": db_obj.id, "gNB_id": db_obj.gNB_id, "owner_id": db_obj.owner_id, "name": db_obj.name}
    crud.gnb.update = fake_update

    resp = client.put("/api/v1/gNBs/AAAAAA", json={"gNB_id": "AAAAAA", "name": "superuser_update"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "superuser_update"


def test_get_cells(monkeypatch):
    client, crud = _setup_client(monkeypatch)

    cell_obj = {
        "id": 1,
        "cell_id": "AAAAAAA01",
        "owner_id": 1,
        "gNB_id": 1,
        "latitude": 0.0,
        "longitude": 0.0,
        "radius": 1.0,
        "name": "c",
    }
    crud.cell.get_multi_by_owner = lambda db, owner_id, skip=0, limit=100: [cell_obj]

    resp = client.get("/api/v1/Cells")
    assert resp.status_code == 200
    data = resp.json()
    assert data[0]["cell_id"] == "AAAAAAA01"


def test_create_cell_missing_gnb(monkeypatch):
    client, crud = _setup_client(monkeypatch)

    crud.cell.get_Cell_id = lambda db, id: None
    crud.gnb.get = lambda db, id: None

    payload = {
        "cell_id": "AAAAAAA01",
        "name": "c",
        "gNB_id": 1,
        "latitude": 0.0,
        "longitude": 0.0,
        "radius": 1.0,
    }
    resp = client.post("/api/v1/Cells", json=payload)
    assert resp.status_code == 409


def test_delete_cell_not_found(monkeypatch):
    client, crud = _setup_client(monkeypatch)

    crud.cell.get_Cell_id = lambda db, id: None
    resp = client.delete("/api/v1/Cells/AAAAAAA01")
    assert resp.status_code == 404


def test_create_cell_db_failure(monkeypatch):
    client, crud = _setup_client(monkeypatch)

    def raise_error(*args, **kwargs):
        raise Exception("db error")

    crud.cell.get_Cell_id = raise_error
    crud.gnb.get = lambda db, id: SimpleNamespace(id=1)

    payload = {
        "cell_id": "AAAAAAA02",
        "name": "c",
        "gNB_id": 1,
        "latitude": 0.0,
        "longitude": 0.0,
        "radius": 1.0,
    }

    resp = client.post("/api/v1/Cells", json=payload)
    assert resp.status_code == 500
    data = resp.get_json()
    assert "db error" in str(data).lower() or "database error" in str(data).lower()


def test_delete_cell_db_failure(monkeypatch):
    client, crud = _setup_client(monkeypatch)

    crud.cell.get_Cell_id = lambda db, id: SimpleNamespace(id=1, owner_id=1)

    def raise_error(*args, **kwargs):
        raise Exception("db error")

    crud.cell.remove_by_cell_id = raise_error

    resp = client.delete("/api/v1/Cells/AAAAAAA01")
    assert resp.status_code == 409
