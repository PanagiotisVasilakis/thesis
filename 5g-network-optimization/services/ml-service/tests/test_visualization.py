from unittest.mock import MagicMock, patch
from pathlib import Path
import json


COVERAGE_IMG = Path(__file__).resolve().parents[1] / "test_coverage_map.png"
TRAJ_IMG = Path(__file__).resolve().parents[1] / "test_trajectory.png"


def test_coverage_map_endpoint(client):
    mock_model = MagicMock()
    mock_model.predict.return_value = {"antenna_id": "a1", "confidence": 1.0}
    with patch("app.api.visualization.model", mock_model), \
         patch("app.api.visualization.plot_antenna_coverage", return_value=str(COVERAGE_IMG)):
        resp = client.get("/api/visualization/coverage-map")
        assert resp.status_code == 200
        assert len(resp.data) > 0


def test_trajectory_endpoint(client):
    movement = [{
        "ue_id": "u1",
        "timestamp": "2025-01-01T00:00:00",
        "latitude": 0,
        "longitude": 0,
        "connected_to": "a1",
        "speed": 1.0
    }]

    with patch("app.api.visualization.plot_movement_trajectory", return_value=str(TRAJ_IMG)):
        resp = client.post("/api/visualization/trajectory", data=json.dumps(movement), content_type="application/json")
        assert resp.status_code == 200
        assert len(resp.data) > 0
