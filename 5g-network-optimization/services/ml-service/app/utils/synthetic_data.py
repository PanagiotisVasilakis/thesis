"""Utilities for generating synthetic training data."""
import numpy as np


def generate_synthetic_training_data(num_samples: int = 500):
    """Return a list of synthetic training samples."""
    np.random.seed(42)

    antennas = {
        "antenna_1": (0, 0),
        "antenna_2": (1000, 0),
        "antenna_3": (500, 866),
    }

    data = []

    for i in range(num_samples):
        x = np.random.uniform(0, 1000)
        y = np.random.uniform(0, 866)

        speed = np.random.uniform(0, 10)
        angle = np.random.uniform(0, 2 * np.pi)
        direction = [np.cos(angle), np.sin(angle), 0]

        distances = {}
        for antenna_id, pos in antennas.items():
            dist = np.sqrt((x - pos[0]) ** 2 + (y - pos[1]) ** 2)
            distances[antenna_id] = dist

        closest_antenna = min(distances, key=distances.get)

        rf_metrics = {}
        for antenna_id, dist in distances.items():
            rsrp = -60 - 20 * np.log10(max(1, dist / 10))
            sinr = 20 * (1 - dist / 1500) + np.random.normal(0, 2)
            rf_metrics[antenna_id] = {"rsrp": rsrp, "sinr": sinr}

        sample = {
            "ue_id": f"synthetic_ue_{i}",
            "latitude": x,
            "longitude": y,
            "speed": speed,
            "direction": direction,
            "connected_to": closest_antenna,
            "rf_metrics": rf_metrics,
            "optimal_antenna": closest_antenna,
        }

        data.append(sample)

    return data
