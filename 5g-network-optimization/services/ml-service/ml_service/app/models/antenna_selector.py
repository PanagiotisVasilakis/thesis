"""Antenna selector model for 5G network optimization."""
import numpy as np
import lightgbm as lgb
import joblib
import os
import logging
import threading
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

import yaml

from ..initialization.model_init import MODEL_VERSION
from sklearn.exceptions import NotFittedError
from sklearn.preprocessing import StandardScaler
from ..features import pipeline
from ..features.transform_registry import (
    register_feature_transform,
    apply_feature_transforms,
)

from ..utils.env_utils import get_neighbor_count_from_env
from ..config.constants import (
    DEFAULT_FALLBACK_ANTENNA_ID,
    DEFAULT_FALLBACK_CONFIDENCE,
    DEFAULT_FALLBACK_RSRP,
    DEFAULT_FALLBACK_SINR,
    DEFAULT_FALLBACK_RSRQ,
    DEFAULT_LIGHTGBM_MAX_DEPTH,
    DEFAULT_LIGHTGBM_RANDOM_STATE,
    env_constants
)
from ..utils.exception_handler import (
    ExceptionHandler,
    ModelError,
    handle_exceptions,
    safe_execute
)
from ..utils.resource_manager import (
    global_resource_manager,
    ResourceType
)
from .async_model_operations import AsyncModelInterface, get_async_model_manager

FALLBACK_ANTENNA_ID = DEFAULT_FALLBACK_ANTENNA_ID
FALLBACK_CONFIDENCE = DEFAULT_FALLBACK_CONFIDENCE

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

# Default feature configuration path relative to this file
DEFAULT_FEATURE_CONFIG = (
    Path(__file__).resolve().parent.parent / "config" / "features.yaml"
)

