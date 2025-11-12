"""Static cell configuration for geographic validation."""
from __future__ import annotations

from math import atan2, cos, radians, sin, sqrt
from typing import Dict

# Synthetic grid aligned with the training generator (0-1000 x, 0-866 y)
CELL_CONFIGS: Dict[str, Dict[str, float]] = {
    "antenna_1": {
        "id": "antenna_1",
        "latitude": 0.0,
        "longitude": 0.0,
        "radius_meters": 600.0,
        "max_distance_multiplier": 2.0,
    },
    "antenna_2": {
        "id": "antenna_2",
        "latitude": 1000.0,
        "longitude": 0.0,
        "radius_meters": 600.0,
        "max_distance_multiplier": 2.0,
    },
    "antenna_3": {
        "id": "antenna_3",
        "latitude": 0.0,
        "longitude": 866.0,
        "radius_meters": 600.0,
        "max_distance_multiplier": 2.0,
    },
    "antenna_4": {
        "id": "antenna_4",
        "latitude": 1000.0,
        "longitude": 866.0,
        "radius_meters": 600.0,
        "max_distance_multiplier": 2.0,
    },
}


def get_cell_config(antenna_id: str) -> Dict[str, float] | None:
    """Return configuration for ``antenna_id`` if known."""
    return CELL_CONFIGS.get(antenna_id)


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two latitude/longitude pairs (meters)."""

    r = 6_371_000.0  # Earth radius in meters

    lat1_rad = radians(lat1)
    lat2_rad = radians(lat2)
    delta_lat = radians(lat2 - lat1)
    delta_lon = radians(lon2 - lon1)

    a = sin(delta_lat / 2.0) ** 2 + cos(lat1_rad) * cos(lat2_rad) * sin(delta_lon / 2.0) ** 2
    c = 2.0 * atan2(sqrt(a), sqrt(max(0.0, 1.0 - a)))
    return r * c
