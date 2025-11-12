"""Utilities for generating synthetic training data."""
from __future__ import annotations

import math
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .mobility_metrics import MobilityMetricTracker
from ..core.qos import DEFAULT_SERVICE_PRESETS
from .antenna_selection import select_optimal_antenna


_QOS_SERVICE_TYPES = tuple(DEFAULT_SERVICE_PRESETS.keys())


def _safe_clip(value: float, minimum: float, maximum: float) -> float:
    """Return ``value`` clipped to ``[minimum, maximum]``."""
    return float(np.clip(value, minimum, maximum))


def _generate_qos_features(rng: np.random.Generator) -> dict[str, Any]:
    """Create QoS requirement and observation fields for a synthetic sample."""

    service_type = str(rng.choice(_QOS_SERVICE_TYPES))
    preset = DEFAULT_SERVICE_PRESETS.get(service_type, DEFAULT_SERVICE_PRESETS["default"])

    priority = int(np.clip(rng.normal(preset.get("service_priority", 5), 1.0), 1, 10))

    latency_req = _safe_clip(
        rng.normal(
            preset.get("latency_requirement_ms", 100.0),
            0.1 * max(1.0, preset.get("latency_requirement_ms", 100.0)) + 5.0,
        ),
        0.0,
        500.0,
    )
    throughput_req = _safe_clip(
        rng.normal(
            preset.get("throughput_requirement_mbps", 50.0),
            0.15 * max(1.0, preset.get("throughput_requirement_mbps", 50.0)) + 2.0,
        ),
        0.0,
        100000.0,
    )
    reliability_req = _safe_clip(
        rng.normal(preset.get("reliability_pct", 99.0), 0.5),
        0.0,
        100.0,
    )
    jitter_req = _safe_clip(
        rng.normal(preset.get("jitter_ms", 10.0), 2.0),
        0.0,
        1000.0,
    )

    latency_obs = _safe_clip(
        rng.normal(
            latency_req * rng.uniform(0.9, 1.2),
            max(1.0, latency_req * 0.1),
        ),
        0.0,
        500.0,
    )
    throughput_obs = _safe_clip(
        rng.normal(
            max(1.0, throughput_req * rng.uniform(0.8, 1.1)),
            max(0.5, throughput_req * 0.15 + 1.0),
        ),
        0.0,
        10000.0,
    )
    jitter_obs = _safe_clip(
        rng.normal(jitter_req * rng.uniform(0.8, 1.2), 2.0),
        0.0,
        200.0,
    )
    packet_loss = _safe_clip(rng.normal(1.5, 1.0), 0.0, 20.0)
    reliability_obs = max(0.0, 100.0 - packet_loss)

    latency_delta = float(np.clip(latency_obs - latency_req, -500.0, 500.0))
    throughput_delta = float(np.clip(throughput_obs - throughput_req, -10000.0, 10000.0))
    reliability_delta = reliability_obs - reliability_req

    observed_qos = {
        "latency_ms": latency_obs,
        "throughput_mbps": throughput_obs,
        "jitter_ms": jitter_obs,
        "packet_loss_rate": packet_loss,
    }

    return {
        "service_type": service_type,
        "service_type_label": service_type,
        "service_priority": priority,
        "latency_requirement_ms": latency_req,
        "throughput_requirement_mbps": throughput_req,
        "reliability_pct": reliability_req,
        "jitter_ms": jitter_req,
        "latency_ms": latency_obs,
        "throughput_mbps": throughput_obs,
        "packet_loss_rate": packet_loss,
        "observed_latency_ms": latency_obs,
        "observed_throughput_mbps": throughput_obs,
        "observed_jitter_ms": jitter_obs,
        "observed_packet_loss_rate": packet_loss,
        "latency_delta_ms": latency_delta,
        "throughput_delta_mbps": throughput_delta,
        "reliability_delta_pct": reliability_delta,
        "observed_qos": observed_qos,
        "observed_qos_summary": {"latest": observed_qos},
    }


