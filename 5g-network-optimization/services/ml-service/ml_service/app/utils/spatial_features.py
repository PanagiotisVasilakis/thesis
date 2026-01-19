"""Spatial feature calculation utilities.

This module provides geospatial calculations for antenna selection,
including distance to antennas, angles, and movement direction analysis.

These features add physics-based spatial awareness to handover decisions,
allowing the model to consider whether the UE is moving toward or away
from potential target antennas.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Optional, Tuple, List

# Earth radius in meters (for Haversine formula)
EARTH_RADIUS_M = 6371000.0


def haversine_distance(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    """Calculate distance between two points using Haversine formula.
    
    Args:
        lat1, lon1: First point coordinates (degrees)
        lat2, lon2: Second point coordinates (degrees)
        
    Returns:
        Distance in meters
    """
    # Convert to radians
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    
    # Haversine formula
    a = (
        math.sin(delta_lat / 2) ** 2 +
        math.cos(lat1_rad) * math.cos(lat2_rad) *
        math.sin(delta_lon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    return EARTH_RADIUS_M * c


def calculate_bearing(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    """Calculate initial bearing from point 1 to point 2.
    
    Args:
        lat1, lon1: Starting point (degrees)
        lat2, lon2: End point (degrees)
        
    Returns:
        Bearing in degrees (0-360, 0=North, 90=East)
    """
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lon = math.radians(lon2 - lon1)
    
    x = math.sin(delta_lon) * math.cos(lat2_rad)
    y = (
        math.cos(lat1_rad) * math.sin(lat2_rad) -
        math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(delta_lon)
    )
    
    bearing = math.degrees(math.atan2(x, y))
    return (bearing + 360) % 360


def angle_difference(angle1: float, angle2: float) -> float:
    """Calculate the signed difference between two angles.
    
    Args:
        angle1: First angle in degrees
        angle2: Second angle in degrees
        
    Returns:
        Signed difference in degrees (-180 to 180)
    """
    diff = angle2 - angle1
    while diff > 180:
        diff -= 360
    while diff < -180:
        diff += 360
    return diff


def compute_spatial_features(
    ue_lat: float,
    ue_lon: float,
    ue_heading: Optional[float],
    ue_speed: Optional[float],
    target_lat: float,
    target_lon: float,
    current_lat: Optional[float] = None,
    current_lon: Optional[float] = None,
) -> Dict[str, float]:
    """Compute spatial features for handover prediction.
    
    Args:
        ue_lat, ue_lon: UE current position
        ue_heading: UE heading in degrees (0=North, 90=East)
        ue_speed: UE speed in m/s
        target_lat, target_lon: Target antenna position
        current_lat, current_lon: Current connected antenna position (optional)
        
    Returns:
        Dictionary of spatial features:
            - distance_to_target: Distance to target antenna (m)
            - distance_to_current: Distance to current antenna (m)
            - angle_to_target: Angle from heading to target (-180 to 180)
            - relative_distance_ratio: target_dist / current_dist
            - moving_toward_target: Cosine of angle to target (-1 to 1)
    """
    result = {
        "distance_to_target": 0.0,
        "distance_to_current": 0.0,
        "angle_to_target": 0.0,
        "relative_distance_ratio": 1.0,
        "moving_toward_target": 0.0,
    }
    
    # Calculate distance to target
    dist_to_target = haversine_distance(ue_lat, ue_lon, target_lat, target_lon)
    result["distance_to_target"] = dist_to_target
    
    # Calculate distance to current antenna
    if current_lat is not None and current_lon is not None:
        dist_to_current = haversine_distance(ue_lat, ue_lon, current_lat, current_lon)
        result["distance_to_current"] = dist_to_current
        
        # Relative distance ratio (< 1 means target is closer)
        if dist_to_current > 0:
            result["relative_distance_ratio"] = min(10.0, dist_to_target / dist_to_current)
        else:
            result["relative_distance_ratio"] = 1.0
    
    # Calculate bearing to target
    bearing_to_target = calculate_bearing(ue_lat, ue_lon, target_lat, target_lon)
    
    # Calculate angle from heading to target
    if ue_heading is not None:
        result["angle_to_target"] = angle_difference(ue_heading, bearing_to_target)
        
        # Moving toward target: cosine of angle (1 = directly toward, -1 = away)
        angle_rad = math.radians(result["angle_to_target"])
        result["moving_toward_target"] = math.cos(angle_rad)
    
    return result


def get_antenna_positions() -> Dict[str, Tuple[float, float]]:
    """Get known antenna positions.
    
    In a real system, this would be loaded from configuration or database.
    These are example positions for the simulation environment.
    
    Returns:
        Dictionary mapping antenna_id to (latitude, longitude)
    """
    # Default positions for simulation - would be loaded from config in production
    return {
        "gNB1": (37.7749, -122.4194),
        "gNB2": (37.7849, -122.4094),
        "gNB3": (37.7649, -122.4094),
        "gNB4": (37.7749, -122.3994),
        "gNB5": (37.7749, -122.4394),
        # Add more as needed
    }


def compute_all_antenna_features(
    ue_lat: float,
    ue_lon: float,
    ue_heading: Optional[float],
    ue_speed: Optional[float],
    target_antenna_id: str,
    current_antenna_id: Optional[str] = None,
    antenna_positions: Optional[Dict[str, Tuple[float, float]]] = None,
) -> Dict[str, float]:
    """Compute spatial features using antenna database.
    
    Args:
        ue_lat, ue_lon: UE position
        ue_heading: UE heading
        ue_speed: UE speed
        target_antenna_id: Target antenna ID
        current_antenna_id: Current connected antenna ID
        antenna_positions: Optional custom antenna positions
        
    Returns:
        Dictionary of computed spatial features
    """
    if antenna_positions is None:
        antenna_positions = get_antenna_positions()
    
    # Get target antenna position
    target_pos = antenna_positions.get(target_antenna_id)
    if target_pos is None:
        # Return default values if antenna not found
        return {
            "distance_to_target": 500.0,
            "distance_to_current": 500.0,
            "angle_to_target": 0.0,
            "relative_distance_ratio": 1.0,
            "moving_toward_target": 0.0,
        }
    
    # Get current antenna position
    current_pos = None
    if current_antenna_id:
        current_pos = antenna_positions.get(current_antenna_id)
    
    return compute_spatial_features(
        ue_lat=ue_lat,
        ue_lon=ue_lon,
        ue_heading=ue_heading,
        ue_speed=ue_speed,
        target_lat=target_pos[0],
        target_lon=target_pos[1],
        current_lat=current_pos[0] if current_pos else None,
        current_lon=current_pos[1] if current_pos else None,
    )
