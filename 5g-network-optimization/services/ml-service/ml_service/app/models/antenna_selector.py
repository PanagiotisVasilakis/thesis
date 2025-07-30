"""Antenna selector model for 5G network optimization."""
import numpy as np
import lightgbm as lgb
import joblib
import os
import logging
from sklearn.exceptions import NotFittedError

from ..utils.env_utils import get_neighbor_count_from_env

FALLBACK_ANTENNA_ID = "antenna_1"
FALLBACK_CONFIDENCE = 0.5

logger = logging.getLogger(__name__)

DEFAULT_TEST_FEATURES = {
    "latitude": 500,
    "longitude": 500,
    "speed": 1.0,
    "direction_x": 0.7,
    "direction_y": 0.7,
    "rsrp_current": -90,
    "sinr_current": 10,
    "best_rsrp_diff": 0.0,
    "best_sinr_diff": 0.0,
    "altitude": 0.0,
}


class AntennaSelector:
    """ML model for selecting optimal antenna based on UE data."""

    def __init__(self, model_path=None, neighbor_count: int | None = None):
        """Initialize the model.

        Parameters
        ----------
        model_path:
            Optional path to a saved model.
        neighbor_count:
            If given, preallocate feature names for this many neighbouring
            antennas instead of determining the number dynamically on the first
            call to :meth:`extract_features`.
        """
        self.model_path = model_path
        self.model = None
        # Base features independent of neighbour count
        self.base_feature_names = [
            "latitude",
            "longitude",
            "speed",
            "direction_x",
            "direction_y",
            "rsrp_current",
            "sinr_current",
            "best_rsrp_diff",
            "best_sinr_diff",
            "altitude",
        ]
        self.neighbor_count = 0
        self.feature_names = list(self.base_feature_names)

        if neighbor_count is None:
            neighbor_count = get_neighbor_count_from_env(logger=logger)

        if neighbor_count and neighbor_count > 0:
            self.neighbor_count = int(neighbor_count)
            for idx in range(self.neighbor_count):
                self.feature_names.extend([
                    f"rsrp_a{idx+1}",
                    f"sinr_a{idx+1}",
                ])

        # Try to load existing model
        try:
            if model_path and os.path.exists(model_path):
                self.load(model_path)
            else:
                self._initialize_model()
        except Exception as e:
            logging.warning(f"Could not load model: {e}")
            self._initialize_model()

    def _initialize_model(self):
        """Initialize a default LightGBM model."""
        self.model = lgb.LGBMClassifier(
            n_estimators=100,
            max_depth=10,
            random_state=42,
        )

    def _direction_to_unit(self, direction: tuple | list) -> tuple[float, float]:
        """Convert a 2D direction vector to unit components."""
        if isinstance(direction, (list, tuple)) and len(direction) >= 2:
            magnitude = (direction[0] ** 2 + direction[1] ** 2) ** 0.5
            if magnitude > 0:
                return direction[0] / magnitude, direction[1] / magnitude
        return 0.0, 0.0

    def _current_signal(
        self, current: str | None, metrics: dict
    ) -> tuple[float, float]:
        """Return RSRP/SINR for the currently connected antenna."""
        if current and current in metrics:
            data = metrics[current]
            return data.get("rsrp", -120), data.get("sinr", 0)
        return -120, 0

    def _neighbor_list(self, metrics: dict, current: str | None, include: bool) -> list:
        """Return sorted list of neighbour metrics."""
        if not include or not metrics:
            return []
        neighbors = [
            (aid, vals.get("rsrp", -120), vals.get("sinr", 0))
            for aid, vals in metrics.items()
            if aid != current
        ]
        neighbors.sort(key=lambda x: x[1], reverse=True)
        return neighbors

    def extract_features(self, data, include_neighbors=True):
        """Extract features from UE data."""
        features = {
            "latitude": data.get("latitude", 0),
            "longitude": data.get("longitude", 0),
            "altitude": data.get("altitude", 0),
            "speed": data.get("speed", 0),
        }

        dx, dy = self._direction_to_unit(data.get("direction", (0, 0, 0)))
        features["direction_x"] = dx
        features["direction_y"] = dy

        rf_metrics = data.get("rf_metrics", {})
        current_antenna = data.get("connected_to")
        rsrp_curr, sinr_curr = self._current_signal(current_antenna, rf_metrics)
        features["rsrp_current"] = rsrp_curr
        features["sinr_current"] = sinr_curr

        neighbors = self._neighbor_list(rf_metrics, current_antenna, include_neighbors)
        best_rsrp, best_sinr = rsrp_curr, sinr_curr
        if neighbors:
            best_rsrp, best_sinr = neighbors[0][1], neighbors[0][2]

        if self.neighbor_count == 0:
            self.neighbor_count = len(neighbors)
            for idx in range(self.neighbor_count):
                self.feature_names.extend([f"rsrp_a{idx+1}", f"sinr_a{idx+1}"])

        for idx in range(self.neighbor_count):
            if idx < len(neighbors):
                features[f"rsrp_a{idx+1}"] = neighbors[idx][1]
                features[f"sinr_a{idx+1}"] = neighbors[idx][2]
            else:
                features[f"rsrp_a{idx+1}"] = -120
                features[f"sinr_a{idx+1}"] = 0

        features["best_rsrp_diff"] = best_rsrp - rsrp_curr
        features["best_sinr_diff"] = best_sinr - sinr_curr

        return features

    def predict(self, features):
        """Predict the optimal antenna for the UE."""
        # Convert features to the format expected by the model
        X = np.array([[features[name] for name in self.feature_names]])

        try:
            # Perform a single prediction attempt via probabilities
            probabilities = self.model.predict_proba(X)[0]
            idx = int(np.argmax(probabilities))
            antenna_id = self.model.classes_[idx]
            confidence = float(probabilities[idx])
        except (lgb.basic.LightGBMError, NotFittedError, AttributeError) as exc:
            if isinstance(exc, (lgb.basic.LightGBMError, NotFittedError)):
                ue_id = features.get("ue_id")
                if ue_id:
                    logger.warning(
                        "Model untrained or error during prediction for UE %s: %s. Returning default antenna.",
                        ue_id,
                        exc,
                    )
                else:
                    logger.warning(
                        "Model untrained or error during prediction: %s. Returning default antenna.",
                        exc,
                    )
            return {
                "antenna_id": FALLBACK_ANTENNA_ID,
                "confidence": FALLBACK_CONFIDENCE,
            }

        return {"antenna_id": antenna_id, "confidence": float(confidence)}

    def train(self, training_data):
        """Train the model with provided data."""
        # Extract features and labels from training data
        X = []
        y = []

        for sample in training_data:
            features = self.extract_features(sample)
            feature_vector = [features[name] for name in self.feature_names]

            # The label is the optimal antenna ID
            label = sample.get("optimal_antenna")

            X.append(feature_vector)
            y.append(label)

        # Convert to numpy arrays
        X = np.array(X)
        y = np.array(y)

        # Train the model
        self.model.fit(X, y)

        # Return training metrics
        return {
            "samples": len(X),
            "classes": len(set(y)),
            "feature_importance": dict(
                zip(self.feature_names, self.model.feature_importances_)
            ),
        }

    def save(self, path=None):
        """Save the model to disk."""
        save_path = path or self.model_path
        if save_path:
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            joblib.dump(
                {
                    "model": self.model,
                    "feature_names": self.feature_names,
                    "neighbor_count": self.neighbor_count,
                },
                save_path,
            )
            return True
        return False

    def load(self, path=None):
        """Load the model from disk."""
        load_path = path or self.model_path
        if load_path and os.path.exists(load_path):
            data = joblib.load(load_path)
            if isinstance(data, dict) and "model" in data:
                self.model = data["model"]
                self.feature_names = data.get("feature_names", self.feature_names)
                self.neighbor_count = data.get("neighbor_count", self.neighbor_count)
            else:
                self.model = data
            return True
        return False