def _generate_antenna_positions(num_antennas: int) -> dict[str, Tuple[float, float]]:
    """Return antenna coordinates arranged in a circle or grid."""
    if num_antennas <= 0:
        raise ValueError("num_antennas must be positive")

    sqrt = int(np.sqrt(num_antennas))
    antennas: dict[str, tuple[float, float]] = {}

    if sqrt * sqrt != num_antennas:
        # Arrange in a circle
        radius_x = 500
        radius_y = 433
        cx, cy = 500.0, 433.0
        angles = np.linspace(0, 2 * np.pi, num_antennas, endpoint=False)
        for idx, ang in enumerate(angles, 1):
            x = cx + radius_x * np.cos(ang)
            y = cy + radius_y * np.sin(ang)
            antennas[f"antenna_{idx}"] = (
                float(np.clip(x, 0, 1000)),
                float(np.clip(y, 0, 866)),
            )
    else:
        # Arrange in a grid
        xs = np.linspace(0, 1000, sqrt)
        ys = np.linspace(0, 866, sqrt)
        idx = 1
        for y in ys:
            for x in xs:
                antennas[f"antenna_{idx}"] = (float(x), float(y))
                idx += 1

    return antennas


def _generate_antenna_biases(
    rng: np.random.Generator,
    antennas: dict[str, Tuple[float, float]],
) -> dict[str, Dict[str, float]]:
    """Create per-antenna capability biases to diversify optimal choices."""

    biases: dict[str, Dict[str, float]] = {}
    for antenna_id in antennas:
        capacity = float(rng.uniform(0.85, 1.2))
        latency = float(rng.uniform(0.85, 1.15))
        reliability = float(rng.uniform(0.85, 1.1))
        coverage = float(rng.uniform(0.9, 1.1))

        # Impose mild specialisation so some antennas excel for specific services.
        service_roll = rng.random()
        if service_roll < 0.25:
            latency += 0.1
        elif service_roll < 0.5:
            capacity += 0.1
        elif service_roll < 0.75:
            reliability += 0.08

        biases[antenna_id] = {
            "capacity": capacity,
            "latency": latency,
            "reliability": reliability,
            "coverage": coverage,
        }
    return biases


