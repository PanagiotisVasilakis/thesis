import importlib.util
import sys
from types import ModuleType
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient as FastAPITestClient
from httpx import ASGITransport


class TestClient(FastAPITestClient):
    def __init__(self, *, transport: ASGITransport, **kwargs):
        super().__init__(transport.app, **kwargs)


class DummyAntenna:
    def __init__(self, rsrp: float):
        self._rsrp = rsrp

    def rsrp_dbm(self, pos):
        return self._rsrp


class DummyResponse:
    def __init__(self, antenna):
        self._antenna = antenna

    def raise_for_status(self):
        pass

    def json(self):
        return {"predicted_antenna": self._antenna, "confidence": 1.0}


def _create_client(monkeypatch: pytest.MonkeyPatch):
    backend_root = Path(__file__).resolve().parents[2] / "backend" / "app"
    monkeypatch.syspath_prepend(str(backend_root))
    monkeypatch.setenv("ML_HANDOVER_ENABLED", "1")

    for name in list(sys.modules.keys()):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]

    # Load network state manager module
    spec_state = importlib.util.spec_from_file_location(
        "app.network.state_manager", backend_root /
        "app" / "network" / "state_manager.py"
    )
    state_mod = importlib.util.module_from_spec(spec_state)
    spec_state.loader.exec_module(state_mod)

    # Patch requests.post used by the handover engine

    def fake_post(url, json=None, timeout=None):
        best = max(json["rf_metrics"],
                   key=lambda a: json["rf_metrics"][a]["rsrp"])
        return DummyResponse(best)

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setenv("ML_SERVICE_URL", "http://ml")

    sys.modules["app.network"] = ModuleType("app.network")
    sys.modules["app.network"].state_manager = state_mod
    sys.modules["app.network.state_manager"] = state_mod

    # Load handover engine with patched AntennaSelector
    spec_engine = importlib.util.spec_from_file_location(
        "app.handover.engine", backend_root / "app" / "handover" / "engine.py"
    )
    engine_mod = importlib.util.module_from_spec(spec_engine)
    handover_pkg = ModuleType("app.handover")
    # Load rule helper used by the engine
    spec_rule = importlib.util.spec_from_file_location(
        "app.handover.a3_rule", backend_root / "app" / "handover" / "a3_rule.py"
    )
    rule_mod = importlib.util.module_from_spec(spec_rule)
    spec_rule.loader.exec_module(rule_mod)
    sys.modules["app.handover.a3_rule"] = rule_mod

    sys.modules["app.handover"] = handover_pkg
    handover_pkg.a3_rule = rule_mod
    spec_engine.loader.exec_module(engine_mod)
    sys.modules["app.handover.engine"] = engine_mod

    # Load ml_api router
    spec_ml = importlib.util.spec_from_file_location(
        "ml_api", backend_root / "app" / "api" / "api_v1" / "endpoints" / "ml_api.py"
    )
    ml_api = importlib.util.module_from_spec(spec_ml)
    spec_ml.loader.exec_module(ml_api)

    app = FastAPI()
    app.include_router(ml_api.router, prefix="/api/v1")
    return TestClient(transport=ASGITransport(app=app)), ml_api


def test_end_to_end_handover(monkeypatch: pytest.MonkeyPatch) -> None:
    client, ml_api = _create_client(monkeypatch)

    ml_api.state_mgr.antenna_list = {
        "A": DummyAntenna(-80), "B": DummyAntenna(-76)}
    ml_api.state_mgr.ue_states = {
        "u1": {"position": (0, 0, 0), "connected_to": "A", "speed": 0.0}
    }

    resp = client.post("/api/v1/ml/handover", params={"ue_id": "u1"})
    assert resp.status_code == 200
    assert resp.json()["to"] == "B"
