"""Utilities for generating synthetic training data."""
import numpy as np
from typing import List, Dict

from .mobility_metrics import MobilityMetricTracker


def _generate_antenna_positions(num_antennas: int) -> dict:
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


def generate_synthetic_training_data(
    num_samples: int = 500, num_antennas: int = 3
):
    """Return a list of synthetic training samples."""
    np.random.seed(42)

    antennas = _generate_antenna_positions(num_antennas)

    data = []
    tracker = MobilityMetricTracker()
    prev_antenna = None
    last_handover_idx = 0

    for i in range(num_samples):
        x = float(np.random.uniform(0, 1000))
        y = float(np.random.uniform(0, 866))

        speed = float(np.random.uniform(0, 10))
        angle = np.random.uniform(0, 2 * np.pi)
        direction = [np.cos(angle), np.sin(angle), 0]

        distances = {}
        for antenna_id, pos in antennas.items():
            dist = float(np.sqrt((x - pos[0]) ** 2 + (y - pos[1]) ** 2))
            distances[antenna_id] = dist

        closest_antenna = min(distances, key=distances.get)

        rf_metrics = {}
        for antenna_id, dist in distances.items():
            rsrp = -60 - 20 * np.log10(max(1, dist / 10))
            sinr = 20 * (1 - dist / 1500) + np.random.normal(0, 2)
            # Approximate RSRQ based on distance with some noise. Values typically
            # range between -3 dB (excellent) and -20 dB (poor).
            rsrq = -3 - 15 * (dist / 1500) + np.random.normal(0, 1)
            rf_metrics[antenna_id] = {
                "rsrp": float(rsrp),
                "sinr": float(sinr),
                "rsrq": float(np.clip(rsrq, -30, -3)),
                "cell_load": float(np.random.uniform(0, 1)),
            }

        # Update trajectory-based metrics
        heading_change_rate, path_curvature = tracker.update_position("ue", x, y)

        # Derive handover timing
        if prev_antenna is None:
            time_since_handover = 0.0
        elif closest_antenna != prev_antenna:
            last_handover_idx = i
            time_since_handover = 0.0
        else:
            time_since_handover = float(i - last_handover_idx)
        prev_antenna = closest_antenna

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
            "acceleration": float(np.random.normal(0, 0.5)),
            "cell_load": float(np.random.uniform(0, 1)),
            "handover_count": int(np.random.randint(0, 4)),
            "time_since_handover": time_since_handover,
            "signal_trend": float(np.random.normal(0, 1)),
            "environment": float(np.random.uniform(0, 1)),
            "direction": direction,
            "heading_change_rate": heading_change_rate,
            "path_curvature": path_curvature,
            "stability": stability,
            "connected_to": closest_antenna,
            "rf_metrics": rf_metrics,
            "optimal_antenna": closest_antenna,
        }

        data.append(sample)

    return data


def generate_synthetic_training_data_batch(
    num_samples: int = 500, 
    num_antennas: int = 3,
    batch_size: int = 100
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
        batch_data = generate_synthetic_training_data(
            num_samples=current_batch_size,
            num_antennas=num_antennas
        )
        
        # Update UE IDs to be globally unique
        for i, sample in enumerate(batch_data):
            sample["ue_id"] = f"synthetic_ue_{batch_start + i}"
        
        all_data.extend(batch_data)
        remaining_samples -= current_batch_size
        batch_start += current_batch_size
    
    return all_data
