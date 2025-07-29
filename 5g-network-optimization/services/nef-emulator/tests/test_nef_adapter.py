import json
from backend.app.app.mobility_models.nef_adapter import (
    generate_nef_path_points,
    save_path_to_json,
)


def test_generate_nef_path_points_linear():
    points = generate_nef_path_points(
        "linear",
        ue_id="u1",
        start_position=(0, 0, 0),
        end_position=(2, 0, 0),
        speed=1.0,
        duration=2,
        time_step=1.0,
    )
    assert len(points) == 3
    assert points[0]["latitude"] == 0.0
    assert points[-1]["latitude"] == 2.0
    for p in points:
        assert set(p) == {"latitude", "longitude", "description"}


def test_generate_nef_path_points_l_shaped():
    points = generate_nef_path_points(
        "l_shaped",
        ue_id="u1",
        start_position=(0, 0, 0),
        corner_position=(1, 1, 0),
        end_position=(1, 2, 0),
        speed=1.0,
        duration=3,
        time_step=1.0,
    )
    assert len(points) >= 3
    assert points[0]["latitude"] == 0.0
    assert points[-1]["longitude"] == 2.0
    assert any(p["latitude"] != points[0]["latitude"] and p["longitude"]
               != points[-1]["longitude"] for p in points[1:-1])


def test_save_path_to_json(tmp_path):
    points = [{"latitude": 0, "longitude": 0, "description": "p0"}]
    file_path = tmp_path / "path.json"
    returned = save_path_to_json(points, str(file_path))
    assert returned == str(file_path)
    with open(file_path) as f:
        saved = json.load(f)
    assert saved == points
