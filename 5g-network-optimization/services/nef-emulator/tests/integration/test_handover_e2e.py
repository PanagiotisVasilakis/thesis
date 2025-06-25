import os
import importlib
import sys

import pytest

pytest.skip("Requires full ML service context", allow_module_level=True)
from fastapi.testclient import TestClient

import importlib.util
from pathlib import Path

try:
    import sqlalchemy  # noqa: F401
except Exception:  # pragma: no cover - optional dependency for integration test
    sqlalchemy = None

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
    # Reload module to apply env var with dynamically loaded app package
    backend_root = Path(__file__).resolve().parents[2] / "backend" / "app"
    for name in list(sys.modules.keys()):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        "app",
        backend_root / "app" / "__init__.py",
        submodule_search_locations=[str(backend_root / "app")],
    )
    app_pkg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(app_pkg)
    sys.modules["app"] = app_pkg

    endpoints_dir = backend_root / "app" / "api" / "api_v1" / "endpoints"
    spec_ml = importlib.util.spec_from_file_location("ml_api", endpoints_dir / "ml_api.py")
    ml_api = importlib.util.module_from_spec(spec_ml)
    spec_ml.loader.exec_module(ml_api)
    return ml_api


def test_end_to_end_handover(monkeypatch):
    if sqlalchemy is None:
        pytest.skip("SQLAlchemy not available")

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
            aid: {"rsrp": fv["neighbor_rsrp_dbm"][aid], "sinr": fv["neighbor_sinrs"][aid]}
            for aid in fv["neighbor_rsrp_dbm"]
        },
    }

    pred_resp = ml_client.post("/api/predict", json=ml_payload)
    assert pred_resp.status_code == 200
    predicted = pred_resp.get_json()["predicted_antenna"]

    resp = nef_client.post("/api/v1/ml/handover", params={"ue_id": "u1"})
    assert resp.status_code == 200
    assert resp.json()["to"] == predicted

