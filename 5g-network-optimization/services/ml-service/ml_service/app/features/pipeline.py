"""Reusable feature extraction pipeline."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple, List
import threading
import math

from .transform_registry import apply_feature_transforms
from ..config.constants import (
    DEFAULT_FALLBACK_RSRP,
    DEFAULT_FALLBACK_SINR,
    DEFAULT_FALLBACK_RSRQ,
)
from ..config.feature_specs import sanitize_feature_ranges
from ..utils.feature_cache import _cached_direction_to_unit, _cached_signal_extraction
from ..utils.type_helpers import safe_float_or_none

__all__ = [
    "extract_rf_features",
    "extract_environment_features",
    "extract_mobility_features",
    "determine_optimal_antenna",
    "build_model_features",
]


# Note: _safe_float is now imported from utils.type_helpers as safe_float_or_none


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

        metrics: Dict[str, float] = {}
        if rsrp is not None:
            metrics["rsrp"] = float(rsrp)
        if sinr is not None:
            metrics["sinr"] = float(sinr)
        if rsrq is not None:
            metrics["rsrq"] = float(rsrq)
        if load is not None:
            metrics["cell_load"] = float(load)
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

        if isinstance(value, (int, float)):
            features[key] = float(value)
        elif isinstance(value, str):
            try:
                features[key] = float(value)
            except ValueError:
                features[key] = None
        else:
            features[key] = None



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
    if isinstance(dir_val, list):
        dir_val = tuple(dir_val)
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

    stability_val = data.get("stability")
    if not isinstance(stability_val, (int, float)):
        stability_val = 1.0 / (1.0 + abs(mobility["heading_change_rate"]) + abs(mobility["path_curvature"]))
    stability = max(0.0, min(1.0, float(stability_val)))

    features: Dict[str, Any] = {
        "latitude": latitude,
        "longitude": longitude,
        "altitude": altitude,
        **mobility,
        "stability": stability,
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

    latency_req = safe_float_or_none(data.get("latency_requirement_ms"))
    latency_obs = safe_float_or_none(data.get("latency_ms"))
    latency_delta = safe_float_or_none(data.get("latency_delta_ms"))
    throughput_req = safe_float_or_none(data.get("throughput_requirement_mbps"))
    throughput_obs = safe_float_or_none(data.get("throughput_mbps"))
    throughput_delta = safe_float_or_none(data.get("throughput_delta_mbps"))
    reliability_req = safe_float_or_none(data.get("reliability_pct"))
    reliability_delta = safe_float_or_none(data.get("reliability_delta_pct"))

    if latency_delta is None and latency_obs is not None and latency_req is not None:
        latency_delta = latency_obs - latency_req
    if throughput_delta is None and throughput_obs is not None and throughput_req is not None:
        throughput_delta = throughput_obs - throughput_req
    if reliability_delta is None:
        reliability_delta = 0.0

    def _ratio(delta: Optional[float], reference: Optional[float]) -> float:
        if delta is None or reference in (None, 0):
            return 0.0
        return float(delta / max(reference, 1e-6))

    latency_pressure_ratio = _ratio(latency_delta, latency_req)
    throughput_headroom_ratio = _ratio(throughput_delta, throughput_req)
    reliability_pressure_ratio = _ratio(reliability_delta, reliability_req)

    features.update(
        {
            "latency_pressure_ratio": latency_pressure_ratio,
            "throughput_headroom_ratio": throughput_headroom_ratio,
            "reliability_pressure_ratio": reliability_pressure_ratio,
            "sla_pressure": (
                max(0.0, latency_pressure_ratio)
                + max(0.0, -throughput_headroom_ratio)
                + max(0.0, -reliability_pressure_ratio)
            ),
        }
    )

    loads = [float(vals.get("cell_load")) for vals in rf_metrics.values() if isinstance(vals.get("cell_load"), (int, float))]
    if loads:
        mean_load = sum(loads) / len(loads)
        load_variance = sum((val - mean_load) ** 2 for val in loads) / len(loads)
        load_std = math.sqrt(load_variance)
    else:
        load_std = 0.0

    rsrp_values = [float(vals.get("rsrp")) for vals in rf_metrics.values() if isinstance(vals.get("rsrp"), (int, float))]
    if len(rsrp_values) >= 2:
        rsrp_sorted = sorted(rsrp_values, reverse=True)
        top2_rsrp_gap = rsrp_sorted[0] - rsrp_sorted[1]
    else:
        top2_rsrp_gap = 0.0

    sinr_values = [float(vals.get("sinr")) for vals in rf_metrics.values() if isinstance(vals.get("sinr"), (int, float))]
    if len(sinr_values) >= 2:
        sinr_sorted = sorted(sinr_values, reverse=True)
        top2_sinr_gap = sinr_sorted[0] - sinr_sorted[1]
    else:
        top2_sinr_gap = 0.0

    features.update(
        {
            "rf_load_std": load_std,
            "top2_rsrp_gap": top2_rsrp_gap,
            "top2_sinr_gap": top2_sinr_gap,
        }
    )

    selection_scores = data.get("antenna_selection_scores")
    optimal_score_margin = data.get("optimal_score_margin")
    if not isinstance(optimal_score_margin, (int, float)) and isinstance(selection_scores, dict):
        ordered_scores = sorted(selection_scores.items(), key=lambda item: item[1], reverse=True)
        if len(ordered_scores) >= 2:
            optimal_score_margin = float(ordered_scores[0][1] - ordered_scores[1][1])
        elif ordered_scores:
            optimal_score_margin = float(ordered_scores[0][1])
        else:
            optimal_score_margin = 0.0
    if not isinstance(optimal_score_margin, (int, float)):
        optimal_score_margin = 0.0

    connected_rank = data.get("connected_signal_rank")
    if not isinstance(connected_rank, (int, float)) and isinstance(selection_scores, dict):
        ordered_scores = sorted(selection_scores.items(), key=lambda item: item[1], reverse=True)
        connected_rank = next(
            (idx + 1 for idx, (aid, _) in enumerate(ordered_scores) if aid == current_antenna),
            float(len(ordered_scores)) if ordered_scores else 1.0,
        )
    if not isinstance(connected_rank, (int, float)):
        connected_rank = 1.0

    features.update(
        {
            "optimal_score_margin": float(optimal_score_margin),
            "connected_signal_rank": float(connected_rank),
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
    sanitize_feature_ranges(features)

    return features, current_count, feature_names


