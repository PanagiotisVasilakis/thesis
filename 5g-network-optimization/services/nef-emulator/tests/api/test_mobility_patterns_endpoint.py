import sys
from types import ModuleType, SimpleNamespace
import importlib.util
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest


def _create_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Return TestClient instance with auth dependency overridden."""
    backend_root = Path(__file__).resolve().parents[2] / "backend" / "app"
    monkeypatch.syspath_prepend(str(backend_root))

    for name in list(sys.modules.keys()):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]

    adapter_mod = ModuleType("app.tools.mobility.adapter")
    class MobilityPatternAdapter:
        pass

    adapter_mod.MobilityPatternAdapter = MobilityPatternAdapter
    mobility_pkg = ModuleType("app.tools.mobility")
    mobility_pkg.adapter = adapter_mod
    tools_pkg = ModuleType("app.tools")
    tools_pkg.mobility = mobility_pkg
    sys.modules.setdefault("app.tools.mobility", mobility_pkg)
    sys.modules.setdefault("app.tools", tools_pkg)
    sys.modules.setdefault("app", ModuleType("app"))
    sys.modules["app.tools.mobility.adapter"] = adapter_mod

    api_pkg = ModuleType("app.api")
    deps_mod = ModuleType("app.api.deps")
    deps_mod.get_current_active_user = lambda: SimpleNamespace(id=1, is_superuser=True)
    api_pkg.deps = deps_mod

    models_pkg = ModuleType("app.models")
    user_mod = ModuleType("app.models.user")
    from pydantic import BaseModel

    class User(BaseModel):
        id: int = 1
        is_superuser: bool = True

    user_mod.User = User
    models_pkg.user = user_mod

    app_pkg = ModuleType("app")
    app_pkg.api = api_pkg
    app_pkg.tools = tools_pkg
    app_pkg.models = models_pkg

    monkeypatch.setitem(sys.modules, "app", app_pkg)
    monkeypatch.setitem(sys.modules, "app.api", api_pkg)
    monkeypatch.setitem(sys.modules, "app.api.deps", deps_mod)
    monkeypatch.setitem(sys.modules, "app.tools", tools_pkg)
    monkeypatch.setitem(sys.modules, "app.tools.mobility", mobility_pkg)
    monkeypatch.setitem(sys.modules, "app.tools.mobility.adapter", adapter_mod)
    monkeypatch.setitem(sys.modules, "app.models", models_pkg)
    monkeypatch.setitem(sys.modules, "app.models.user", user_mod)

    endpoints_dir = backend_root / "app" / "api" / "api_v1" / "endpoints"
    spec = importlib.util.spec_from_file_location("mobility_patterns", endpoints_dir / "mobility_patterns.py")
    mobility_patterns = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mobility_patterns)

    app = FastAPI()
    app.include_router(mobility_patterns.router, prefix="/api/v1/mobility-patterns")
    app.dependency_overrides[deps_mod.get_current_active_user] = lambda: SimpleNamespace(id=1, is_superuser=True)
    return TestClient(app)


def test_generate_pattern_success(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _create_client(monkeypatch)

    from app.tools.mobility.adapter import MobilityPatternAdapter

    monkeypatch.setattr(MobilityPatternAdapter, "get_mobility_model", lambda *a, **k: object(), raising=False)
    monkeypatch.setattr(MobilityPatternAdapter, "generate_path_points", lambda *a, **k: [{"latitude": 0.0, "longitude": 0.0}], raising=False)

    payload = {
        "model_type": "linear",
        "ue_id": "ue1",
        "duration": 10,
        "time_step": 1.0,
        "parameters": {
            "start_position": [0, 0, 0],
            "end_position": [1, 1, 0],
            "speed": 1.0,
        },
    }
    resp = client.post("/api/v1/mobility-patterns/generate", json=payload)
    assert resp.status_code == 200
    assert resp.json() == [{"latitude": 0.0, "longitude": 0.0}]


def test_generate_pattern_validation_error(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _create_client(monkeypatch)

    payload = {
        "model_type": "linear",
        "duration": 10,
        "time_step": 1.0,
        "parameters": {
            "start_position": [0, 0, 0],
            "end_position": [1, 1, 0],
            "speed": 1.0,
        },
    }
    resp = client.post("/api/v1/mobility-patterns/generate", json=payload)
    assert resp.status_code == 422
