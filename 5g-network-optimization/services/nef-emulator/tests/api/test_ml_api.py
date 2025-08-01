import importlib.util
from pathlib import Path
import sys
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient as FastAPITestClient
from httpx import ASGITransport


class TestClient(FastAPITestClient):
    def __init__(self, *, transport: ASGITransport, **kwargs):
        super().__init__(transport.app, **kwargs)


class DummyStateManager:
    """Minimal stand-in for NetworkStateManager."""

    def get_feature_vector(self, ue_id: str):
        if ue_id == "ue1":
            return {"ue_id": ue_id, "feature": 1}
        raise KeyError("UE not found")


class DummyEngine:
    """Minimal stand-in for HandoverEngine."""

    def __init__(self, sm: DummyStateManager):
        self.sm = sm

    def decide_and_apply(self, ue_id: str):
        if ue_id == "ue1":
            return {"ue_id": ue_id, "from": "A", "to": "B"}
        if ue_id == "ue_no":
            return None
        raise KeyError("UE not found")


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Return a TestClient with dummy dependencies injected."""
    backend_root = Path(__file__).resolve().parents[2] / "backend" / "app"
    spec = importlib.util.spec_from_file_location(
        "ml_api", backend_root / "app" / "api" / "api_v1" / "endpoints" / "ml_api.py"
    )
    ml_api = importlib.util.module_from_spec(spec)
    # Provide minimal stub modules expected by ml_api during import
    handover_pkg = types.ModuleType("app.handover")
    engine_mod = types.ModuleType("app.handover.engine")

    class HandoverEngine:
        def __init__(self, *a, **k):
            pass

    engine_mod.HandoverEngine = HandoverEngine

    # Stub out network state manager dependency
    network_pkg = types.ModuleType("app.network")
    state_mod = types.ModuleType("app.network.state_manager")
    state_mod.NetworkStateManager = DummyStateManager
    network_pkg.state_manager = state_mod

    monitoring_pkg = types.ModuleType("app.monitoring")
    metrics_mod = types.ModuleType("app.monitoring.metrics")
    metrics_mod.HANDOVER_DECISIONS = types.SimpleNamespace(
        labels=lambda *a, **k: types.SimpleNamespace(inc=lambda: None))
    metrics_mod.REQUEST_DURATION = types.SimpleNamespace(
        labels=lambda *a, **k: types.SimpleNamespace(observe=lambda v: None))
    monitoring_pkg.metrics = metrics_mod

    app_pkg = types.ModuleType("app")
    app_pkg.handover = handover_pkg
    app_pkg.network = network_pkg
    app_pkg.monitoring = monitoring_pkg

    sys.modules.setdefault("app", app_pkg)
    sys.modules.setdefault("app.handover", handover_pkg)
    sys.modules.setdefault("app.handover.engine", engine_mod)
    sys.modules.setdefault("app.network", network_pkg)
    sys.modules.setdefault("app.network.state_manager", state_mod)
    sys.modules.setdefault("app.monitoring", monitoring_pkg)
    sys.modules.setdefault("app.monitoring.metrics", metrics_mod)
    spec.loader.exec_module(ml_api)

    sm = DummyStateManager()
    eng = DummyEngine(sm)
    monkeypatch.setattr(ml_api, "state_mgr", sm)
    monkeypatch.setattr(ml_api, "engine", eng)

    app = FastAPI()
    app.include_router(ml_api.router, prefix="/api/v1")
    return TestClient(transport=ASGITransport(app=app))


def test_get_state_success(client: TestClient) -> None:
    resp = client.get("/api/v1/ml/state/ue1")
    assert resp.status_code == 200
    assert resp.json() == {"ue_id": "ue1", "feature": 1}


def test_get_state_not_found(client: TestClient) -> None:
    resp = client.get("/api/v1/ml/state/missing")
    assert resp.status_code == 404


def test_handover_applied(client: TestClient) -> None:
    resp = client.post("/api/v1/ml/handover?ue_id=ue1")
    assert resp.status_code == 200
    assert resp.json()["to"] == "B"


def test_handover_not_triggered(client: TestClient) -> None:
    resp = client.post("/api/v1/ml/handover?ue_id=ue_no")
    assert resp.status_code == 400
    data = resp.json()
    assert (data.get("message") or data.get("detail")) == "No handover triggered"
