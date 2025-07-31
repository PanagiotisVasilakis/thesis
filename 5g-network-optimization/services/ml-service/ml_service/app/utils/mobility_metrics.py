"""Utilities for computing mobility-related metrics."""

from collections.abc import Sequence
import math

from collections import defaultdict, deque

__all__ = [
    "compute_heading_change_rate",
    "compute_path_curvature",
    "MobilityMetricTracker",
]


def compute_heading_change_rate(positions: Sequence[tuple[float, float]]) -> float:
    """Return the average rate of heading change between consecutive segments.

    Parameters
    ----------
    positions:
        Ordered sequence of ``(x, y)`` coordinates. At least three points
        are required to compute a non-zero rate.

    Returns
    -------
    float
        Average absolute change in heading (radians) between successive
        segments. Returns ``0.0`` when fewer than three valid positions are
        provided.
    """
    if len(positions) < 3:
        return 0.0

    headings = []
    for i in range(len(positions) - 1):
        p1 = positions[i]
        p2 = positions[i + 1]
        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        if dx == 0 and dy == 0:
            headings.append(None)
        else:
            headings.append(math.atan2(dy, dx))

    valid_headings = [h for h in headings if h is not None]
    if len(valid_headings) < 2:
        return 0.0

    total_change = 0.0
    count = 0
    prev = valid_headings[0]
    for h in valid_headings[1:]:
        # normalise difference to [-pi, pi]
        diff = (h - prev + math.pi) % (2 * math.pi) - math.pi
        total_change += abs(diff)
        prev = h
        count += 1
    return total_change / count if count else 0.0


def compute_path_curvature(positions: Sequence[tuple[float, float]]) -> float:
    """Return a simple curvature metric for the given path.

    Parameters
    ----------
    positions:
        Ordered sequence of ``(x, y)`` coordinates. At least three points
        are required to compute a non-zero curvature.

    Returns
    -------
    float
        Sum of absolute turning angles divided by total path length. A
        straight path yields ``0.0`` while sharper turns increase the value.
    """
    if len(positions) < 3:
        return 0.0

    path_length = 0.0
    total_angle = 0.0
    for i in range(1, len(positions)):
        p_prev = positions[i - 1]
        p_curr = positions[i]
        seg_len = math.hypot(p_curr[0] - p_prev[0], p_curr[1] - p_prev[1])
        path_length += seg_len

    for i in range(1, len(positions) - 1):
        p_prev = positions[i - 1]
        p = positions[i]
        p_next = positions[i + 1]
        v1 = (p[0] - p_prev[0], p[1] - p_prev[1])
        v2 = (p_next[0] - p[0], p_next[1] - p[1])
        len1 = math.hypot(*v1)
        len2 = math.hypot(*v2)
        if len1 == 0 or len2 == 0:
            continue
        dot = v1[0] * v2[0] + v1[1] * v2[1]
        cos_ang = max(-1.0, min(1.0, dot / (len1 * len2)))
        angle = math.acos(cos_ang)
        total_angle += abs(angle)

    return 0.0 if path_length == 0 else total_angle / path_length


class MobilityMetricTracker:
    """Track recent UE positions and compute mobility metrics incrementally."""

    def __init__(self, window_size: int = 5) -> None:
        self.window_size = window_size
        # mapping of UE id to deque of recent (lat, lon) samples
        self._positions: dict[str, deque[tuple[float, float]]] = defaultdict(
            lambda: deque(maxlen=self.window_size)
        )

    def update_position(self, ue_id: str, lat: float, lon: float) -> tuple[float, float]:
        """Add a new position and return updated heading change rate and curvature."""
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            buf = self._positions.get(ue_id)
            if buf is None:
                return 0.0, 0.0
            return (
                compute_heading_change_rate(buf),
                compute_path_curvature(buf),
            )

        buf = self._positions[ue_id]
        buf.append((float(lat), float(lon)))

        return compute_heading_change_rate(buf), compute_path_curvature(buf)
