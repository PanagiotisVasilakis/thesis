"""UE category classification utilities for training data stratification.

This module provides functions to classify UEs into mobility categories
based on speed patterns and naming conventions. This enables stratified
sampling during data collection to ensure balanced training data.

Categories:
    - car: Vehicles (15-120 km/h)
    - pedestrian: Walking users (0-7 km/h)
    - cyclist: Cyclists (7-25 km/h)
    - drone: UAVs (high altitude variations)
    - iot_sensor: Stationary IoT devices (0 km/h)
"""
from __future__ import annotations

import re
from typing import Dict, Any, Optional, Tuple

# Speed thresholds in m/s for category detection
SPEED_THRESHOLDS = {
    "stationary": 0.5,       # Less than 0.5 m/s = stationary
    "pedestrian_max": 2.0,   # Up to 2 m/s (7.2 km/h)
    "cyclist_max": 7.0,      # Up to 7 m/s (25 km/h)
    "car_max": 35.0,         # Up to 35 m/s (126 km/h)
}

# Pattern-based classification from UE naming conventions
UE_NAME_PATTERNS = {
    "car": re.compile(r"(car|vehicle|auto|truck|bus)", re.IGNORECASE),
    "pedestrian": re.compile(r"(pedestrian|ped|walk|person|human)", re.IGNORECASE),
    "cyclist": re.compile(r"(cyclist|bike|bicycle|cycling)", re.IGNORECASE),
    "drone": re.compile(r"(drone|uav|aerial|flying)", re.IGNORECASE),
    "iot_sensor": re.compile(r"(iot|sensor|device|meter|static)", re.IGNORECASE),
}


def classify_ue_by_name(ue_id: str) -> Optional[str]:
    """Classify UE based on its identifier/name.
    
    Args:
        ue_id: UE identifier string
        
    Returns:
        Category name if pattern matches, None otherwise
    """
    for category, pattern in UE_NAME_PATTERNS.items():
        if pattern.search(ue_id):
            return category
    return None


def classify_ue_by_speed(speed: Optional[float]) -> str:
    """Classify UE based on current speed.
    
    Args:
        speed: Current speed in m/s
        
    Returns:
        Category name based on speed thresholds
    """
    if speed is None or speed < SPEED_THRESHOLDS["stationary"]:
        return "iot_sensor"
    elif speed < SPEED_THRESHOLDS["pedestrian_max"]:
        return "pedestrian"
    elif speed < SPEED_THRESHOLDS["cyclist_max"]:
        return "cyclist"
    elif speed < SPEED_THRESHOLDS["car_max"]:
        return "car"
    else:
        # Very high speed - likely a drone or vehicle
        return "car"


def classify_ue_by_altitude(
    altitude: Optional[float],
    altitude_variance: Optional[float] = None,
) -> Optional[str]:
    """Classify UE based on altitude patterns (for drone detection).
    
    Args:
        altitude: Current altitude in meters
        altitude_variance: Variance in altitude over time
        
    Returns:
        "drone" if altitude patterns indicate aerial device, None otherwise
    """
    if altitude is None:
        return None
    
    # Drones typically operate above ground level
    if altitude > 10.0:  # More than 10m above ground
        return "drone"
    
    # High altitude variance indicates flying
    if altitude_variance is not None and altitude_variance > 5.0:
        return "drone"
    
    return None


def get_ue_category(
    ue_id: str,
    speed: Optional[float] = None,
    altitude: Optional[float] = None,
    altitude_variance: Optional[float] = None,
) -> Tuple[str, str]:
    """Determine UE category using multiple classification methods.
    
    Uses a priority-based approach:
    1. Altitude-based classification (for drones)
    2. Name-based classification (from UE ID patterns)
    3. Speed-based classification (fallback)
    
    Args:
        ue_id: UE identifier
        speed: Current speed in m/s
        altitude: Current altitude in meters
        altitude_variance: Altitude variance over time
        
    Returns:
        Tuple of (category: str, classification_method: str)
    """
    # Priority 1: Check for drone by altitude
    if altitude is not None:
        drone_check = classify_ue_by_altitude(altitude, altitude_variance)
        if drone_check == "drone":
            return "drone", "altitude"
    
    # Priority 2: Check name patterns
    name_category = classify_ue_by_name(ue_id)
    if name_category:
        return name_category, "name_pattern"
    
    # Priority 3: Use speed-based classification
    speed_category = classify_ue_by_speed(speed)
    return speed_category, "speed"


def get_category_statistics(samples: list) -> Dict[str, Dict[str, Any]]:
    """Calculate statistics per UE category from a list of samples.
    
    Args:
        samples: List of training samples with ue_category field
        
    Returns:
        Dictionary mapping category to statistics
    """
    from collections import defaultdict
    
    category_counts: Dict[str, int] = defaultdict(int)
    category_samples: Dict[str, list] = defaultdict(list)
    
    for sample in samples:
        category = sample.get("ue_category", "unknown")
        category_counts[category] += 1
        category_samples[category].append(sample)
    
    total = len(samples)
    stats = {}
    
    for category, count in category_counts.items():
        samples_in_cat = category_samples[category]
        stats[category] = {
            "count": count,
            "percentage": (count / total * 100) if total > 0 else 0,
            "positive_samples": sum(1 for s in samples_in_cat if s.get("sample_type") == "positive"),
            "negative_samples": sum(1 for s in samples_in_cat if s.get("sample_type") == "negative"),
        }
    
    return stats
