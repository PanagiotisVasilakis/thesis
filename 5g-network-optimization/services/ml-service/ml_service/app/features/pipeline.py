"""Reusable feature extraction pipeline."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple, List
import threading

__all__ = [
    "extract_rf_features",
    "extract_environment_features",
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
    """Extract environment related features from the raw vector."""
    features: Dict[str, Optional[float]] = {}
    for key in ["cell_load", "environment", "velocity", "acceleration", "signal_trend"]:
        value = feature_vector.get(key)
        features[key] = float(value) if isinstance(value, (int, float)) else None
    return features


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
        magnitude = (direction[0] ** 2 + direction[1] ** 2) ** 0.5
        if magnitude > 0:
            return direction[0] / magnitude, direction[1] / magnitude
    return 0.0, 0.0


def _current_signal(current: str | None, metrics: dict) -> Tuple[float, float, float]:
    if current and current in metrics:
        data = metrics[current]
        rsrp = data.get("rsrp", -120)
        sinr = data.get("sinr") if data.get("sinr") is not None else 0
        rsrq = data.get("rsrq") if data.get("rsrq") is not None else -30
        return rsrp, sinr, rsrq
    return -120, 0, -30


def _neighbor_list(metrics: dict, current: str | None, include: bool) -> List[Tuple[str, float, float, float, Optional[float]]]:
    if not include or not metrics:
        return []
    neighbors = [
        (
            aid,
            vals.get("rsrp", -120),
            vals.get("sinr") if vals.get("sinr") is not None else 0,
            vals.get("rsrq") if vals.get("rsrq") is not None else -30,
            vals.get("cell_load"),
        )
        for aid, vals in metrics.items()
        if aid != current
    ]
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
    speed = data.get("speed", 0)
    velocity = data.get("velocity")
    if velocity is None:
        velocity = speed
    velocity = velocity if velocity is not None else 0

    heading_change_rate = data.get("heading_change_rate", 0)
    path_curvature = data.get("path_curvature", 0)
    acceleration = data.get("acceleration", 0)
    cell_load = data.get("cell_load", 0)
    time_since_handover = data.get("time_since_handover", 0)
    signal_trend = data.get("signal_trend", 0)
    environment = data.get("environment", 0)
    rsrp_stddev = data.get("rsrp_stddev", 0)
    sinr_stddev = data.get("sinr_stddev", 0)

    if "handover_count" in data:
        handover_count = data["handover_count"]
    else:
        hist = data.get("handover_history")
        handover_count = len(hist) if isinstance(hist, list) else 0

    direction = data.get("direction", (0, 0, 0))
    dx, dy = _direction_to_unit(direction)

    rf_metrics = data.get("rf_metrics", {})
    current_antenna = data.get("connected_to")
    rsrp_curr, sinr_curr, rsrq_curr = _current_signal(current_antenna, rf_metrics)

    features: Dict[str, Any] = {
        "latitude": latitude,
        "longitude": longitude,
        "altitude": altitude,
        "speed": speed,
        "velocity": velocity,
        "heading_change_rate": heading_change_rate,
        "path_curvature": path_curvature,
        "acceleration": acceleration,
        "cell_load": cell_load,
        "handover_count": handover_count,
        "time_since_handover": time_since_handover,
        "signal_trend": signal_trend,
        "environment": environment,
        "rsrp_stddev": rsrp_stddev,
        "sinr_stddev": sinr_stddev,
        "direction_x": dx,
        "direction_y": dy,
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
                    f"rsrp_a{idx+1}": -120,
                    f"sinr_a{idx+1}": 0,
                    f"rsrq_a{idx+1}": -30,
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
    return features, current_count, feature_names


