"""Reusable feature extraction pipeline."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple, List
import threading

from .transform_registry import apply_feature_transforms
from ..config.constants import (
    DEFAULT_FALLBACK_RSRP,
    DEFAULT_FALLBACK_SINR,
    DEFAULT_FALLBACK_RSRQ,
)
from ..utils.feature_cache import _cached_direction_to_unit, _cached_signal_extraction

__all__ = [
    "extract_rf_features",
    "extract_environment_features",
    "extract_mobility_features",
    "determine_optimal_antenna",
    "build_model_features",
]


def extract_rf_features(feature_vector: Dict[str, Any]) -> Dict[str, Dict[str, float]]:
    """Extract RF metrics from a raw feature vector."""
    rsrps = feature_vector.get("neighbor_rsrp_dbm", {})
    sinrs = feature_vector.get("neighbor_sinrs", {})
    rsrqs = feature_vector.get("neighbor_rsrqs", {})
    loads = feature_vector.get("neighbor_cell_loads", {})

    if not isinstance(rsrps, dict):
        rsrps = {}
    if not isinstance(sinrs, dict):
        sinrs = {}
    if not isinstance(rsrqs, dict):
        rsrqs = {}
    if not isinstance(loads, dict):
        loads = {}

    rf_metrics: Dict[str, Dict[str, float]] = {}
    for antenna_id in rsrps.keys():
        rsrp = rsrps.get(antenna_id)
        sinr = sinrs.get(antenna_id)
        rsrq = rsrqs.get(antenna_id)
        load = loads.get(antenna_id)

        metrics: Dict[str, float] = {"rsrp": rsrp}
        if sinr is not None:
            metrics["sinr"] = sinr
        if rsrq is not None:
            metrics["rsrq"] = rsrq
        if load is not None:
            metrics["cell_load"] = load
        rf_metrics[antenna_id] = metrics
    return rf_metrics


def extract_environment_features(feature_vector: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """Extract environment related features from the raw vector.

    The returned dictionary contains:

    

    * **cell_load** – current load on the serving cell expressed as a fraction (0–1).

    * **environment** – optional indicator describing broader environmental conditions (e.g. indoor/outdoor, shadowing).

    * **signal_trend** – recent trend in RSRP/SINR/RSRQ measurements.

    * **service_profile** – an ordinal representation of the UE's service class.

    

    Including these descriptors allows the model to reason about radio quality and QoS requirements.

    """

    features: Dict[str, Optional[float]] = {}

    for key in ["cell_load", "environment", "signal_trend"]:

        value = feature_vector.get(key)

        features[key] = float(value) if isinstance(value, (int, float)) else None



    service_profile = feature_vector.get("service_profile")

    if service_profile is not None:

        mapping = {"mmtc": 0.5, "embb": 1.0, "urllc": 2.0}

        features["service_profile"] = mapping.get(str(service_profile).lower(), 0.0)



    return features

def extract_mobility_features(feature_vector: Dict[str, Any]) -> Dict[str, float]:
    """Extract mobility related features including direction components.

    The returned dictionary includes:

    * **speed** – instantaneous ground speed (m/s) derived from GNSS or timing advance.
    * **velocity** – a smoothed estimate of speed; defaults to instantaneous speed if not provided.
    * **acceleration** – rate of change of speed (m/s²).
    * **heading_change_rate** – average absolute change in heading (radians/s).
    * **path_curvature** – normalised curvature of the UE’s path.
    * **direction_x** / **direction_y** – unit vector components of movement direction.

    These descriptors allow the model to differentiate between stationary, pedestrian and vehicular users.
    """
    speed_val = feature_vector.get("speed", 0)
    speed = float(speed_val) if isinstance(speed_val, (int, float)) else 0.0

    velocity_val = feature_vector.get("velocity")
    if velocity_val is None:
        velocity_val = speed
    velocity = float(velocity_val) if isinstance(velocity_val, (int, float)) else speed

    accel_val = feature_vector.get("acceleration", 0)
    acceleration = float(accel_val) if isinstance(accel_val, (int, float)) else 0.0

    hcr_val = feature_vector.get("heading_change_rate", 0)
    heading_change_rate = float(hcr_val) if isinstance(hcr_val, (int, float)) else 0.0

    pc_val = feature_vector.get("path_curvature", 0)
    path_curvature = float(pc_val) if isinstance(pc_val, (int, float)) else 0.0

    dir_val = feature_vector.get("direction", (0, 0))
    dx, dy = _cached_direction_to_unit(dir_val)

    return {
        "speed": speed,
        "velocity": velocity,
        "acceleration": acceleration,
        "heading_change_rate": heading_change_rate,
        "path_curvature": path_curvature,
        "direction_x": dx,
        "direction_y": dy,
    }
def determine_optimal_antenna(rf_metrics: Dict[str, Dict[str, float]]) -> str:
    """Choose the antenna with highest RSRP using SINR as tie breaker."""
    if not rf_metrics:
        return "antenna_1"

    best: Tuple[str, float, float] | None = None
    for antenna_id, metrics in rf_metrics.items():
        rsrp = metrics.get("rsrp", float("-inf"))
        sinr = metrics.get("sinr", float("-inf"))
        if best is None or rsrp > best[1] or (rsrp == best[1] and sinr > best[2]):
            best = (antenna_id, rsrp, sinr)
    return best[0] if best else "antenna_1"


# --- Helper functions used by the ML models ---

def _direction_to_unit(direction: tuple | list) -> Tuple[float, float]:
    if isinstance(direction, (list, tuple)) and len(direction) >= 2:
        direction_tuple = (
            direction[0],
            direction[1],
            direction[2] if len(direction) >= 3 else 0,
        )
        return _cached_direction_to_unit(direction_tuple)
    return 0.0, 0.0


def _current_signal(current: str | None, metrics: dict) -> Tuple[float, float, float]:
    if current and current in metrics:
        data = metrics[current]
        return _cached_signal_extraction(
            data.get("rsrp"), data.get("sinr"), data.get("rsrq")
        )
    return _cached_signal_extraction(None, None, None)


def _neighbor_list(
    metrics: dict, current: str | None, include: bool
) -> List[Tuple[str, float, float, float, Optional[float]]]:
    if not include or not metrics:
        return []
    neighbors: List[Tuple[str, float, float, float, Optional[float]]] = []
    for aid, vals in metrics.items():
        if aid == current:
            continue
        rsrp, sinr, rsrq = _cached_signal_extraction(
            vals.get("rsrp"), vals.get("sinr"), vals.get("rsrq")
        )
        neighbors.append((aid, rsrp, sinr, rsrq, vals.get("cell_load")))
    neighbors.sort(key=lambda x: x[1], reverse=True)
    return neighbors


def build_model_features(
    data: Dict[str, Any],
    *,
    base_feature_names: List[str],
    neighbor_count: int = 0,
    include_neighbors: bool = True,
    init_lock: Optional[threading.Lock] = None,
    feature_names: Optional[List[str]] = None,
) -> Tuple[Dict[str, Any], int, List[str]]:
    """Build the feature dictionary used by ML models.

    Parameters
    ----------
    data:
        Raw UE data dictionary.
    base_feature_names:
        Names of the base features independent of neighbour count.
    neighbor_count:
        Number of neighbour antennas already configured. ``0`` means the count
        is determined dynamically on first call.
    include_neighbors:
        Whether neighbour features should be included.
    init_lock:
        Optional lock used when determining the neighbor count the first time.
    feature_names:
        Existing feature name list to extend when new neighbor features are
        discovered. If ``None`` a new list based on ``base_feature_names`` is
        returned.

    Returns
    -------
    tuple
        ``(features, neighbor_count, feature_names)``
    """
    latitude = data.get("latitude", 0)
    longitude = data.get("longitude", 0)
    altitude = data.get("altitude", 0)

    mobility = extract_mobility_features(data)
    env = extract_environment_features(data)

    time_since_handover = data.get("time_since_handover", 0)
    rsrp_stddev = data.get("rsrp_stddev", 0)
    sinr_stddev = data.get("sinr_stddev", 0)

    if "handover_count" in data:
        handover_count = data["handover_count"]
    else:
        hist = data.get("handover_history")
        handover_count = len(hist) if isinstance(hist, list) else 0

    rf_metrics = data.get("rf_metrics", {})
    current_antenna = data.get("connected_to")
    rsrp_curr, sinr_curr, rsrq_curr = _current_signal(current_antenna, rf_metrics)

    features: Dict[str, Any] = {
        "latitude": latitude,
        "longitude": longitude,
        "altitude": altitude,
        **mobility,
        "cell_load": env.get("cell_load", 0) or 0,
        "handover_count": handover_count,
        "time_since_handover": time_since_handover,
        "signal_trend": env.get("signal_trend", 0) or 0,
        "environment": env.get("environment", 0) or 0,
        "rsrp_stddev": rsrp_stddev,
        "sinr_stddev": sinr_stddev,
        "rsrp_current": rsrp_curr,
        "sinr_current": sinr_curr,
        "rsrq_current": rsrq_curr,
    }

    neighbors = _neighbor_list(rf_metrics, current_antenna, include_neighbors)
    best_rsrp, best_sinr, best_rsrq = rsrp_curr, sinr_curr, rsrq_curr
    if neighbors:
        best_rsrp, best_sinr, best_rsrq = neighbors[0][1], neighbors[0][2], neighbors[0][3]

    current_count = neighbor_count
    if current_count == 0:
        if init_lock:
            with init_lock:
                current_count = neighbor_count or len(neighbors)
        else:
            current_count = len(neighbors)

    neighbor_features: Dict[str, Any] = {}
    for idx in range(current_count):
        if idx < len(neighbors):
            n = neighbors[idx]
            neighbor_features.update(
                {
                    f"rsrp_a{idx+1}": n[1],
                    f"sinr_a{idx+1}": n[2],
                    f"rsrq_a{idx+1}": n[3],
                    f"neighbor_cell_load_a{idx+1}": n[4] if n[4] is not None else 0,
                }
            )
        else:
            neighbor_features.update(
                {
                    f"rsrp_a{idx+1}": DEFAULT_FALLBACK_RSRP,
                    f"sinr_a{idx+1}": DEFAULT_FALLBACK_SINR,
                    f"rsrq_a{idx+1}": DEFAULT_FALLBACK_RSRQ,
                    f"neighbor_cell_load_a{idx+1}": 0,
                }
            )

    features.update(neighbor_features)
    features.update(
        {
            "best_rsrp_diff": best_rsrp - rsrp_curr,
            "best_sinr_diff": best_sinr - sinr_curr,
            "best_rsrq_diff": best_rsrq - rsrq_curr,
        }
    )

    if feature_names is None:
        feature_names = list(base_feature_names)
    if current_count > neighbor_count:
        new_names = []
        for idx in range(current_count):
            new_names.extend(
                [
                    f"rsrp_a{idx+1}",
                    f"sinr_a{idx+1}",
                    f"rsrq_a{idx+1}",
                    f"neighbor_cell_load_a{idx+1}",
                ]
            )
        feature_names = feature_names + new_names

    apply_feature_transforms(features)

    return features, current_count, feature_names


