import math
from ml_service.app.utils.mobility_metrics import (
    compute_heading_change_rate,
    compute_path_curvature,
    MobilityMetricTracker,
)


def test_heading_change_rate_straight_line():
    pts = [(0, 0), (1, 0), (2, 0)]
    assert compute_heading_change_rate(pts) == 0.0


def test_heading_change_rate_turn():
    pts = [(0, 0), (1, 0), (1, 1)]
    rate = compute_heading_change_rate(pts)
    assert math.isclose(rate, math.pi / 2, rel_tol=1e-6)


def test_heading_change_rate_multiple_turns():
    pts = [
        (0, 0),
        (1, 0),
        (1, 1),
        (0, 1),
        (0, 2),
    ]
    rate = compute_heading_change_rate(pts)
    assert math.isclose(rate, math.pi / 2, rel_tol=1e-6)


def test_path_curvature_straight():
    pts = [(0, 0), (1, 0), (2, 0)]
    assert compute_path_curvature(pts) == 0.0


def test_path_curvature_turn():
    pts = [(0, 0), (1, 0), (1, 1)]
    curv = compute_path_curvature(pts)
    expected = (math.pi / 2) / 2  # angle / path length
    assert math.isclose(curv, expected, rel_tol=1e-6)


def test_incremental_tracker_matches_full_computation():
    pts = [
        (0.0, 0.0),
        (1.0, 0.0),
        (1.0, 1.0),
        (2.0, 1.0),
        (2.0, 2.0),
    ]
    tracker = MobilityMetricTracker()
    prefix: list[tuple[float, float]] = []
    for p in pts:
        prefix.append(p)
        tracker.update(p)
        assert math.isclose(
            tracker.heading_change_rate,
            compute_heading_change_rate(prefix),
            rel_tol=1e-6,
        )
        assert math.isclose(
            tracker.path_curvature,
            compute_path_curvature(prefix),
            rel_tol=1e-6,
        )
