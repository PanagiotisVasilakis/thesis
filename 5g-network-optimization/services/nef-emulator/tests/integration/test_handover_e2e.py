import os
import importlib

import pytest
from fastapi.testclient import TestClient

import importlib.util
from pathlib import Path

ML_DIR = Path(__file__).resolve().parents[3] / "ml-service" / "app" / "__init__.py"
spec = importlib.util.spec_from_file_location("ml_app_pkg", ML_DIR)
ml_app_pkg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ml_app_pkg)
create_ml_app = ml_app_pkg.create_app


class DummyAntenna:
    def __init__(self, rsrp):
        self._rsrp = rsrp
    def rsrp_dbm(self, pos):
        return self._rsrp

def _setup_environment(monkeypatch):
    monkeypatch.setenv("ML_HANDOVER_ENABLED", "1")
    # Reload module to apply env var
    from app.api.api_v1 import endpoints
    importlib.reload(endpoints.ml_api)
    return endpoints.ml_api


def test_end_to_end_handover(monkeypatch):
    ml_api = _setup_environment(monkeypatch)

    from app.main import app as nef_app
    nef_client = TestClient(nef_app)

    ml_app = create_ml_app({"TESTING": True})
    ml_client = ml_app.test_client()

    ml_api.state_mgr.antenna_list = {"A": DummyAntenna(-80), "B": DummyAntenna(-76)}
    ml_api.state_mgr.ue_states = {
        "u1": {"position": (0, 0, 0), "connected_to": "A", "speed": 0.0}
    }

    fv = ml_api.state_mgr.get_feature_vector("u1")
    ml_payload = {
        "ue_id": "u1",
        "latitude": fv["latitude"],
        "longitude": fv["longitude"],
        "speed": fv.get("speed", 0.0),
        "direction": (0, 0, 0),
        "connected_to": fv["connected_to"],
        "rf_metrics": {
            aid: {"rsrp": fv["neighbor_rsrs"][aid], "sinr": fv["neighbor_sinrs"][aid]}
            for aid in fv["neighbor_rsrs"]
        },
    }

    pred_resp = ml_client.post("/api/predict", json=ml_payload)
    assert pred_resp.status_code == 200
    predicted = pred_resp.get_json()["predicted_antenna"]

    resp = nef_client.post("/api/v1/ml/handover", params={"ue_id": "u1"})
    assert resp.status_code == 200
    assert resp.json()["to"] == predicted

