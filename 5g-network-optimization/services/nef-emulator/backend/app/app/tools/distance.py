"""Distance calculation utilities for cell coverage."""
from app.core.geo_utils import haversine_distance

# Deprecated: Use haversine_distance from geo_utils directly
# This module is kept for backward compatibility

def distance(lat1, lon1, lat2, lon2):
    """Calculate great-circle distance using Haversine formula.
    
    DEPRECATED: Use app.core.geo_utils.haversine_distance instead.
    
    Returns:
        Distance in meters.
    """
    return haversine_distance(lat1, lon1, lat2, lon2)

def check_distance(UE_lat, UE_long, cells):
    """Find the closest cell that covers the UE's position.
    
    Args:
        UE_lat: UE's latitude in degrees.
        UE_long: UE's longitude in degrees.
        cells: List of cell dictionaries with 'latitude', 'longitude', 'radius' keys.
    
    Returns:
        The closest cell dict if UE is within any cell's radius, None otherwise.
        Returns None when UE is outside all cell coverage areas (out of coverage).
    """
    current_cell = None      
    current_cell_dist = float("inf")

    for cell in cells:
        lat = cell.get("latitude")
        lon = cell.get("longitude")
        radius = cell.get("radius")
        if lat is None or lon is None or radius is None:
            continue

        dist = distance(UE_lat, UE_long, lat, lon)
        if dist <= radius:
            if dist < current_cell_dist:
                current_cell_dist = dist
                current_cell = cell
    
    return current_cell
