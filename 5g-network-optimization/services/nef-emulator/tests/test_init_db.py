import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, mock_open, patch


def _load_init_db(monkeypatch):
    # Stub minimal sqlalchemy package if not installed
    sa = ModuleType("sqlalchemy")
    sa.orm = ModuleType("sqlalchemy.orm")
    sa.orm.Session = object
    sa.Column = lambda *a, **k: None
    sa.Integer = sa.String = sa.Boolean = sa.Float = object
    sa.ForeignKey = lambda *a, **k: None
    sa.orm.relationship = lambda *a, **k: None
    sa.create_engine = lambda *a, **k: None
    sa.orm.sessionmaker = lambda *a, **k: None
    sa.asc = lambda x: x
    monkeypatch.setitem(sys.modules, "sqlalchemy", sa)
    monkeypatch.setitem(sys.modules, "sqlalchemy.orm", sa.orm)
    monkeypatch.setitem(sys.modules, "sqlalchemy.orm.session", sa.orm)

    # Stub fastapi.encoder
    fe = ModuleType("fastapi.encoders")
    fe.jsonable_encoder = lambda obj: obj
    monkeypatch.setitem(sys.modules, "fastapi.encoders", fe)

    # Build ``app`` package skeleton
    app_pkg = ModuleType("app")
    db_pkg = ModuleType("app.db")
    db_pkg.__path__ = []
    base_class_mod = ModuleType("app.db.base_class")
    class Base:
        metadata = SimpleNamespace(create_all=MagicMock())
    base_class_mod.Base = Base
    session_mod = ModuleType("app.db.session")
    session_mod.engine = "engine"
    monkeypatch.setitem(sys.modules, "app.db.base_class", base_class_mod)
    monkeypatch.setitem(sys.modules, "app.db.session", session_mod)
    monkeypatch.setitem(sys.modules, "app.db.base", ModuleType("app.db.base"))
    db_pkg.base_class = base_class_mod
    db_pkg.session = session_mod
    app_pkg.db = db_pkg

    # CRUD module with MagicMocks
    crud_mod = ModuleType("app.crud")
    crud_mod.user = SimpleNamespace(get_by_email=MagicMock(return_value=SimpleNamespace(id=1)))
    crud_mod.gnb = SimpleNamespace(create_with_owner=MagicMock())
    crud_mod.cell = SimpleNamespace(create_with_owner=MagicMock())
    crud_mod.ue = SimpleNamespace(
        create_with_owner=MagicMock(),
        get_supi=MagicMock(return_value={}),
        update=MagicMock(),
    )
    crud_mod.path = SimpleNamespace(create_with_owner=MagicMock(return_value=SimpleNamespace(id=1)))
    crud_mod.points = SimpleNamespace(create=MagicMock())
    app_pkg.crud = crud_mod
    monkeypatch.setitem(sys.modules, "app.crud", crud_mod)

    # Empty schemas and config settings
    schemas_mod = ModuleType("app.schemas")
    monkeypatch.setitem(sys.modules, "app.schemas", schemas_mod)
    core_cfg_mod = ModuleType("app.core.config")
    core_cfg_mod.settings = SimpleNamespace(
        FIRST_SUPERUSER="admin@example.com",
        FIRST_SUPERUSER_PASSWORD="pass",
    )
    monkeypatch.setitem(sys.modules, "app.core.config", core_cfg_mod)
    core_mod = ModuleType("app.core")
    core_mod.config = core_cfg_mod
    monkeypatch.setitem(sys.modules, "app.core", core_mod)

    # paths.get_random_point
    paths_mod = ModuleType("app.api.api_v1.endpoints.paths")
    paths_mod.get_random_point = lambda db, path_id: {"latitude": 0.0, "longitude": 0.0}
    monkeypatch.setitem(sys.modules, "app.api.api_v1.endpoints.paths", paths_mod)

    monkeypatch.setitem(sys.modules, "app", app_pkg)
    monkeypatch.setitem(sys.modules, "app.db", db_pkg)

    # Load init_db module from file
    path = Path(__file__).resolve().parents[1] / "backend" / "app" / "app" / "db" / "init_db.py"
    spec = importlib.util.spec_from_file_location("app.db.init_db", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "app.db.init_db", module)
    spec.loader.exec_module(module)
    return module, Base, crud_mod


def test_init_db(monkeypatch):
    module, Base, crud = _load_init_db(monkeypatch)
    scenario = {
        "gNBs": [{"id": 1}],
        "cells": [{"id": 1}],
        "UEs": [{"id": 1}],
        "paths": [{"id": 1}],
        "ue_path_association": [{"supi": "a"}],
    }

    class DummyDB:
        def execute(self, q):
            self.executed = q

    db = DummyDB()
    with patch("app.db.init_db.open", mock_open(read_data=json.dumps(scenario))):
        module.init_db(db)

    assert Base.metadata.create_all.call_count == 1
    assert crud.gnb.create_with_owner.call_count == 1
    assert crud.cell.create_with_owner.call_count == 1
    assert crud.ue.create_with_owner.call_count == 1
    assert crud.path.create_with_owner.call_count == 1
    assert crud.points.create.call_count == 1
    assert crud.ue.update.call_count == len(scenario["ue_path_association"])
    assert db.executed == "TRUNCATE TABLE cell, gnb, path, points, ue RESTART IDENTITY"
