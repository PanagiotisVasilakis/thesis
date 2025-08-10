"""Built-in feature transformations for 5G network optimization."""

import logging
import math
import numpy as np
from typing import Dict, Any, List, Optional, Tuple

from .transformation_registry import (
    TransformationRegistry, 
    FeatureTransformation, 
    TransformationMetadata,
    TransformationCategory,
    TransformationPriority,
    register_transformation,
    get_transformation_registry
)

logger = logging.getLogger(__name__)


# Spatial/Geographic Transformations
@register_transformation(
    name="normalize_coordinates",
    category="spatial",
    priority=1,
    description="Normalize latitude/longitude coordinates to 0-1 range",
    input_features=["latitude", "longitude"],
    output_features=["latitude_norm", "longitude_norm"]
)
def normalize_coordinates(features: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Normalize coordinates to 0-1 range."""
    lat = features.get("latitude", 0)
    lon = features.get("longitude", 0)
    
    # Normalize latitude (-90 to 90) to (0 to 1)
    lat_norm = (lat + 90) / 180
    
    # Normalize longitude (-180 to 180) to (0 to 1)  
    lon_norm = (lon + 180) / 360
    
    return {
        "latitude_norm": lat_norm,
        "longitude_norm": lon_norm
    }


@register_transformation(
    name="calculate_distance_to_center",
    category="spatial", 
    priority=2,
    description="Calculate distance from UE to network center",
    input_features=["latitude", "longitude"],
    output_features=["distance_to_center", "bearing_to_center"]
)
def calculate_distance_to_center(features: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Calculate distance and bearing to network center."""
    lat = features.get("latitude", 0)
    lon = features.get("longitude", 0)
    
    # Default network center (could be configurable)
    center_lat = context.get("center_lat", 0) if context else 0
    center_lon = context.get("center_lon", 0) if context else 0
    
    # Haversine distance calculation
    def haversine_distance(lat1, lon1, lat2, lon2):
        R = 6371  # Earth's radius in kilometers
        
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        
        a = (math.sin(dlat/2) * math.sin(dlat/2) + 
             math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * 
             math.sin(dlon/2) * math.sin(dlon/2))
        
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        return R * c
    
    # Calculate bearing
    def calculate_bearing(lat1, lon1, lat2, lon2):
        lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
        
        dlon = lon2 - lon1
        y = math.sin(dlon) * math.cos(lat2)
        x = (math.cos(lat1) * math.sin(lat2) - 
             math.sin(lat1) * math.cos(lat2) * math.cos(dlon))
        
        bearing = math.atan2(y, x)
        return (math.degrees(bearing) + 360) % 360
    
    distance = haversine_distance(lat, lon, center_lat, center_lon)
    bearing = calculate_bearing(lat, lon, center_lat, center_lon)
    
    return {
        "distance_to_center": distance,
        "bearing_to_center": bearing
    }


@register_transformation(
    name="spatial_clustering",
    category="spatial",
    priority=3,
    description="Assign UE to spatial cluster based on position",
    input_features=["latitude", "longitude"],
    output_features=["spatial_cluster", "cluster_distance"]
)
def spatial_clustering(features: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Assign UE to spatial cluster."""
    lat = features.get("latitude", 0)
    lon = features.get("longitude", 0)
    
    # Simple grid-based clustering (could be enhanced with k-means)
    grid_size = context.get("grid_size", 100) if context else 100  # meters
    
    # Convert to grid coordinates
    grid_x = int(lat * 111320 / grid_size)  # Approximate meters per degree latitude
    grid_y = int(lon * 111320 * math.cos(math.radians(lat)) / grid_size)  # Adjusted for longitude
    
    cluster_id = f"cluster_{grid_x}_{grid_y}"
    
    # Distance to cluster center
    cluster_center_lat = grid_x * grid_size / 111320
    cluster_center_lon = grid_y * grid_size / (111320 * math.cos(math.radians(lat)))
    
    cluster_distance = math.sqrt((lat - cluster_center_lat)**2 + (lon - cluster_center_lon)**2) * 111320
    
    return {
        "spatial_cluster": cluster_id,
        "cluster_distance": cluster_distance
    }


# Signal Processing Transformations
@register_transformation(
    name="signal_quality_score",
    category="signal",
    priority=2,
    description="Calculate composite signal quality score",
    input_features=["rsrp_current", "sinr_current", "rsrq_current"],
    output_features=["signal_quality_score", "signal_grade"]
)
def signal_quality_score(features: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Calculate composite signal quality score."""
    rsrp = features.get("rsrp_current", -120)
    sinr = features.get("sinr_current", 0)
    rsrq = features.get("rsrq_current", -30)
    
    # Normalize signal values to 0-1 range
    # RSRP: -120 to -60 dBm
    rsrp_norm = max(0, min(1, (rsrp + 120) / 60))
    
    # SINR: -10 to 30 dB
    sinr_norm = max(0, min(1, (sinr + 10) / 40))
    
    # RSRQ: -30 to -5 dB
    rsrq_norm = max(0, min(1, (rsrq + 30) / 25))
    
    # Weighted composite score
    score = (0.4 * rsrp_norm + 0.4 * sinr_norm + 0.2 * rsrq_norm)
    
    # Signal grade based on score
    if score >= 0.8:
        grade = "excellent"
    elif score >= 0.6:
        grade = "good"
    elif score >= 0.4:
        grade = "fair"
    elif score >= 0.2:
        grade = "poor"
    else:
        grade = "very_poor"
    
    return {
        "signal_quality_score": score,
        "signal_grade": grade
    }


@register_transformation(
    name="signal_stability",
    category="signal",
    priority=3,
    description="Calculate signal stability metrics",
    input_features=["rsrp_stddev", "sinr_stddev"],
    output_features=["signal_stability_score", "stability_class"]
)
def signal_stability(features: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Calculate signal stability metrics."""
    rsrp_std = features.get("rsrp_stddev", 0)
    sinr_std = features.get("sinr_stddev", 0)
    
    # Stability score (lower stddev = higher stability)
    # Normalize based on typical ranges
    rsrp_stability = max(0, 1 - rsrp_std / 10)  # Assume max stddev of 10 dB
    sinr_stability = max(0, 1 - sinr_std / 5)   # Assume max stddev of 5 dB
    
    stability_score = (rsrp_stability + sinr_stability) / 2
    
    # Classify stability
    if stability_score >= 0.8:
        stability_class = "very_stable"
    elif stability_score >= 0.6:
        stability_class = "stable"
    elif stability_score >= 0.4:
        stability_class = "moderate"
    elif stability_score >= 0.2:
        stability_class = "unstable"
    else:
        stability_class = "very_unstable"
    
    return {
        "signal_stability_score": stability_score,
        "stability_class": stability_class
    }


@register_transformation(
    name="neighbor_analysis",
    category="signal",
    priority=3,
    description="Analyze neighbor cell signal patterns",
    input_features=["best_rsrp_diff", "best_sinr_diff", "best_rsrq_diff"],
    output_features=["handover_readiness", "neighbor_advantage", "coverage_overlap"]
)
def neighbor_analysis(features: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Analyze neighbor cell signal patterns."""
    rsrp_diff = features.get("best_rsrp_diff", 0)
    sinr_diff = features.get("best_sinr_diff", 0)
    rsrq_diff = features.get("best_rsrq_diff", 0)
    
    # Calculate neighbor advantage
    neighbor_advantage = (0.5 * rsrp_diff + 0.3 * sinr_diff + 0.2 * rsrq_diff)
    
    # Handover readiness based on signal differences
    handover_threshold = context.get("handover_threshold", 3) if context else 3
    
    if neighbor_advantage >= handover_threshold:
        handover_readiness = "ready"
    elif neighbor_advantage >= handover_threshold / 2:
        handover_readiness = "preparing"
    else:
        handover_readiness = "stable"
    
    # Coverage overlap indicator
    if rsrp_diff > 0 and sinr_diff > 0:
        coverage_overlap = "strong"
    elif rsrp_diff > 0 or sinr_diff > 0:
        coverage_overlap = "moderate"
    else:
        coverage_overlap = "weak"
    
    return {
        "handover_readiness": handover_readiness,
        "neighbor_advantage": neighbor_advantage,
        "coverage_overlap": coverage_overlap
    }


# Mobility Transformations
@register_transformation(
    name="mobility_classification",
    category="mobility",
    priority=2,
    description="Classify UE mobility patterns",
    input_features=["speed", "heading_change_rate", "path_curvature"],
    output_features=["mobility_class", "movement_pattern", "mobility_score"]
)
def mobility_classification(features: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Classify UE mobility patterns."""
    speed = features.get("speed", 0)
    heading_change = features.get("heading_change_rate", 0)
    curvature = features.get("path_curvature", 0)
    
    # Mobility classification based on speed
    if speed < 1:
        mobility_class = "stationary"
    elif speed < 5:
        mobility_class = "pedestrian"
    elif speed < 30:
        mobility_class = "vehicle_slow"
    elif speed < 60:
        mobility_class = "vehicle_medium"
    else:
        mobility_class = "vehicle_fast"
    
    # Movement pattern based on heading change and curvature
    if abs(heading_change) < 0.1 and abs(curvature) < 0.1:
        movement_pattern = "straight_line"
    elif abs(heading_change) < 0.5:
        movement_pattern = "gentle_curve"
    elif abs(heading_change) < 1.0:
        movement_pattern = "moderate_turn"
    else:
        movement_pattern = "sharp_turn"
    
    # Mobility score (combination of speed and direction changes)
    mobility_score = speed * (1 + abs(heading_change) + abs(curvature))
    
    return {
        "mobility_class": mobility_class,
        "movement_pattern": movement_pattern,
        "mobility_score": mobility_score
    }


@register_transformation(
    name="predictive_mobility",
    category="mobility",
    priority=3,
    description="Predict future position and mobility",
    input_features=["speed", "direction_x", "direction_y", "acceleration"],
    output_features=["predicted_x_5s", "predicted_y_5s", "mobility_trend"]
)
def predictive_mobility(features: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Predict future position and mobility trends."""
    speed = features.get("speed", 0)
    dir_x = features.get("direction_x", 0)
    dir_y = features.get("direction_y", 0)
    acceleration = features.get("acceleration", 0)
    
    # Simple kinematic prediction for 5 seconds ahead
    time_horizon = 5  # seconds
    
    # Current velocity components
    vel_x = speed * dir_x
    vel_y = speed * dir_y
    
    # Predicted position (assuming constant acceleration)
    predicted_x = vel_x * time_horizon + 0.5 * acceleration * dir_x * time_horizon**2
    predicted_y = vel_y * time_horizon + 0.5 * acceleration * dir_y * time_horizon**2
    
    # Mobility trend
    if acceleration > 1:
        mobility_trend = "accelerating"
    elif acceleration < -1:
        mobility_trend = "decelerating"
    elif speed > 10:
        mobility_trend = "high_speed"
    elif speed > 1:
        mobility_trend = "moderate_speed"
    else:
        mobility_trend = "low_speed"
    
    return {
        "predicted_x_5s": predicted_x,
        "predicted_y_5s": predicted_y,
        "mobility_trend": mobility_trend
    }


# Network Topology Transformations
@register_transformation(
    name="network_load_analysis",
    category="network",
    priority=2,
    description="Analyze network load and capacity",
    input_features=["cell_load", "handover_count", "time_since_handover"],
    output_features=["load_pressure", "handover_frequency", "stability_indicator"]
)
def network_load_analysis(features: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Analyze network load and capacity metrics."""
    cell_load = features.get("cell_load", 0)
    handover_count = features.get("handover_count", 0)
    time_since_handover = features.get("time_since_handover", 0)
    
    # Load pressure classification
    if cell_load < 0.3:
        load_pressure = "low"
    elif cell_load < 0.6:
        load_pressure = "moderate"
    elif cell_load < 0.8:
        load_pressure = "high"
    else:
        load_pressure = "critical"
    
    # Handover frequency (handovers per hour)
    if time_since_handover > 0:
        handover_frequency = handover_count / (time_since_handover / 3600)
    else:
        handover_frequency = 0
    
    # Stability indicator
    if handover_frequency < 1 and cell_load < 0.7:
        stability_indicator = "stable"
    elif handover_frequency < 3 and cell_load < 0.8:
        stability_indicator = "moderate"
    else:
        stability_indicator = "unstable"
    
    return {
        "load_pressure": load_pressure,
        "handover_frequency": handover_frequency,
        "stability_indicator": stability_indicator
    }


# Temporal Transformations
@register_transformation(
    name="temporal_features",
    category="temporal",
    priority=1,
    description="Extract temporal features from timestamp",
    input_features=["timestamp"],
    output_features=["hour_of_day", "day_of_week", "is_weekend", "time_period"]
)
def temporal_features(features: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Extract temporal features from timestamp."""
    import datetime
    
    timestamp = features.get("timestamp")
    if timestamp is None:
        # Use current time if no timestamp provided
        dt = datetime.datetime.now()
    elif isinstance(timestamp, str):
        # Parse ISO format timestamp
        dt = datetime.datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
    elif isinstance(timestamp, (int, float)):
        # Unix timestamp
        dt = datetime.datetime.fromtimestamp(timestamp)
    else:
        dt = timestamp
    
    hour_of_day = dt.hour
    day_of_week = dt.weekday()  # 0=Monday, 6=Sunday
    is_weekend = day_of_week >= 5
    
    # Time period classification
    if 6 <= hour_of_day < 9:
        time_period = "morning_rush"
    elif 9 <= hour_of_day < 17:
        time_period = "business_hours"
    elif 17 <= hour_of_day < 20:
        time_period = "evening_rush"
    elif 20 <= hour_of_day < 23:
        time_period = "evening"
    else:
        time_period = "night"
    
    return {
        "hour_of_day": hour_of_day,
        "day_of_week": day_of_week,
        "is_weekend": is_weekend,
        "time_period": time_period
    }


# Statistical Transformations
@register_transformation(
    name="feature_statistics",
    category="statistical",
    priority=4,
    description="Calculate statistical aggregations of features",
    input_features=["rsrp_current", "sinr_current", "speed"],
    output_features=["signal_mean", "signal_variance", "speed_zscore"]
)
def feature_statistics(features: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Calculate statistical aggregations."""
    rsrp = features.get("rsrp_current", -120)
    sinr = features.get("sinr_current", 0)
    speed = features.get("speed", 0)
    
    # Signal statistics
    signal_values = [rsrp, sinr]
    signal_mean = np.mean(signal_values)
    signal_variance = np.var(signal_values)
    
    # Speed z-score (assuming population mean=20, std=15)
    speed_mean = context.get("speed_mean", 20) if context else 20
    speed_std = context.get("speed_std", 15) if context else 15
    speed_zscore = (speed - speed_mean) / speed_std if speed_std > 0 else 0
    
    return {
        "signal_mean": signal_mean,
        "signal_variance": signal_variance,
        "speed_zscore": speed_zscore
    }


def register_all_builtin_transformations() -> None:
    """Register all built-in transformations with the registry."""
    registry = get_transformation_registry()
    
    # The transformations are automatically registered via decorators
    # when this module is imported
    
    transformations = [
        "normalize_coordinates",
        "calculate_distance_to_center", 
        "spatial_clustering",
        "signal_quality_score",
        "signal_stability",
        "neighbor_analysis",
        "mobility_classification",
        "predictive_mobility",
        "network_load_analysis",
        "temporal_features",
        "feature_statistics"
    ]
    
    registered_count = 0
    for name in transformations:
        if registry.get_transformation(name) is not None:
            registered_count += 1
    
    logger.info(f"Built-in transformations registered: {registered_count}/{len(transformations)}")
    
    return registered_count