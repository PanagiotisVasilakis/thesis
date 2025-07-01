from unittest.mock import MagicMock, patch
import json


def _create_png(tmp_path, name):
    """Return the path to a simple PNG file under ``tmp_path``."""
    from PIL import Image

    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (10, 10), color="red")
    img.save(path)
    return path


def test_coverage_map_endpoint(client, tmp_path):
    mock_model = MagicMock()
    mock_model.predict.return_value = {"antenna_id": "a1", "confidence": 1.0}
    img_path = _create_png(tmp_path / "coverage", "coverage.png")
    with patch("ml_service.app.api.visualization.model", mock_model), \
         patch("ml_service.app.api.visualization.plot_antenna_coverage", return_value=str(img_path)):
        resp = client.get("/api/visualization/coverage-map")
        assert resp.status_code == 200
        assert len(resp.data) > 0


def test_trajectory_endpoint(client, tmp_path):
    movement = [{
        "ue_id": "u1",
        "timestamp": "2025-01-01T00:00:00",
        "latitude": 0,
        "longitude": 0,
        "connected_to": "a1",
        "speed": 1.0
    }]

    img_path = _create_png(tmp_path / "trajectory", "traj.png")
    with patch("ml_service.app.api.visualization.plot_movement_trajectory", return_value=str(img_path)):
        resp = client.post("/api/visualization/trajectory", data=json.dumps(movement), content_type="application/json")
        assert resp.status_code == 200
        assert len(resp.data) > 0
