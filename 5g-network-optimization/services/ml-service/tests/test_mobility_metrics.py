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


def test_mobility_metric_tracker_basic():
    tracker = MobilityMetricTracker(window_size=3)
    r, c = tracker.update_position("ue", 0, 0)
    assert (r, c) == (0.0, 0.0)
    r, c = tracker.update_position("ue", 1, 0)
    assert (r, c) == (0.0, 0.0)
    r, c = tracker.update_position("ue", 1, 1)
    assert math.isclose(r, math.pi / 2, rel_tol=1e-6)
    assert math.isclose(c, math.pi / 4, rel_tol=1e-6)


def test_mobility_metric_tracker_window():
    tracker = MobilityMetricTracker(window_size=2)
    tracker.update_position("ue", 0, 0)
    tracker.update_position("ue", 1, 0)
    r, c = tracker.update_position("ue", 1, 1)
    # only last two positions retained -> insufficient for metrics
    assert (r, c) == (0.0, 0.0)


def test_mobility_metric_tracker_invalid():
    tracker = MobilityMetricTracker(window_size=3)
    r, c = tracker.update_position("ue", "bad", None)
    assert (r, c) == (0.0, 0.0)
