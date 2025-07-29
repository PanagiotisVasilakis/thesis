from types import ModuleType, SimpleNamespace
import importlib.util
from pathlib import Path
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient as FastAPITestClient
from httpx import ASGITransport


class TestClient(FastAPITestClient):
    def __init__(self, *, transport: ASGITransport, **kwargs):
        super().__init__(transport.app, **kwargs)
import pytest


def _create_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    backend_root = Path(__file__).resolve().parents[2] / "backend" / "app"
    monkeypatch.syspath_prepend(str(backend_root))

    for name in list(sys.modules.keys()):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]

    spec_adapter = importlib.util.spec_from_file_location(
        "app.tools.mobility.adapter",
        backend_root / "app" / "tools" / "mobility" / "adapter.py",
    )
    adapter_mod = importlib.util.module_from_spec(spec_adapter)
    spec_adapter.loader.exec_module(adapter_mod)

    mobility_pkg = ModuleType("app.tools.mobility")
    mobility_pkg.adapter = adapter_mod
    tools_pkg = ModuleType("app.tools")
    tools_pkg.mobility = mobility_pkg

    deps_mod = ModuleType("app.api.deps")
    deps_mod.get_current_active_user = lambda: SimpleNamespace(id=1)
    api_pkg = ModuleType("app.api")
    api_pkg.deps = deps_mod

    user_mod = ModuleType("app.models.user")
    user_mod.User = SimpleNamespace
    models_pkg = ModuleType("app.models")
    models_pkg.user = user_mod

    app_pkg = ModuleType("app")
    app_pkg.api = api_pkg
    app_pkg.tools = tools_pkg
    app_pkg.models = models_pkg

    for name, mod in {
        "app": app_pkg,
        "app.api": api_pkg,
        "app.api.deps": deps_mod,
        "app.tools": tools_pkg,
        "app.tools.mobility": mobility_pkg,
        "app.tools.mobility.adapter": adapter_mod,
        "app.models": models_pkg,
        "app.models.user": user_mod,
    }.items():
        sys.modules[name] = mod

    spec_router = importlib.util.spec_from_file_location(
        "patterns",
        backend_root / "app" / "api" / "api_v1" /
        "endpoints" / "mobility" / "patterns.py",
    )
    patterns = importlib.util.module_from_spec(spec_router)
    spec_router.loader.exec_module(patterns)

    app = FastAPI()
    app.include_router(patterns.router, prefix="/api/v1/mobility-patterns")
    app.dependency_overrides[deps_mod.get_current_active_user] = lambda: SimpleNamespace(
        id=1)
    return TestClient(transport=ASGITransport(app=app))


def test_generate_pattern_invalid_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _create_client(monkeypatch)
    payload = {
        "model_type": "linear",
        "duration": 5,
        "time_step": 1.0,
        "parameters": {"start_position": [0, 0, 0], "end_position": [1, 1, 0], "speed": 1.0},
    }
    resp = client.post("/api/v1/mobility-patterns/generate", json=payload)
    assert resp.status_code == 422
