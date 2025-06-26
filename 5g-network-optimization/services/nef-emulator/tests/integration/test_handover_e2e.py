import importlib.util
import sys
from types import ModuleType
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


class DummyAntenna:
    def __init__(self, rsrp: float):
        self._rsrp = rsrp

    def rsrp_dbm(self, pos):
        return self._rsrp


class DummySelector:
    """Simple predictor choosing antenna with highest RSRP."""

    def __init__(self, *a, **k):
        pass

    def extract_features(self, data):
        return data

    def predict(self, features):
        best = max(features["rf_metrics"], key=lambda k: features["rf_metrics"][k]["rsrp"])
        return {"antenna_id": best, "confidence": 1.0}


def _create_client(monkeypatch: pytest.MonkeyPatch):
    backend_root = Path(__file__).resolve().parents[2] / "backend" / "app"
    monkeypatch.syspath_prepend(str(backend_root))
    monkeypatch.setenv("ML_HANDOVER_ENABLED", "1")

    for name in list(sys.modules.keys()):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]

    # Load network state manager module
    spec_state = importlib.util.spec_from_file_location(
        "app.network.state_manager", backend_root / "app" / "network" / "state_manager.py"
    )
    state_mod = importlib.util.module_from_spec(spec_state)
    spec_state.loader.exec_module(state_mod)

    # Prepare dummy AntennaSelector module
    selector_mod = ModuleType("app.models.antenna_selector")
    selector_mod.AntennaSelector = DummySelector
    models_pkg = ModuleType("app.models")
    models_pkg.antenna_selector = selector_mod

    sys.modules["app.models"] = models_pkg
    sys.modules["app.models.antenna_selector"] = selector_mod

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
    return TestClient(app), ml_api


def test_end_to_end_handover(monkeypatch: pytest.MonkeyPatch) -> None:
    client, ml_api = _create_client(monkeypatch)

    ml_api.state_mgr.antenna_list = {"A": DummyAntenna(-80), "B": DummyAntenna(-76)}
    ml_api.state_mgr.ue_states = {
        "u1": {"position": (0, 0, 0), "connected_to": "A", "speed": 0.0}
    }

    resp = client.post("/api/v1/ml/handover", params={"ue_id": "u1"})
    assert resp.status_code == 200
    assert resp.json()["to"] == "B"
