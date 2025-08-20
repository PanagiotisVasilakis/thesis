import importlib.util
import sys
from types import ModuleType
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient as FastAPITestClient
from httpx import ASGITransport


pytestmark = pytest.mark.skip(reason="Requires full ML dependencies")


class TestClient(FastAPITestClient):
    def __init__(self, *, transport: ASGITransport, **kwargs):
        super().__init__(transport.app, **kwargs)


class DummyAntenna:
    def __init__(self, rsrp: float):
        self._rsrp = rsrp

    def rsrp_dbm(self, pos):
        return self._rsrp


def _create_client(monkeypatch: pytest.MonkeyPatch):
    """Return FastAPI TestClient using local ML model."""
    backend_root = Path(__file__).resolve().parents[2] / "backend" / "app"
    monkeypatch.syspath_prepend(str(backend_root))
    monkeypatch.setenv("ML_HANDOVER_ENABLED", "1")
    monkeypatch.setenv("ML_LOCAL", "1")

    # Ensure HTTP requests are not made
    def fake_post(*a, **k):
        raise AssertionError("HTTP requests should not be made")

    monkeypatch.setattr("requests.post", fake_post)

    dummy_model = MagicMock()
    dummy_model.extract_features.return_value = {"f": 1}
    dummy_model.predict.return_value = {"antenna_id": "B", "confidence": 1.0}

    # Provide lightweight stub for model manager to avoid heavy ML imports
    model_init_mod = ModuleType("ml_service.app.initialization.model_init")
    class ModelManager:
        @staticmethod
        def get_instance(p=None, **_):
            return dummy_model
    model_init_mod.ModelManager = ModelManager
    sys.modules["ml_service.app.initialization.model_init"] = model_init_mod

    for name in list(sys.modules.keys()):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]

    spec_state = importlib.util.spec_from_file_location(
        "app.network.state_manager", backend_root /
        "app" / "network" / "state_manager.py"
    )
    state_mod = importlib.util.module_from_spec(spec_state)
    spec_state.loader.exec_module(state_mod)

    sys.modules["app.network"] = ModuleType("app.network")
    sys.modules["app.network"].state_manager = state_mod
    sys.modules["app.network.state_manager"] = state_mod

    spec_engine = importlib.util.spec_from_file_location(
        "app.handover.engine", backend_root / "app" / "handover" / "engine.py"
    )
    engine_mod = importlib.util.module_from_spec(spec_engine)

    spec_rule = importlib.util.spec_from_file_location(
        "app.handover.a3_rule", backend_root / "app" / "handover" / "a3_rule.py"
    )
    rule_mod = importlib.util.module_from_spec(spec_rule)
    spec_rule.loader.exec_module(rule_mod)

    handover_pkg = ModuleType("app.handover")
    handover_pkg.a3_rule = rule_mod
    spec_engine.loader.exec_module(engine_mod)
    sys.modules["app.handover"] = handover_pkg
    sys.modules["app.handover.engine"] = engine_mod

    spec_ml = importlib.util.spec_from_file_location(
        "ml_api", backend_root / "app" / "api" / "api_v1" / "endpoints" / "ml_api.py"
    )
    ml_api = importlib.util.module_from_spec(spec_ml)
    spec_ml.loader.exec_module(ml_api)

    app = FastAPI()
    app.include_router(ml_api.router, prefix="/api/v1")
    return TestClient(transport=ASGITransport(app=app)), ml_api, dummy_model


def test_local_model_used(monkeypatch: pytest.MonkeyPatch) -> None:
    client, ml_api, dummy_model = _create_client(monkeypatch)

    ml_api.state_mgr.antenna_list = {
        "A": DummyAntenna(-80), "B": DummyAntenna(-70)}
    ml_api.state_mgr.ue_states = {
        "u1": {"position": (0, 0, 0), "connected_to": "A", "speed": 0.0}
    }

    resp = client.post("/api/v1/ml/handover", params={"ue_id": "u1"})
    assert resp.status_code == 200
    assert resp.json()["to"] == "B"
    assert dummy_model.predict.called
