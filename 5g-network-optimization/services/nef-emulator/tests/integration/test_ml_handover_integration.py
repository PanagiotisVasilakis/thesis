import importlib.util
import sys
from types import ModuleType
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient as FastAPITestClient
from httpx import ASGITransport
from importlib.machinery import ModuleSpec
from typing import cast, Any


# Integration test for ML handover behavior — runs in-process with patched ML client


class TestClient(FastAPITestClient):
    def __init__(self, *, transport: ASGITransport, **kwargs):
        # transport.app is a typed ASGI app; mypy/pylance sometimes
        # complains about exact ASGI types — cast to satisfy type checkers
        app = cast(Any, transport.app)
        super().__init__(app, **kwargs)


class DummyAntenna:
    def __init__(self, rsrp: float):
        self._rsrp = rsrp

    def rsrp_dbm(self, pos):
        return self._rsrp


def _create_ml_client(monkeypatch: pytest.MonkeyPatch):
    """Return Flask test client for the ML service with a stub model."""
    import importlib.util
    import sys
    from ml_service.app import create_app

    # Stub optional dependency used during app import
    sys.modules.setdefault(
        "seaborn",
        importlib.util.module_from_spec(
            importlib.util.spec_from_loader("seaborn", loader=None)),
    )

    # Skip expensive model initialization
    monkeypatch.setattr(
        "ml_service.app.initialization.model_init.ModelManager.initialize",
        lambda *a, **k: None,
    )

    dummy_model = MagicMock()
    dummy_model.extract_features.return_value = {"f": 1}
    dummy_model.predict.return_value = {"antenna_id": "B", "confidence": 1.0}

    monkeypatch.setattr(
        "ml_service.app.api.routes.load_model", lambda *a, **k: dummy_model
    )

    app = create_app({"TESTING": True})
    return app.test_client(), dummy_model


def _create_nef_client(monkeypatch: pytest.MonkeyPatch, ml_client):
    """Return FastAPI TestClient for the NEF emulator routing."""
    backend_root = Path(__file__).resolve().parents[2] / "backend" / "app"
    monkeypatch.syspath_prepend(str(backend_root))
    monkeypatch.setenv("ML_HANDOVER_ENABLED", "1")

    for name in list(sys.modules.keys()):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]

    spec_state = importlib.util.spec_from_file_location(
        "app.network.state_manager", backend_root / "app" / "network" / "state_manager.py"
    )
    assert spec_state is not None and isinstance(spec_state, ModuleSpec)
    state_mod = importlib.util.module_from_spec(spec_state)
    assert spec_state.loader is not None
    spec_state.loader.exec_module(state_mod)

    class DummyResponse:
        def __init__(self, resp):
            self.resp = resp

        def raise_for_status(self):
            if self.resp.status_code >= 400:
                raise Exception(self.resp.status_code)

        def json(self):
            return self.resp.get_json()

    def fake_post(url, json=None, timeout=None):
        path = url.split("http://ml", 1)[1]
        resp = ml_client.post(path, json=json)
        return DummyResponse(resp)

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setenv("ML_SERVICE_URL", "http://ml")

    sys.modules["app.network"] = ModuleType("app.network")
    # assign attribute via setattr so type checkers don't complain
    setattr(sys.modules["app.network"], "state_manager", state_mod)
    sys.modules["app.network.state_manager"] = state_mod

    spec_engine = importlib.util.spec_from_file_location(
        "app.handover.engine", backend_root / "app" / "handover" / "engine.py"
    )
    assert spec_engine is not None and isinstance(spec_engine, ModuleSpec)
    engine_mod = importlib.util.module_from_spec(spec_engine)
    assert spec_engine.loader is not None

    spec_rule = importlib.util.spec_from_file_location(
        "app.handover.a3_rule", backend_root / "app" / "handover" / "a3_rule.py"
    )
    assert spec_rule is not None and isinstance(spec_rule, ModuleSpec)
    rule_mod = importlib.util.module_from_spec(spec_rule)
    assert spec_rule.loader is not None
    spec_rule.loader.exec_module(rule_mod)

    handover_pkg = ModuleType("app.handover")
    setattr(handover_pkg, "a3_rule", rule_mod)
    spec_engine.loader.exec_module(engine_mod)
    sys.modules["app.handover"] = handover_pkg
    sys.modules["app.handover.engine"] = engine_mod

    spec_ml = importlib.util.spec_from_file_location(
        "ml_api", backend_root / "app" / "api" / "api_v1" / "endpoints" / "ml_api.py"
    )
    assert spec_ml is not None and isinstance(spec_ml, ModuleSpec)
    ml_api = importlib.util.module_from_spec(spec_ml)
    assert spec_ml.loader is not None
    spec_ml.loader.exec_module(ml_api)

    app = FastAPI()
    app.include_router(ml_api.router, prefix="/api/v1")
    # ASGITransport expects a concrete ASGI app; cast for type checkers
    transport = ASGITransport(app=cast(Any, app))
    return TestClient(transport=transport), ml_api


def test_handover_triggers_prediction(monkeypatch: pytest.MonkeyPatch) -> None:
    ml_client, dummy_model = _create_ml_client(monkeypatch)
    nef_client, ml_api = _create_nef_client(monkeypatch, ml_client)

    ml_api.state_mgr.antenna_list = {
        "A": DummyAntenna(-80), "B": DummyAntenna(-70)}
    ml_api.state_mgr.ue_states = {
        "u1": {"position": (0, 0, 0), "connected_to": "A", "speed": 0.0}
    }

    # Scenario A: ML reports qos_compliance OK despite low confidence
    dummy_model.predict.return_value = {
        "antenna_id": "B",
        "confidence": 0.4,
        "qos_compliance": {"service_priority_ok": True, "required_confidence": 0.8, "observed_confidence": 0.4, "details": {}},
    }
    # Record baseline metric values from the real monitoring module so we
    # observe increments made by the HandoverEngine (avoid creating a
    # separate module instance).
    import importlib

    metrics_mod = importlib.import_module("app.monitoring.metrics")
    base_ok = metrics_mod.HANDOVER_COMPLIANCE.labels(outcome="ok")._value.get()
    resp = nef_client.post("/api/v1/ml/handover", params={"ue_id": "u1"})
    assert resp.status_code == 200
    assert resp.json()["to"] == "B"
    assert dummy_model.predict.called
    assert metrics_mod.HANDOVER_COMPLIANCE.labels(outcome="ok")._value.get() == base_ok + 1

    # Scenario B: ML reports qos_compliance failed and engine should fallback
    dummy_model.predict.return_value = {
        "antenna_id": "B",
        "confidence": 0.9,
        "qos_compliance": {"service_priority_ok": False, "required_confidence": 0.95, "observed_confidence": 0.9, "details": {}},
    }
    base_failed = metrics_mod.HANDOVER_COMPLIANCE.labels(outcome="failed")._value.get()
    base_fallbacks = metrics_mod.HANDOVER_FALLBACKS._value.get()
    resp2 = nef_client.post("/api/v1/ml/handover", params={"ue_id": "u1"})
    assert resp2.status_code == 200
    # Fallback may choose same or different antenna; ensure fallback counter incremented
    assert metrics_mod.HANDOVER_COMPLIANCE.labels(outcome="failed")._value.get() == base_failed + 1
    assert metrics_mod.HANDOVER_FALLBACKS._value.get() == base_fallbacks + 1