# Fallback features used when the configuration file cannot be loaded
_FALLBACK_FEATURES = [
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


def _load_feature_config(path: str | Path) -> list[str]:
    """Load feature names and register transforms from configuration.

    The configuration file is expected to contain a ``base_features`` list where
    each entry may specify a ``name`` and an optional ``transform``.  Supported
    ``transform`` values are either keys of the transform registry or fully
    qualified Python import paths.  When provided, the transform is registered
    for the given feature name via :func:`register_feature_transform`.
    """
    cfg_path = Path(path)
    if not cfg_path.exists():
        raise FileNotFoundError(f"Feature config not found: {cfg_path}")

    with open(cfg_path, "r", encoding="utf-8") as f:
        if cfg_path.suffix.lower() in {".yaml", ".yml"}:
            data = yaml.safe_load(f) or {}
        else:
            data = json.load(f) or {}

    feats = data.get("base_features", [])
    names: list[str] = []
    for item in feats:
        if isinstance(item, dict):
            name = item.get("name")
            transform = item.get("transform")
            if name and transform:
                try:
                    register_feature_transform(str(name), str(transform))
                except Exception:  # noqa: BLE001 - ignore invalid transforms
                    pass
        else:
            name = str(item)
        if name:
            names.append(str(name))
    return names




class AntennaSelector(AsyncModelInterface):
    """ML model for selecting optimal antenna based on UE data."""

    # Guard lazy initialization of neighbour feature names. This initialization
    # may run during the first prediction call when ``extract_features`` is
    # invoked concurrently, so a lock ensures feature names are added only once.
    _init_lock = threading.Lock()

    def __init__(
        self,
        model_path: str | None = None,
        neighbor_count: int | None = None,
        *,
        config_path: str | None = None,
    ):
        """Initialize the model.

        Parameters
        ----------
        model_path:
            Optional path to a saved model.
        neighbor_count:
            If given, preallocate feature names for this many neighbouring
            antennas instead of determining the number dynamically on the first
            call to :meth:`extract_features`.
        config_path:
            Optional path to a YAML/JSON file specifying feature names and
            their transforms. Defaults to ``FEATURE_CONFIG_PATH`` environment
            variable or ``config/features.yaml``.
        """
        self.model_path = model_path
        # Thread-safety: protect concurrent reads/writes to the underlying estimator
        self._model_lock = threading.RLock()
        self.model = None
        self.scaler = StandardScaler()

        if config_path is None:
            config_path = os.environ.get("FEATURE_CONFIG_PATH", str(DEFAULT_FEATURE_CONFIG))

        try:
            names = _load_feature_config(config_path)
            if not names:
                raise ValueError("No base features defined")
            self.base_feature_names = names
        except Exception as exc:  # noqa: BLE001
            logging.getLogger(__name__).warning(
                "Failed to load feature config %s: %s; using defaults", config_path, exc
            )
            self.base_feature_names = list(_FALLBACK_FEATURES)

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
        
        # Register with resource manager
        self._resource_id = global_resource_manager.register_resource(
            self,
            ResourceType.MODEL,
            cleanup_method=self._cleanup_resources,
            metadata={
                "model_type": "AntennaSelector",
                "model_path": self.model_path,
                "neighbor_count": self.neighbor_count
            }
        )

    def _initialize_model(self):
        """Initialize a default LightGBM model."""
        self.model = lgb.LGBMClassifier(
            n_estimators=env_constants.N_ESTIMATORS,
            max_depth=DEFAULT_LIGHTGBM_MAX_DEPTH,
            random_state=DEFAULT_LIGHTGBM_RANDOM_STATE,
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
            rsrp = data.get("rsrp", DEFAULT_FALLBACK_RSRP)
            sinr = data.get("sinr")
            rsrq = data.get("rsrq")
            if sinr is None:
                sinr = DEFAULT_FALLBACK_SINR
            if rsrq is None:
                rsrq = DEFAULT_FALLBACK_RSRQ
            return rsrp, sinr, rsrq
        return DEFAULT_FALLBACK_RSRP, DEFAULT_FALLBACK_SINR, DEFAULT_FALLBACK_RSRQ

    def _neighbor_list(self, metrics: dict, current: str | None, include: bool) -> list:
        """Return sorted list of neighbour metrics."""
        if not include or not metrics:
            return []
        neighbors = [
            (
                aid,
                vals.get("rsrp", DEFAULT_FALLBACK_RSRP),
                vals.get("sinr") if vals.get("sinr") is not None else DEFAULT_FALLBACK_SINR,
                vals.get("rsrq") if vals.get("rsrq") is not None else DEFAULT_FALLBACK_RSRQ,
                vals.get("cell_load"),
            )
            for aid, vals in metrics.items()
            if aid != current
        ]
        neighbors.sort(key=lambda x: x[1], reverse=True)
        return neighbors

    def extract_features(self, data, include_neighbors=True):
        """Extract features from UE data with performance optimizations.

        Performance improvements:
        - Reduced dictionary lookups with batch extraction
        - Pre-allocated feature dictionary
        - Optimized neighbor processing
        - Cached default values
        - Feature extraction caching for repeated requests
        """
        # Try to get cached features first
        ue_id = data.get("ue_id")
        if ue_id:
            from ..utils.feature_cache import feature_cache

            cached_features = feature_cache.get(ue_id, data)
            if cached_features is not None:
                return cached_features

        # Batch extract common values to reduce dict.get() calls
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
        
        # Optimized handover count extraction
        if "handover_count" in data:
            handover_count = data["handover_count"]
        else:
            hist = data.get("handover_history")
            handover_count = len(hist) if isinstance(hist, list) else 0
        
        # Optimized direction processing with caching
        direction = data.get("direction", (0, 0, 0))
        if isinstance(direction, (list, tuple)) and len(direction) >= 2:
            from ..utils.feature_cache import _cached_direction_to_unit
            direction_tuple = tuple(direction[:3]) if len(direction) >= 3 else (direction[0], direction[1], 0)
            dx, dy = _cached_direction_to_unit(direction_tuple)
        else:
            dx, dy = 0.0, 0.0
        
        # Batch RF metrics processing
        rf_metrics = data.get("rf_metrics", {})
        current_antenna = data.get("connected_to")
        rsrp_curr, sinr_curr, rsrq_curr = self._current_signal(current_antenna, rf_metrics)
        
        # Pre-allocate features dictionary with known size
        base_feature_count = len(self.base_feature_names) + (self.neighbor_count * 4) + 3
        features = {}
        features.update({
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
        })

        # Optimized neighbor processing
        neighbors = self._neighbor_list(rf_metrics, current_antenna, include_neighbors)
        best_rsrp, best_sinr, best_rsrq = rsrp_curr, sinr_curr, rsrq_curr
        if neighbors:
            # Extract best values from first neighbor (already sorted)
            first_neighbor = neighbors[0]
            best_rsrp, best_sinr, best_rsrq = first_neighbor[1], first_neighbor[2], first_neighbor[3]

        # Thread-safe neighbor count initialization
        if self.neighbor_count == 0:
            with self._init_lock:
                if self.neighbor_count == 0:
                    self.neighbor_count = len(neighbors)
                    # Batch extend feature names
                    new_features = []
                    for idx in range(self.neighbor_count):
                        new_features.extend([
                            f"rsrp_a{idx+1}",
                            f"sinr_a{idx+1}",
                            f"rsrq_a{idx+1}",
                            f"neighbor_cell_load_a{idx+1}",
                        ])
                    self.feature_names.extend(new_features)

        # Optimized neighbor feature extraction with batch updates
        neighbor_updates = {}
        for idx in range(self.neighbor_count):
            if idx < len(neighbors):
                neighbor = neighbors[idx]
                neighbor_updates.update({
                    f"rsrp_a{idx+1}": neighbor[1],
                    f"sinr_a{idx+1}": neighbor[2],
                    f"rsrq_a{idx+1}": neighbor[3],
                    f"neighbor_cell_load_a{idx+1}": neighbor[4] if neighbor[4] is not None else 0
                })
            else:
                # Use batch update for default values
                neighbor_updates.update({
                    f"rsrp_a{idx+1}": -120,
                    f"sinr_a{idx+1}": 0,
                    f"rsrq_a{idx+1}": -30,
                    f"neighbor_cell_load_a{idx+1}": 0
                })
        
        # Batch update neighbor features
        features.update(neighbor_updates)
        
        # Add difference features
        features.update({
            "best_rsrp_diff": best_rsrp - rsrp_curr,
            "best_sinr_diff": best_sinr - sinr_curr,
            "best_rsrq_diff": best_rsrq - rsrq_curr,
        })

        # Apply configured feature transformations via registry
        apply_feature_transforms(features)

        # Cache the extracted features for future use
        if ue_id:
            from ..utils.feature_cache import feature_cache
            feature_cache.put(ue_id, data, features)
        
        return features

    def predict(self, features):
        """Predict the optimal antenna for the UE."""
        # Convert features to the format expected by the model and scale
        X = np.array([[features[name] for name in self.feature_names]], dtype=float)
        if self.scaler:
            try:
                X = self.scaler.transform(X)
            except NotFittedError:
                pass

        def _perform_prediction():
            # Perform a single prediction attempt via probabilities
            with self._model_lock:
                probabilities = self.model.predict_proba(X)[0]
                classes_ = self.model.classes_
            idx = int(np.argmax(probabilities))
            antenna_id = classes_[idx]
            confidence = float(probabilities[idx])
            return {"antenna_id": antenna_id, "confidence": confidence}
        
        # Use safe execution with fallback
        ue_id = features.get("ue_id", "unknown")
        result = safe_execute(
            _perform_prediction,
            context=f"Model prediction for UE {ue_id}",
            default_return={
                "antenna_id": FALLBACK_ANTENNA_ID,
                "confidence": FALLBACK_CONFIDENCE,
            },
            exceptions=(lgb.basic.LightGBMError, NotFittedError, Exception),
            logger_name="AntennaSelector"
        )
        
        if result["antenna_id"] == FALLBACK_ANTENNA_ID:
            # Explicit warning to surface when the model falls back to defaults
            logger.warning(
                "Using default antenna for UE %s due to prediction error",
                ue_id,
            )

        return result

    async def predict_async(self, features: Dict[str, Any], priority: int = 5, timeout: Optional[float] = None) -> Dict[str, Any]:
        """Async prediction using the async model manager."""
        async_manager = get_async_model_manager()
        return await async_manager.predict_async(self, features, priority, timeout)

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

        # Convert to numpy arrays and scale
        X = np.array(X, dtype=float)
        y = np.array(y)
        self.scaler.fit(X)
        X = self.scaler.transform(X)

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

    async def train_async(self, training_data: List[Dict[str, Any]], priority: int = 3, timeout: Optional[float] = None) -> Dict[str, Any]:
        """Async training using the async model manager."""
        async_manager = get_async_model_manager()
        return await async_manager.train_async(self, training_data, priority, timeout)

    async def evaluate_async(self, test_data: List[Dict[str, Any]], priority: int = 7, timeout: Optional[float] = None) -> Dict[str, Any]:
        """Async evaluation using the async model manager."""
        async_manager = get_async_model_manager()
        return await async_manager.evaluate_async(self, test_data, priority, timeout)

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
                        "scaler": self.scaler,
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
                    self.scaler = data.get("scaler", StandardScaler())
                else:
                    self.model = data
                
                logger.info("Successfully loaded model from %s", load_path)
                return True
                
            except Exception as e:
                logger.error("Failed to load model from %s: %s", load_path, e)
                return False
    
    def _cleanup_resources(self) -> None:
        """Clean up model resources."""
        try:
            # Clear model data
            self.model = None
            
            # Clear feature data
            self.feature_names.clear()
            
            # Unregister from resource manager
            if hasattr(self, '_resource_id') and self._resource_id:
                global_resource_manager.unregister_resource(self._resource_id, force_cleanup=False)
                self._resource_id = None
            
            logger.info("AntennaSelector resources cleaned up")
        except Exception as e:
            logger.error("Error cleaning up AntennaSelector resources: %s", e)
