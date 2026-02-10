# services/nef-emulator/backend/app/app/core/geo_utils.py
"""Geographic utilities for distance and coordinate calculations.

Consolidates haversine and coordinate conversion functions that were
duplicated across distance.py, runtime.py, and unit_verification.py.
"""

import math
from typing import Tuple


# Earth radius in meters
EARTH_RADIUS_M = 6_371_000


def haversine_distance(
    lat1: float, lon1: float,
    lat2: float, lon2: float,
) -> float:
    """Calculate great-circle distance between two points using Haversine formula.
    
    Args:
        lat1, lon1: First point coordinates in degrees.
        lat2, lon2: Second point coordinates in degrees.
    
    Returns:
        Distance in meters.
    """
    # Convert to radians
    lat1_r, lon1_r = math.radians(lat1), math.radians(lon1)
    lat2_r, lon2_r = math.radians(lat2), math.radians(lon2)
    
    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r
    
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))
    
    return EARTH_RADIUS_M * c


def latlon_to_local_meters(
    lat: float, lon: float,
    ref_lat: float, ref_lon: float,
) -> Tuple[float, float]:
    """Convert lat/lon to local Cartesian coordinates (x, y) in meters.
    
    Uses equirectangular approximation, suitable for small areas.
    
    Args:
        lat, lon: Point coordinates in degrees.
        ref_lat, ref_lon: Reference origin in degrees.
    
    Returns:
        Tuple (x, y) in meters relative to reference point.
    """
    lat_r = math.radians(lat)
    lon_r = math.radians(lon)
    ref_lat_r = math.radians(ref_lat)
    ref_lon_r = math.radians(ref_lon)
    
    x = EARTH_RADIUS_M * (lon_r - ref_lon_r) * math.cos(ref_lat_r)
    y = EARTH_RADIUS_M * (lat_r - ref_lat_r)
    
    return (x, y)


def euclidean_distance_3d(
    pos1: Tuple[float, float, float],
    pos2: Tuple[float, float, float],
) -> float:
    """Calculate 3D Euclidean distance between two points.
    
    Args:
        pos1: First point (x, y, z).
        pos2: Second point (x, y, z).
    
    Returns:
        Distance in same units as input.
    """
    return math.sqrt(
        (pos2[0] - pos1[0]) ** 2 +
        (pos2[1] - pos1[1]) ** 2 +
        (pos2[2] - pos1[2]) ** 2
    )


def euclidean_distance_2d(
    x1: float, y1: float,
    x2: float, y2: float,
) -> float:
    """Calculate 2D Euclidean distance between two points.
    
    Args:
        x1, y1: First point coordinates.
        x2, y2: Second point coordinates.
    
    Returns:
        Distance in same units as input.
    """
    return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
