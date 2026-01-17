import math

# Earth's mean radius in meters (used in Haversine formula)
EARTH_RADIUS_METERS = 6371e3


def distance(lat1, lon1, lat2, lon2):
    """Calculate great-circle distance using Haversine formula.
    
    Determines the distance between two points on Earth given their
    longitudes and latitudes.
    
    Returns:
        Distance in meters.
    """
    R = EARTH_RADIUS_METERS
    φ1 = lat1 * math.pi / 180  # φ, λ in radians
    φ2 = lat2 * math.pi / 180
    Δλ = (lon2 - lon1) * math.pi / 180
    Δφ = (lat2 - lat1) * math.pi / 180

    a = math.sin(Δφ / 2) * math.sin(Δφ / 2) + math.cos(φ1) * math.cos(φ2) * math.sin(Δλ / 2) * math.sin(Δλ / 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    d = R * c  # in metres

    return d

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
