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
        "app.network.state_manager", backend_root /
        "app" / "network" / "state_manager.py"
    )
    state_mod = importlib.util.module_from_spec(spec_state)
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
    return TestClient(transport=ASGITransport(app=app)), ml_api


def test_handover_triggers_prediction(monkeypatch: pytest.MonkeyPatch) -> None:
    ml_client, dummy_model = _create_ml_client(monkeypatch)
    nef_client, ml_api = _create_nef_client(monkeypatch, ml_client)

    ml_api.state_mgr.antenna_list = {
        "A": DummyAntenna(-80), "B": DummyAntenna(-70)}
    ml_api.state_mgr.ue_states = {
        "u1": {"position": (0, 0, 0), "connected_to": "A", "speed": 0.0}
    }

    resp = nef_client.post("/api/v1/ml/handover", params={"ue_id": "u1"})
    assert resp.status_code == 200
    assert resp.json()["to"] == "B"
    assert dummy_model.predict.called
