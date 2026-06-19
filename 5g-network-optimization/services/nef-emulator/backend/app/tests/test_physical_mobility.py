import math

from app.simulation.mobility import (
    advance_ping_pong,
    configured_speed_mps,
    interpolate_path_position,
    path_cumulative_distances,
)


def test_distance_based_mobility_tracks_numeric_speed():
    points = [
        {"latitude": 37.0, "longitude": 23.0},
        {"latitude": 37.001, "longitude": 23.0},
    ]
    cumulative = path_cumulative_distances(points)
    distance, direction = advance_ping_pong(0.0, 1, 33.3, cumulative[-1])
    latitude, longitude, _index = interpolate_path_position(points, cumulative, distance)
    moved = path_cumulative_distances(
        [points[0], {"latitude": latitude, "longitude": longitude}]
    )[-1]
    assert math.isclose(moved, 33.3, rel_tol=0.01)
    assert direction == 1


def test_open_path_bounces_without_teleporting():
    distance, direction = advance_ping_pong(95.0, 1, 10.0, 100.0)
    assert distance == 95.0
    assert direction == -1


def test_numeric_speed_overrides_legacy_label():
    assert configured_speed_mps({"speed": "HIGH", "speed_mps": 22.2}) == 22.2