def generate_synthetic_training_data(
    num_samples: int = 500,
    num_antennas: int = 3,
    *,
    seed: Optional[int] = None,
    balance_classes: bool = False,
    edge_case_ratio: float = 0.2,
):
    """Return a list of synthetic training samples."""

    rng = np.random.default_rng(seed)

    antennas = _generate_antenna_positions(num_antennas)
    antenna_bias = _generate_antenna_biases(rng, antennas)

    data = []
    tracker = MobilityMetricTracker()
    prev_antenna = None
    last_handover_idx = 0

    assignments: List[str] = []
    if balance_classes:
        per_antenna = max(1, math.ceil(num_samples / max(1, num_antennas)))
        for antenna_id in antennas.keys():
            assignments.extend([antenna_id] * per_antenna)
        rng.shuffle(assignments)

    for i in range(num_samples):
        anchor_antenna = assignments[i] if balance_classes and i < len(assignments) else None

        if balance_classes and anchor_antenna:
            anchor_pos = antennas[anchor_antenna]
            is_edge_case = rng.random() < edge_case_ratio and num_antennas > 1
            if is_edge_case:
                neighbor_choices = [aid for aid in antennas if aid != anchor_antenna]
                if neighbor_choices:
                    neighbor_id = str(rng.choice(neighbor_choices))
                    neighbor_pos = antennas[neighbor_id]
                    t = rng.uniform(0.4, 0.6)
                    jitter_x = rng.normal(0.0, 10.0)
                    jitter_y = rng.normal(0.0, 10.0)
                    x = anchor_pos[0] + t * (neighbor_pos[0] - anchor_pos[0]) + jitter_x
                    y = anchor_pos[1] + t * (neighbor_pos[1] - anchor_pos[1]) + jitter_y
                else:
                    x = anchor_pos[0]
                    y = anchor_pos[1]
            else:
                radius = rng.uniform(0, 250.0)
                angle = rng.uniform(0, 2 * np.pi)
                x = anchor_pos[0] + radius * math.cos(angle)
                y = anchor_pos[1] + radius * math.sin(angle)
        else:
            x = float(rng.uniform(0, 1000))
            y = float(rng.uniform(0, 866))

        x = float(np.clip(x, 0, 1000))
        y = float(np.clip(y, 0, 866))

        speed = float(rng.uniform(0, 10))
        angle = rng.uniform(0, 2 * np.pi)
        direction = [np.cos(angle), np.sin(angle), 0]

        distances = {}
        for antenna_id, pos in antennas.items():
            dist = float(np.sqrt((x - pos[0]) ** 2 + (y - pos[1]) ** 2))
            distances[antenna_id] = dist

        closest_antenna = min(distances, key=distances.get)
        connected_antenna = anchor_antenna or closest_antenna

        rf_metrics = {}
        for antenna_id, dist in distances.items():
            profile = antenna_bias[antenna_id]
            rsrp = (-58 - 20 * np.log10(max(1, dist / 10))) * profile["coverage"]
            sinr = (20 * (1 - dist / 1500) * profile["capacity"]) + rng.normal(0, 2)
            # Approximate RSRQ based on distance with some noise. Values typically
            # range between -3 dB (excellent) and -20 dB (poor).
            rsrq = (-3 - 15 * (dist / 1500)) * profile["reliability"] + rng.normal(0, 1)
            rf_metrics[antenna_id] = {
                "rsrp": float(rsrp),
                "sinr": float(sinr),
                "rsrq": float(np.clip(rsrq, -30, -3)),
                "cell_load": float(np.clip(rng.beta(2.0, 2.5) / profile["capacity"], 0.0, 1.0)),
            }

        # Update trajectory-based metrics
        heading_change_rate, path_curvature = tracker.update_position("ue", x, y)

        # Derive handover timing
        if prev_antenna is None:
            time_since_handover = 0.0
        elif connected_antenna != prev_antenna:
            last_handover_idx = i
            time_since_handover = 0.0
        else:
            time_since_handover = float(i - last_handover_idx)
        prev_antenna = connected_antenna

        # Derive a basic stability score from mobility metrics. Straight,
        # consistent movement yields a value near 1 while frequent direction
        # changes reduce the score.  Both ``heading_change_rate`` and
        # ``path_curvature`` increase as the UE trajectory becomes more erratic.
        # We map the combined value into ``[0, 1]`` using a reciprocal form so
        # extreme mobility quickly lowers stability.
        stability = float(1.0 / (1.0 + heading_change_rate + path_curvature))

        sample = {
            "ue_id": f"synthetic_ue_{i}",
            "latitude": x,
            "longitude": y,
            "altitude": 0.0,
            "speed": speed,
            "velocity": speed,
            "acceleration": float(rng.normal(0, 0.5)),
            "cell_load": float(rng.uniform(0, 1)),
            "handover_count": int(rng.integers(0, 4)),
            "time_since_handover": time_since_handover,
            "signal_trend": float(rng.normal(0, 1)),
            "environment": float(rng.uniform(0, 1)),
            "direction": direction,
            "heading_change_rate": heading_change_rate,
            "path_curvature": path_curvature,
            "stability": stability,
            "connected_to": connected_antenna,
            "rf_metrics": rf_metrics,
        }

        qos_features = _generate_qos_features(rng)
        sample.update(qos_features)

        optimal_antenna, antenna_scores = select_optimal_antenna(
            rf_metrics,
            qos_requirements=qos_features,
            service_type=qos_features.get("service_type"),
            service_priority=qos_features.get("service_priority"),
            stability=stability,
            signal_trend=sample["signal_trend"],
            antenna_bias=antenna_bias,
            rng=rng,
        )
        if balance_classes and anchor_antenna:
            sample["original_optimal_antenna"] = optimal_antenna
            sample["optimal_antenna"] = anchor_antenna
        else:
            sample["optimal_antenna"] = optimal_antenna
        sample["antenna_selection_scores"] = {k: float(v) for k, v in antenna_scores.items()}

        sorted_scores = sorted(antenna_scores.items(), key=lambda item: item[1], reverse=True)
        if len(sorted_scores) >= 2:
            sample["optimal_score_margin"] = float(sorted_scores[0][1] - sorted_scores[1][1])
        else:
            sample["optimal_score_margin"] = 0.0
        connected_rank = next(
            (idx + 1 for idx, (aid, _) in enumerate(sorted_scores) if aid == sample["connected_to"]),
            float(len(sorted_scores)) if sorted_scores else 1.0,
        )
        sample["connected_signal_rank"] = float(connected_rank)

        data.append(sample)

    return data


