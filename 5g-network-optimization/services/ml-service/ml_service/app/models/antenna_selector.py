"""Antenna selector model for 5G network optimization."""
import numpy as np
import lightgbm as lgb
import joblib
import os
import logging
import threading
import json
from datetime import datetime, timezone
from ..initialization.model_init import MODEL_VERSION
from sklearn.exceptions import NotFittedError
from ..features import pipeline

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
    "heading_change_rate": 0.0,
    "path_curvature": 0.0,
    "velocity": 1.0,
    "acceleration": 0.0,
    "cell_load": 0.0,
    "handover_count": 0,
    "time_since_handover": 0.0,
    "signal_trend": 0.0,
    "environment": 0.0,
    "rsrp_stddev": 0.0,
    "sinr_stddev": 0.0,
    "rsrp_current": -90,
    "sinr_current": 10,
    "rsrq_current": -10,
    "best_rsrp_diff": 0.0,
    "best_sinr_diff": 0.0,
    "best_rsrq_diff": 0.0,
    "altitude": 0.0,
}


class AntennaSelector:
    """ML model for selecting optimal antenna based on UE data."""

    # Guard lazy initialization of neighbour feature names. This initialization
    # may run during the first prediction call when ``extract_features`` is
    # invoked concurrently, so a lock ensures feature names are added only once.
    _init_lock = threading.Lock()

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
        # Thread-safety: protect concurrent reads/writes to the underlying estimator
        self._model_lock = threading.RLock()
        self.model = None
        # Base features independent of neighbour count
        self.base_feature_names = [
            "latitude",
            "longitude",
            "speed",
            "direction_x",
            "direction_y",
            "heading_change_rate",
            "path_curvature",
            "velocity",
            "acceleration",
            "cell_load",
            "handover_count",
            "time_since_handover",
            "signal_trend",
            "environment",
            "rsrp_stddev",
            "sinr_stddev",
            "rsrp_current",
            "sinr_current",
            "rsrq_current",
            "best_rsrp_diff",
            "best_sinr_diff",
            "best_rsrq_diff",
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
                    f"rsrq_a{idx+1}",
                    f"neighbor_cell_load_a{idx+1}",
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
    ) -> tuple[float, float, float]:
        """Return RSRP/SINR/RSRQ for the currently connected antenna."""
        if current and current in metrics:
            data = metrics[current]
            rsrp = data.get("rsrp", -120)
            sinr = data.get("sinr")
            rsrq = data.get("rsrq")
            if sinr is None:
                sinr = 0
            if rsrq is None:
                rsrq = -30
            return rsrp, sinr, rsrq
        return -120, 0, -30

    def _neighbor_list(self, metrics: dict, current: str | None, include: bool) -> list:
        """Return sorted list of neighbour metrics."""
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

    def extract_features(self, data, include_neighbors=True):
        """Extract features from UE data using the shared pipeline."""
        features, n_count, names = pipeline.build_model_features(
            data,
            base_feature_names=self.base_feature_names,
            neighbor_count=self.neighbor_count,
            include_neighbors=include_neighbors,
            init_lock=self._init_lock,
            feature_names=self.feature_names,
        )
        self.neighbor_count = n_count
        self.feature_names = names
        return features

    def predict(self, features):
        """Predict the optimal antenna for the UE."""
        # Convert features to the format expected by the model
        X = np.array([[features[name] for name in self.feature_names]])

        try:
            # Perform a single prediction attempt via probabilities
            with self._model_lock:
                probabilities = self.model.predict_proba(X)[0]
                classes_ = self.model.classes_
            idx = int(np.argmax(probabilities))
            antenna_id = classes_[idx]
            confidence = float(probabilities[idx])
        except (lgb.basic.LightGBMError, NotFittedError) as exc:
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
        """Train the model with provided data.

        This method acquires the model lock to ensure that no concurrent
        prediction is performed while the estimator object is being
        replaced by a newly-trained one.
        """
        if not training_data:
            raise ValueError("Training data cannot be empty")
        
        # Extract features and labels from training data
        X = []
        y = []

        for sample in training_data:
            features = self.extract_features(sample)
            feature_vector = [features[name] for name in self.feature_names]

            # The label is the optimal antenna ID
            label = sample.get("optimal_antenna")
            if label is None:
                raise ValueError(f"Sample missing 'optimal_antenna' label: {sample}")

            X.append(feature_vector)
            y.append(label)

        # Convert to numpy arrays
        X = np.array(X)
        y = np.array(y)

        # Thread-safe training with lock
        with self._model_lock:
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

    def save(
        self,
        path: str | None = None,
        *,
        model_type: str = "lightgbm",
        metrics: dict | None = None,
        version: str = MODEL_VERSION,
    ) -> bool:
        """Persist the model and accompanying metadata.

        Parameters
        ----------
        path:
            Optional path overriding ``self.model_path``.
        model_type:
            String describing the model implementation.
        metrics:
            Optional training metrics to store in the metadata file.
        version:
            Semantic version of the persisted format.
        """

        save_path = path or self.model_path
        if not save_path:
            return False
        save_path = str(save_path)

        # Thread-safe model saving
        with self._model_lock:
            try:
                os.makedirs(os.path.dirname(save_path), exist_ok=True)
                
                # Create atomic save by writing to temporary file first
                temp_path = f"{save_path}.tmp"
                joblib.dump(
                    {
                        "model": self.model,
                        "feature_names": self.feature_names,
                        "neighbor_count": self.neighbor_count,
                    },
                    temp_path,
                )
                
                # Atomic move to final location
                os.replace(temp_path, save_path)
                
                # Save metadata
                meta = {
                    "model_type": model_type,
                    "trained_at": datetime.now(timezone.utc).isoformat(),
                    "version": version,
                }
                if metrics is not None:
                    meta["metrics"] = metrics
                
                meta_path = f"{save_path}.meta.json"
                temp_meta_path = f"{meta_path}.tmp"
                
                with open(temp_meta_path, "w", encoding="utf-8") as f:
                    json.dump(meta, f)
                
                # Atomic move for metadata
                os.replace(temp_meta_path, meta_path)
                
                return True
                
            except Exception as e:
                logger.error("Failed to save model to %s: %s", save_path, e)
                # Clean up temporary files if they exist
                for temp_file in [f"{save_path}.tmp", f"{save_path}.meta.json.tmp"]:
                    try:
                        if os.path.exists(temp_file):
                            os.remove(temp_file)
                    except OSError:
                        pass
                return False

    def load(self, path=None):
        """Load the model from disk with thread safety."""
        load_path = path or self.model_path
        if not load_path or not os.path.exists(load_path):
            return False
        
        # Thread-safe model loading
        with self._model_lock:
            try:
                data = joblib.load(load_path)
                if isinstance(data, dict) and "model" in data:
                    self.model = data["model"]
                    self.feature_names = data.get("feature_names", self.feature_names)
                    self.neighbor_count = data.get("neighbor_count", self.neighbor_count)
                else:
                    self.model = data
                
                logger.info("Successfully loaded model from %s", load_path)
                return True
                
            except Exception as e:
                logger.error("Failed to load model from %s: %s", load_path, e)
                return False