def generate_synthetic_training_data_batch(
    num_samples: int = 500, 
    num_antennas: int = 3,
    batch_size: int = 100,
    *,
    seed: Optional[int] = None,
    balance_classes: bool = False,
    edge_case_ratio: float = 0.2,
) -> List[Dict]:
    """Generate synthetic training data in batches for memory efficiency.
    
    For very large datasets, this function generates data in batches
    to avoid memory issues while maintaining performance optimizations.
    
    Args:
        num_samples: Total number of samples to generate
        num_antennas: Number of antennas in the simulation
        batch_size: Number of samples to generate per batch
        
    Returns:
        List of synthetic training samples
    """
    if batch_size <= 0 or batch_size > num_samples:
        batch_size = num_samples
    
    all_data = []
    remaining_samples = num_samples
    batch_start = 0
    
    while remaining_samples > 0:
        current_batch_size = min(batch_size, remaining_samples)
        
        # Generate a batch of data
        batch_seed = seed + batch_start if seed is not None else None
        batch_data = generate_synthetic_training_data(
            num_samples=current_batch_size,
            num_antennas=num_antennas,
            seed=batch_seed,
            balance_classes=balance_classes,
            edge_case_ratio=edge_case_ratio,
        )
        
        # Update UE IDs to be globally unique
        for i, sample in enumerate(batch_data):
            sample["ue_id"] = f"synthetic_ue_{batch_start + i}"
        
        all_data.extend(batch_data)
        remaining_samples -= current_batch_size
        batch_start += current_batch_size
    
    return all_data


def validate_training_data(samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Return balance and coverage statistics for *samples*.

    The validator summarises class distribution, geographic spread, edge case
    coverage and compares the ML heuristic label against the enforced class
    when balancing is enabled.  The result is JSON serialisable so diagnostics
    scripts can persist the report directly.
    """

    if not samples:
        return {
            "total_samples": 0,
            "class_distribution": {},
            "imbalance_ratio": float("inf"),
            "latitude_range": [0.0, 0.0],
            "longitude_range": [0.0, 0.0],
            "edge_case_ratio": 0.0,
            "edge_case_outcomes": {},
        }

    labels = [str(sample.get("optimal_antenna", "")) for sample in samples]
    distribution = Counter(filter(None, labels))
    min_count = min(distribution.values()) if distribution else 0
    max_count = max(distribution.values()) if distribution else 0
    imbalance_ratio = (max_count / min_count) if min_count else float("inf")

    latitudes = [float(sample.get("latitude", 0.0)) for sample in samples]
    longitudes = [float(sample.get("longitude", 0.0)) for sample in samples]

    edge_cases = [sample for sample in samples if sample.get("original_optimal_antenna")]
    edge_case_ratio = len(edge_cases) / len(samples)

    edge_outcomes = Counter()
    for sample in edge_cases:
        original = str(sample.get("original_optimal_antenna"))
        reassigned = str(sample.get("optimal_antenna"))
        key = "unchanged" if original == reassigned else "reassigned"
        edge_outcomes[key] += 1

    return {
        "total_samples": len(samples),
        "class_distribution": {label: int(count) for label, count in distribution.items()},
        "imbalance_ratio": imbalance_ratio,
        "latitude_range": [float(min(latitudes)), float(max(latitudes))],
        "longitude_range": [float(min(longitudes)), float(max(longitudes))],
        "edge_case_ratio": edge_case_ratio,
        "edge_case_outcomes": {k: int(v) for k, v in edge_outcomes.items()},
    }
