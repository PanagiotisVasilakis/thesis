"""Antenna selector model for 5G network optimization."""
import numpy as np
import lightgbm as lgb
import joblib
import os
import logging
import threading
import json
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, cast

import yaml

from sklearn.exceptions import NotFittedError
from sklearn.preprocessing import StandardScaler
from ..features import pipeline
from ..core.qos import qos_from_request
from ..features.transform_registry import (
    register_feature_transform,
    apply_feature_transforms,
)
from ..data.feature_extractor import HandoverTracker
from ..data import AntennaQoSProfiler, QoSHistoryTracker
from ..core.adaptive_qos import adaptive_qos_manager

from ..utils.env_utils import get_neighbor_count_from_env
from ..config.constants import (
    DEFAULT_FALLBACK_ANTENNA_ID,
    DEFAULT_FALLBACK_CONFIDENCE,
    DEFAULT_FALLBACK_RSRP,
    DEFAULT_FALLBACK_SINR,
    DEFAULT_FALLBACK_RSRQ,
    DEFAULT_LIGHTGBM_MAX_DEPTH,
    DEFAULT_LIGHTGBM_RANDOM_STATE,
    DEFAULT_PREDICTION_HISTORY_LIMIT,
    DEFAULT_DIVERSITY_WINDOW_SIZE,
    DEFAULT_DIVERSITY_MIN_RATIO,
    DEFAULT_MIN_TRAINING_SAMPLES,
    DEFAULT_MIN_TRAINING_CLASSES,
    DEFAULT_IMMEDIATE_RETURN_CONFIDENCE,
    env_constants,
)
from ..config.feature_specs import sanitize_feature_ranges, validate_feature_ranges
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
from ..utils.type_helpers import safe_float
from .async_model_operations import AsyncModelInterface, get_async_model_manager
from .ping_pong_prevention import PingPongPrevention
from .qos_bias import QoSBiasManager
from ..monitoring import metrics
from ..config.cells import CELL_CONFIGS, get_cell_config, haversine_distance
from ..initialization.model_version import MODEL_VERSION

FALLBACK_ANTENNA_ID = DEFAULT_FALLBACK_ANTENNA_ID
FALLBACK_CONFIDENCE = DEFAULT_FALLBACK_CONFIDENCE

logger = logging.getLogger(__name__)

DEFAULT_QOS_FEATURES = {
    "service_type": "default",
    "service_type_label": "default",
    "service_priority": 5,
    "latency_requirement_ms": 50.0,
    "throughput_requirement_mbps": 100.0,
    "jitter_ms": 5.0,
    "reliability_pct": 99.0,
    "latency_ms": 50.0,
    "throughput_mbps": 100.0,
    "packet_loss_rate": 0.0,
    "observed_latency_ms": 50.0,
    "observed_throughput_mbps": 100.0,
    "observed_jitter_ms": 5.0,
    "observed_packet_loss_rate": 0.0,
    "latency_delta_ms": 0.0,
    "throughput_delta_mbps": 0.0,
    "reliability_delta_pct": 1.0,
}

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
    "stability": 0.5,
    "latency_pressure_ratio": 0.0,
    "throughput_headroom_ratio": 0.0,
    "reliability_pressure_ratio": 0.0,
    "sla_pressure": 0.0,
    "rf_load_std": 0.0,
    "top2_rsrp_gap": 0.0,
    "top2_sinr_gap": 0.0,
    "optimal_score_margin": 0.0,
    "connected_signal_rank": 1.0,
    "rsrp_current": -90,
    "sinr_current": 10,
    "rsrq_current": -10,
    "best_rsrp_diff": 0.0,
    "best_sinr_diff": 0.0,
    "best_rsrq_diff": 0.0,
    "altitude": 0.0,
    **DEFAULT_QOS_FEATURES,
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

    @staticmethod
    def _safe_float(value: Any, fallback: float) -> float:
        """Return ``value`` as float with ``fallback`` on failure.
        
        Note: Delegates to shared utils.type_helpers.safe_float.
        """
        return safe_float(value, fallback)

    def _apply_qos_defaults(self, features: Dict[str, Any]) -> None:
        """Ensure QoS-related features exist and remain numerically consistent."""

        for key, value in DEFAULT_QOS_FEATURES.items():
            if key not in features or features[key] is None:
                features[key] = value

        # Normalise string label for downstream reporting
        svc_label = features.get("service_type_label")
        if not svc_label:
            svc_label = features.get("service_type", DEFAULT_QOS_FEATURES["service_type"])
        features["service_type_label"] = str(svc_label)

        latency_req = self._safe_float(
            features.get("latency_requirement_ms"),
            DEFAULT_QOS_FEATURES["latency_requirement_ms"],
        )
        latency_obs = self._safe_float(features.get("latency_ms"), latency_req)

        throughput_req = self._safe_float(
            features.get("throughput_requirement_mbps"),
            DEFAULT_QOS_FEATURES["throughput_requirement_mbps"],
        )
        throughput_obs = self._safe_float(features.get("throughput_mbps"), throughput_req)

        jitter_req = self._safe_float(features.get("jitter_ms"), DEFAULT_QOS_FEATURES["jitter_ms"])
        observed_jitter = self._safe_float(features.get("observed_jitter_ms"), jitter_req)

        reliability_req = self._safe_float(features.get("reliability_pct"), DEFAULT_QOS_FEATURES["reliability_pct"])
        observed_packet_loss = self._safe_float(
            features.get("observed_packet_loss_rate"),
            DEFAULT_QOS_FEATURES["observed_packet_loss_rate"],
        )
        packet_loss = self._safe_float(features.get("packet_loss_rate"), observed_packet_loss)
        observed_latency = self._safe_float(features.get("observed_latency_ms"), latency_obs)
        observed_throughput = self._safe_float(features.get("observed_throughput_mbps"), throughput_obs)

        reliability_observed = max(0.0, 100.0 - observed_packet_loss)

        features["latency_requirement_ms"] = latency_req
        features["latency_ms"] = latency_obs
        features["latency_delta_ms"] = self._safe_float(
            features.get("latency_delta_ms"),
            latency_obs - latency_req,
        )

        features["throughput_requirement_mbps"] = throughput_req
        features["throughput_mbps"] = throughput_obs
        features["throughput_delta_mbps"] = self._safe_float(
            features.get("throughput_delta_mbps"),
            throughput_obs - throughput_req,
        )

        features["jitter_ms"] = jitter_req
        features["observed_jitter_ms"] = observed_jitter

        features["reliability_pct"] = reliability_req
        features["observed_packet_loss_rate"] = observed_packet_loss
        features["packet_loss_rate"] = packet_loss
        features["reliability_delta_pct"] = self._safe_float(
            features.get("reliability_delta_pct"),
            reliability_observed - reliability_req,
        )

        features["observed_latency_ms"] = observed_latency
        features["observed_throughput_mbps"] = observed_throughput

        # Ensure service priority is integral
        try:
            features["service_priority"] = int(features.get("service_priority", DEFAULT_QOS_FEATURES["service_priority"]))
        except (TypeError, ValueError):
            features["service_priority"] = int(DEFAULT_QOS_FEATURES["service_priority"])

        # Normalise auxiliary QoS containers for downstream consumers
        if not isinstance(features.get("observed_qos"), dict):
            features["observed_qos"] = {
                "latency_ms": observed_latency,
                "throughput_mbps": observed_throughput,
                "jitter_ms": observed_jitter,
                "packet_loss_rate": observed_packet_loss,
            }
        if not isinstance(features.get("observed_qos_summary"), dict):
            features["observed_qos_summary"] = {"latest": features["observed_qos"]}

    def _prepare_features_for_model(self, features: Dict[str, Any]) -> Dict[str, Any]:
        """Return a copy of ``features`` ready for numerical model ingestion."""

        prepared = dict(features)
        self._apply_qos_defaults(prepared)

        service_type_raw = prepared.get("service_type", DEFAULT_QOS_FEATURES["service_type"])
        prepared["service_type_label"] = str(prepared.get("service_type_label") or service_type_raw)

        if not isinstance(service_type_raw, (int, float)):
            try:
                from ..core.qos_encoding import encode_service_type

                prepared["service_type"] = encode_service_type(service_type_raw)
            except Exception:
                from ..core.qos_encoding import encode_service_type

                prepared["service_type"] = encode_service_type(DEFAULT_QOS_FEATURES["service_type"])
        else:
            prepared["service_type"] = float(service_type_raw)

        return prepared

    def _default_feature_value(self, name: str) -> float | int:
        """Return a safe default for missing features used by the model."""

        if name in DEFAULT_TEST_FEATURES:
            return DEFAULT_TEST_FEATURES[name]
        if name in DEFAULT_QOS_FEATURES:
            return DEFAULT_QOS_FEATURES[name]
        if name.startswith("rsrp_"):
            return DEFAULT_FALLBACK_RSRP
        if name.startswith("sinr_"):
            return DEFAULT_FALLBACK_SINR
        if name.startswith("rsrq_"):
            return DEFAULT_FALLBACK_RSRQ
        if name.startswith("neighbor_cell_load"):
            return 0.0
        if name.endswith("handover_count_1min") or name.endswith("time_since_last_handover"):
            return 0.0
        return 0.0

    def _ensure_feature_defaults(self, features: Dict[str, Any]) -> list[str]:
        """Populate missing feature names with safe defaults.

        Returns a list of feature names that required defaulting so callers
        can optionally trace or log the adjustments.
        """

        missing: list[str] = []
        for name in self.feature_names:
            if name not in features or features[name] is None:
                features[name] = self._default_feature_value(name)
                missing.append(name)
        return missing

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
        self.model: Optional[lgb.LGBMClassifier] = None
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

        # QoS-derived features are optional for validation; they will be
        # populated with safe defaults when absent.
        self.optional_feature_names = set(DEFAULT_QOS_FEATURES.keys())

        # Initialize handover tracker for ping-pong prevention
        self.handover_tracker = HandoverTracker()
        self.antenna_profiler = AntennaQoSProfiler()
        self.qos_history = QoSHistoryTracker()
        self.qos_bias_enabled = os.getenv("QOS_BIAS_ENABLED", "1").lower() not in {"0", "false", "no"}
        self.qos_bias_min_samples = int(os.getenv("QOS_BIAS_MIN_SAMPLES", "5"))
        self.qos_bias_success_threshold = float(os.getenv("QOS_BIAS_SUCCESS_THRESHOLD", "0.9"))
        self.qos_bias_min_multiplier = float(os.getenv("QOS_BIAS_MIN_MULTIPLIER", "0.35"))
        
        # Anti-ping-pong configuration from environment
        self.min_handover_interval_s = float(os.getenv("MIN_HANDOVER_INTERVAL_S", "2.0"))
        self.max_handovers_per_minute = int(os.getenv("MAX_HANDOVERS_PER_MINUTE", "3"))
        self.pingpong_window_s = float(os.getenv("PINGPONG_WINDOW_S", "10.0"))
        self.pingpong_confidence_boost = float(os.getenv("PINGPONG_CONFIDENCE_BOOST", "0.9"))
        
        # Modular components for ping-pong prevention and QoS bias
        # These encapsulate the logic for better testing and extensibility
        self.ping_pong_prevention = PingPongPrevention(
            min_interval_s=self.min_handover_interval_s,
            max_per_minute=self.max_handovers_per_minute,
            window_s=self.pingpong_window_s,
            confidence_boost=self.pingpong_confidence_boost,
        )
        self.qos_bias_manager = QoSBiasManager(
            enabled=self.qos_bias_enabled,
            min_samples=self.qos_bias_min_samples,
            success_threshold=self.qos_bias_success_threshold,
            min_multiplier=self.qos_bias_min_multiplier,
        )

        # Track recent predictions for diversity monitoring
        self._prediction_history: list[str] = []

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

    def _current_signal(self, current: str | None, metrics: dict) -> tuple[float, float, float]:
        """Wrapper around pipeline._current_signal for instance access."""
        return pipeline._current_signal(current, metrics)

    def _neighbor_list(
        self, metrics: dict, current: str | None, include: bool
    ) -> list[tuple[str, float, float, float, float | None]]:
        """Wrapper around pipeline._neighbor_list for instance access."""
        return pipeline._neighbor_list(metrics, current, include)

    def ensure_neighbor_capacity(self, desired_count: int) -> None:
        """Expand neighbour-derived features to accommodate ``desired_count`` antennas."""
        if desired_count <= self.neighbor_count:
            return
        with self._init_lock:
            if desired_count <= self.neighbor_count:
                return
            for idx in range(self.neighbor_count, desired_count):
                self.feature_names.extend(
                    [
                        f"rsrp_a{idx+1}",
                        f"sinr_a{idx+1}",
                        f"rsrq_a{idx+1}",
                        f"neighbor_cell_load_a{idx+1}",
                    ]
                )
            self.neighbor_count = desired_count

    def _initialize_model(self):
        """Initialize a default LightGBM model."""
        self.model = lgb.LGBMClassifier(
            n_estimators=env_constants.N_ESTIMATORS,
            max_depth=DEFAULT_LIGHTGBM_MAX_DEPTH,
            random_state=DEFAULT_LIGHTGBM_RANDOM_STATE,
        )


    def extract_features(self, data, include_neighbors=True):
        """Extract features from UE data with caching and shared pipeline."""

        ue_id = data.get("ue_id")
        if ue_id:
            from ..utils.feature_cache import feature_cache

            cached_features = feature_cache.get(ue_id, data)
            if cached_features is not None:
                missing_keys = [name for name in self.feature_names if name not in cached_features]
                if not missing_keys:
                    return cached_features

        features, neighbor_count, feature_names = pipeline.build_model_features(
            data,
            base_feature_names=self.base_feature_names,
            neighbor_count=self.neighbor_count,
            include_neighbors=include_neighbors,
            init_lock=self._init_lock,
            feature_names=self.feature_names,
        )

        # Derive QoS features from the incoming request payload. This keeps
        # the feature-extraction pipeline backward-compatible while enabling
        # downstream model training to use QoS-derived signals.
        try:
            qos = qos_from_request(data)
            # Merge and ensure features contain QoS keys
            features.setdefault("service_type", qos.get("service_type"))
            features.setdefault("service_priority", qos.get("service_priority"))
            features.setdefault("service_type_label", qos.get("service_type"))
            features.setdefault("latency_requirement_ms", qos.get("latency_requirement_ms"))
            features.setdefault("throughput_requirement_mbps", qos.get("throughput_requirement_mbps"))
            features.setdefault("reliability_pct", qos.get("reliability_pct"))
            # Observed QoS metrics (may come directly from telemetry)
            if "latency_ms" not in features:
                features["latency_ms"] = float(data.get("latency_ms", qos.get("latency_requirement_ms", 0.0) or 0.0))
            if "throughput_mbps" not in features:
                features["throughput_mbps"] = float(data.get("throughput_mbps", qos.get("throughput_requirement_mbps", 0.0) or 0.0))
            if "packet_loss_rate" not in features:
                features["packet_loss_rate"] = float(data.get("packet_loss_rate", 0.0) or 0.0)
            if "jitter_ms" not in features:
                features["jitter_ms"] = float(data.get("jitter_ms", 0.0) or 0.0)

            # Using shared safe_float from type_helpers
            def _safe_float_local(value: Any, fallback: float = 0.0) -> float:
                return safe_float(value, fallback)

            observed_raw = data.get("observed_qos")
            if not isinstance(observed_raw, dict):
                summary = data.get("observed_qos_summary")
                if isinstance(summary, dict):
                    observed_raw = summary.get("latest")

            observed_raw = observed_raw if isinstance(observed_raw, dict) else {}

            obs_latency = _safe_float_local(
                observed_raw.get("latency_ms"),
                fallback=features.get("latency_ms", qos.get("latency_requirement_ms", 0.0)) or 0.0,
            )
            obs_throughput = _safe_float_local(
                observed_raw.get("throughput_mbps"),
                fallback=features.get("throughput_mbps", qos.get("throughput_requirement_mbps", 0.0)) or 0.0,
            )
            obs_jitter = _safe_float_local(
                observed_raw.get("jitter_ms"),
                fallback=features.get("jitter_ms", 0.0) or 0.0,
            )
            obs_loss = _safe_float_local(
                observed_raw.get("packet_loss_rate"),
                fallback=features.get("packet_loss_rate", 0.0) or 0.0,
            )

            features["observed_latency_ms"] = obs_latency
            features["observed_throughput_mbps"] = obs_throughput
            features["observed_jitter_ms"] = obs_jitter
            features["observed_packet_loss_rate"] = obs_loss

            req_latency = _safe_float(qos.get("latency_requirement_ms"), fallback=0.0)
            req_throughput = _safe_float(qos.get("throughput_requirement_mbps"), fallback=0.0)
            req_reliability = _safe_float(qos.get("reliability_pct"), fallback=0.0)

            features["latency_delta_ms"] = obs_latency - req_latency
            features["throughput_delta_mbps"] = obs_throughput - req_throughput

            observed_reliability = max(0.0, 100.0 - obs_loss)
            features["reliability_delta_pct"] = observed_reliability - req_reliability
        except Exception:
            # Non-fatal: if QoS derivation fails, continue with base features
            pass
        # Preserve original `service_type` as provided (string) to remain
        # backward-compatible for callers and tests. Numeric encoding for
        # training is performed later when building the dataset.

        self._apply_qos_defaults(features)

        if neighbor_count != self.neighbor_count or feature_names is not self.feature_names:
            with self._init_lock:
                self.neighbor_count = neighbor_count
                self.feature_names = feature_names

        if ue_id:
            from ..utils.feature_cache import feature_cache

            feature_cache.put(ue_id, data, features)

        return features

    def predict(self, features):
        """Predict the optimal antenna for the UE with ping-pong prevention."""
        # Start timing for feature extraction stage
        _stage_start = time.time()
        
        prepared = self._prepare_features_for_model(features)
        self._ensure_feature_defaults(prepared)
        sanitize_feature_ranges(prepared)
        # Validate required features and their configured ranges
        validate_feature_ranges(prepared)

        # Convert features to the format expected by the model and scale
        # Ensure `service_type` is numeric for prediction as well
        try:
            from ml_service.app.core.qos_encoding import encode_service_type

            svc = prepared.get("service_type")
            if svc is not None and not isinstance(svc, (int, float)):
                prepared["service_type"] = encode_service_type(svc)
        except Exception:
            # non-fatal; let the eventual conversion raise if still invalid
            pass

        X = np.array([[prepared[name] for name in self.feature_names]], dtype=float)
        if self.scaler:
            try:
                X = self.scaler.transform(X)
            except NotFittedError:
                pass

        service_type_label = prepared.get("service_type_label") or prepared.get("service_type") or "default"
        if isinstance(service_type_label, (int, float)):
            service_type_label = str(service_type_label)
        
        # Record feature extraction latency (includes all preparation work)
        metrics.PREDICTION_STAGE_LATENCY.labels(stage='feature_extraction').observe(
            time.time() - _stage_start
        )

        fallback_payload = {
            "antenna_id": FALLBACK_ANTENNA_ID,
            "confidence": FALLBACK_CONFIDENCE,
            "qos_bias_applied": False,
            "_fallback_marker": True,
        }

        def _perform_prediction():
            # Perform a single prediction attempt via probabilities
            with self._model_lock:
                if self.model is None:
                    raise ModelError("Model is not initialized")

                # Use calibrated model if available (better confidence estimates)
                # Otherwise use base model
                prediction_model = getattr(self, 'calibrated_model', None) or self.model
                model = cast(lgb.LGBMClassifier, prediction_model if hasattr(prediction_model, 'classes_') else self.model)
                
                # Ensure the returned probabilities are a NumPy array so
                # indexing and numpy ops work correctly even if some
                # implementations return sparse-like objects.
                probas = np.asarray(prediction_model.predict_proba(X) if hasattr(prediction_model, 'predict_proba') else model.predict_proba(X))
                # If the estimator returns a 2D array (n_samples, n_classes)
                # take the first row; if it's already 1D use it as-is.
                if probas.ndim == 1:
                    probabilities = probas
                else:
                    probabilities = probas[0]
                
                # Get classes from base model (calibrated model wraps it)
                if hasattr(prediction_model, 'classes_'):
                    classes_ = np.asarray(prediction_model.classes_)
                else:
                    classes_ = np.asarray(model.classes_)

            adjusted_probabilities, bias_details, bias_applied = self._apply_qos_bias(
                probabilities,
                classes_,
                service_type_label,
            )

            if bias_applied:
                probabilities = adjusted_probabilities

            idx = int(np.argmax(probabilities))
            antenna_id = classes_[idx]
            confidence = float(probabilities[idx])
            
            result = {
                "antenna_id": antenna_id,
                "confidence": confidence
            }
            
            if bias_applied:
                result["qos_bias_applied"] = True
                result["qos_bias_service_type"] = service_type_label
                result["qos_bias_scores"] = bias_details
            else:
                result["qos_bias_applied"] = False

            # Add calibration indicator if calibrated model was used
            if hasattr(self, 'calibrated_model') and self.calibrated_model is not None:
                result["confidence_calibrated"] = True
            
            return result
        
        # Use safe execution with fallback
        ue_id = prepared.get("ue_id", "unknown")
        
        # Start timing for model inference stage
        _inference_start = time.time()
        result = safe_execute(
            _perform_prediction,
            context=f"Model prediction for UE {ue_id}",
            default_return=fallback_payload,
            exceptions=(lgb.basic.LightGBMError, NotFittedError, Exception),
            logger_name="AntennaSelector"
        )
        # Record model inference latency
        metrics.PREDICTION_STAGE_LATENCY.labels(stage='model_inference').observe(
            time.time() - _inference_start
        )

        fallback_used = bool(result.pop("_fallback_marker", False))
        
        if fallback_used:
            logger.warning(
                "Using default antenna for UE %s due to prediction error",
                ue_id,
            )
            result.setdefault("anti_pingpong_applied", False)
            # Record zero time for ping-pong stage when using fallback
            # (ensures consistent metric cardinality)
            metrics.PREDICTION_STAGE_LATENCY.labels(stage='ping_pong_check').observe(0.0)
            return result
        
        predicted_antenna = str(result["antenna_id"])
        confidence = float(result.get("confidence", 0.0))

        # --------------------------------------------------------------
        # Geographic validation and override if prediction is implausible
        # --------------------------------------------------------------
        ue_lat = prepared.get("latitude")
        ue_lon = prepared.get("longitude")

        if isinstance(ue_lat, (int, float)) and isinstance(ue_lon, (int, float)):
            cell_config = get_cell_config(predicted_antenna)
            if cell_config:
                try:
                    distance = haversine_distance(
                        float(ue_lat),
                        float(ue_lon),
                        float(cell_config["latitude"]),
                        float(cell_config["longitude"]),
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Failed geographic check for %s: %s", predicted_antenna, exc)
                    distance = None

                if distance is not None:
                    max_distance = float(cell_config["radius_meters"]) * float(
                        cell_config.get("max_distance_multiplier", 2.0)
                    )

                    if distance > max_distance:
                        # Find nearest configured cell to fall back to
                        nearest_id = None
                        nearest_distance = None
                        for antenna_id, config in CELL_CONFIGS.items():
                            try:
                                dist = haversine_distance(
                                    float(ue_lat),
                                    float(ue_lon),
                                    float(config["latitude"]),
                                    float(config["longitude"]),
                                )
                            except Exception:  # noqa: BLE001
                                continue

                            if nearest_distance is None or dist < nearest_distance:
                                nearest_distance = dist
                                nearest_id = antenna_id

                        if nearest_id:
                            logger.warning(
                                "Geographic override: UE %s predicted %s at %.0fm (> %.0fm); overriding to %s",
                                ue_id,
                                predicted_antenna,
                                distance,
                                max_distance,
                                nearest_id,
                            )

                            metrics.GEOGRAPHIC_OVERRIDES.inc()
                            result["fallback_reason"] = "geographic_override"
                            result["ml_prediction"] = predicted_antenna
                            result["distance_to_ml_prediction"] = float(distance)
                            if nearest_distance is not None:
                                result["distance_to_fallback"] = float(nearest_distance)

                            predicted_antenna = nearest_id
                            confidence = 1.0
                            result["antenna_id"] = nearest_id
                            result["confidence"] = confidence

        # --------------------------------------------------------------
        # Diversity monitoring for collapse detection in production
        # --------------------------------------------------------------
        self._prediction_history.append(predicted_antenna)
        if len(self._prediction_history) > DEFAULT_PREDICTION_HISTORY_LIMIT:
            self._prediction_history.pop(0)

        if len(self._prediction_history) >= DEFAULT_DIVERSITY_WINDOW_SIZE:
            window = self._prediction_history[-DEFAULT_DIVERSITY_WINDOW_SIZE:]
            unique_predictions = len(set(window))
            diversity_ratio = unique_predictions / float(DEFAULT_DIVERSITY_WINDOW_SIZE)

            if diversity_ratio < DEFAULT_DIVERSITY_MIN_RATIO:
                logger.error(
                    "ML diversity warning for UE %s: only %d unique predictions in last 50 (%.1f%%)",
                    ue_id,
                    unique_predictions,
                    diversity_ratio * 100,
                )
                metrics.LOW_DIVERSITY_WARNINGS.inc()
                result.setdefault("warnings", []).append(
                    {
                        "type": "low_diversity",
                        "unique_predictions": unique_predictions,
                        "window": DEFAULT_DIVERSITY_WINDOW_SIZE,
                        "diversity_ratio": diversity_ratio,
                    }
                )

        # ==================================================================
        # PING-PONG PREVENTION LOGIC (Critical for Thesis)
        # ==================================================================
        # Start timing for ping-pong check stage
        _pingpong_start = time.time()
        
        current_cell = prepared.get("connected_to")
        timestamp = time.time()
        
        # Track handover state and get metrics
        if current_cell:
            handover_count, time_since_last = self.handover_tracker.update_handover_state(
                ue_id, current_cell, timestamp
            )
        else:
            handover_count = 0
            time_since_last = float("inf")
        
        # Only apply ping-pong prevention if prediction suggests a handover
        if current_cell and predicted_antenna != current_cell:
            original_antenna = predicted_antenna
            suppression_reason = None
            
            # Check 1: Too many handovers in rolling window (ping-pong detection)
            if handover_count >= self.max_handovers_per_minute:
                handovers_in_window = self.handover_tracker.get_handovers_in_window(ue_id, 60.0)
                if handovers_in_window >= self.max_handovers_per_minute:
                    logger.warning(
                        f"Ping-pong detected for {ue_id}: {handovers_in_window} "
                        f"handovers in last 60s (limit: {self.max_handovers_per_minute})"
                    )
                    # Require much higher confidence to handover
                    if confidence < self.pingpong_confidence_boost:
                        predicted_antenna = current_cell
                        confidence = 1.0
                        suppression_reason = "too_many"
            
            # Check 2: Too recent (minimum interval between handovers)
            if suppression_reason is None and time_since_last < self.min_handover_interval_s:
                logger.debug(
                    f"Suppressing handover for {ue_id}: too recent "
                    f"({time_since_last:.1f}s < {self.min_handover_interval_s}s)"
                )
                predicted_antenna = current_cell
                confidence = 1.0  # High confidence to stay
                suppression_reason = "too_recent"
            
            # Check 3: Immediate ping-pong (handover back to recent cell)
            if suppression_reason is None:
                is_pingpong = self.handover_tracker.check_immediate_pingpong(
                    ue_id, predicted_antenna, self.pingpong_window_s
                )
                if is_pingpong:
                    logger.warning(
                        f"Immediate ping-pong detected for {ue_id}: "
                        f"trying to return to {predicted_antenna} within {self.pingpong_window_s}s"
                    )
                    # Require high confidence to return to recent cell
                    if confidence < DEFAULT_IMMEDIATE_RETURN_CONFIDENCE:
                        predicted_antenna = current_cell
                        confidence = 1.0
                        suppression_reason = "immediate_return"
            
            # Record metrics if handover was suppressed
            if suppression_reason:
                metrics.PING_PONG_SUPPRESSIONS.labels(reason=suppression_reason).inc()
                result["anti_pingpong_applied"] = True
                result["suppression_reason"] = suppression_reason
                result["original_prediction"] = original_antenna
                logger.info(
                    f"Ping-pong prevention: {ue_id} stays on {current_cell} "
                    f"instead of {original_antenna} (reason: {suppression_reason})"
                )
            else:
                result["anti_pingpong_applied"] = False
            
            # Update final result
            result["antenna_id"] = predicted_antenna
            result["confidence"] = confidence
        else:
            # No handover suggested, no ping-pong prevention needed
            result["anti_pingpong_applied"] = False
        
        # Record handover interval for analytics
        if current_cell and time_since_last != float("inf") and time_since_last > 0:
            metrics.HANDOVER_INTERVAL.observe(time_since_last)
        
        # Record ping-pong check latency
        metrics.PREDICTION_STAGE_LATENCY.labels(stage='ping_pong_check').observe(
            time.time() - _pingpong_start
        )
        
        # Add handover tracking metadata to result when applicable
        if current_cell:
            result["handover_count_1min"] = handover_count
            result["time_since_last_handover"] = time_since_last

        if result.get("qos_bias_applied"):
            logger.info(
                "QoS bias applied for UE %s (service=%s, penalties=%s)",
                ue_id,
                service_type_label,
                result.get("qos_bias_scores"),
            )

        return result

    def _apply_qos_bias(
        self,
        probabilities: np.ndarray,
        classes_: np.ndarray,
        service_type: str | None,
    ) -> tuple[np.ndarray, Dict[str, float], bool]:
        """Reduce probabilities for antennas with poor QoS track record."""

        if not self.qos_bias_enabled or not getattr(self, "antenna_profiler", None):
            return probabilities, {}, False

        service_label = (service_type or "default").lower()
        adjusted = probabilities.astype(float).copy()
        bias_details: Dict[str, float] = {}
        bias_applied = False

        for idx, antenna in enumerate(classes_):
            antenna_id = str(antenna)
            profile = self.antenna_profiler.get_profile(antenna_id, service_label)
            success_rate = profile.get("success_rate")
            sample_count = profile.get("sample_count", 0)
            if success_rate is None or sample_count < self.qos_bias_min_samples:
                continue

            if success_rate < self.qos_bias_success_threshold:
                penalty = max(
                    self.qos_bias_min_multiplier,
                    success_rate / self.qos_bias_success_threshold,
                )
                adjusted[idx] *= penalty
                bias_details[antenna_id] = float(penalty)
                bias_applied = True

        if not bias_applied:
            return probabilities, bias_details, False

        total = adjusted.sum()
        if total <= 0:
            return probabilities, bias_details, False

        adjusted /= total
        return adjusted, bias_details, True

    def record_qos_feedback(
        self,
        *,
        ue_id: str,
        antenna_id: str,
        service_type: str,
        metrics: Dict[str, float],
        passed: bool,
        confidence: float = 0.0,
        qos_requirements: Dict[str, float] | None = None,
        timestamp: float | None = None,
    ) -> None:
        metrics_clean: Dict[str, float] = {}
        for key, value in (metrics or {}).items():
            try:
                metrics_clean[key] = float(value)
            except (TypeError, ValueError):
                continue

        self.qos_history.record(
            ue_id=ue_id,
            service_type=service_type,
            metrics=metrics_clean,
            passed=passed,
            timestamp=timestamp,
        )

        self.antenna_profiler.record(
            antenna_id=antenna_id,
            service_type=service_type,
            metrics=metrics_clean,
            passed=passed,
            timestamp=timestamp,
        )

        adaptive_qos_manager.observe_feedback(service_type, passed)

    def get_qos_history_snapshot(self, ue_id: str, window_seconds: float | None = None) -> Dict[str, object]:
        return self.qos_history.get_qos_history(ue_id, window_seconds)

    def get_antenna_profile(self, antenna_id: str, service_type: str) -> Dict[str, object]:
        return self.antenna_profiler.get_profile(antenna_id, service_type)

    def get_adaptive_required_confidence(self, service_type: str, priority: int) -> float:
        return adaptive_qos_manager.get_required_confidence(service_type, priority)

    async def predict_async(self, features: Dict[str, Any], priority: int = 5, timeout: Optional[float] = None) -> Dict[str, Any]:
        """Async prediction using the async model manager."""
        async_manager = get_async_model_manager()
        return await async_manager.predict_async(self, features, priority, timeout)

    def train(self, training_data):
        """Train the model with provided data.

        This method acquires the model lock to ensure that no concurrent
        prediction is performed while the estimator object is being
        replaced by a newly-trained one.
        
        Raises:
            ValueError: If training data is invalid (too few samples, missing
                labels, insufficient class diversity).
        """
        # ================================================================
        # TRAINING DATA VALIDATION (Production-Critical)
        # ================================================================
        if not training_data:
            raise ValueError("Training data cannot be empty")
        
        # Check minimum sample count
        if len(training_data) < DEFAULT_MIN_TRAINING_SAMPLES:
            raise ValueError(
                f"Insufficient training samples: {len(training_data)} < "
                f"{DEFAULT_MIN_TRAINING_SAMPLES} minimum required"
            )
        
        # Extract and validate labels
        labels = []
        missing_label_indices = []
        for i, sample in enumerate(training_data):
            label = sample.get("optimal_antenna")
            if label is None:
                missing_label_indices.append(i)
            labels.append(label)
        
        if missing_label_indices:
            raise ValueError(
                f"{len(missing_label_indices)} samples missing 'optimal_antenna' label "
                f"(first 5 indices: {missing_label_indices[:5]})"
            )
        
        # Check class diversity
        unique_labels = set(labels)
        if len(unique_labels) < DEFAULT_MIN_TRAINING_CLASSES:
            raise ValueError(
                f"Insufficient class diversity: {len(unique_labels)} unique classes, "
                f"need at least {DEFAULT_MIN_TRAINING_CLASSES}"
            )
        
        # Log class distribution for debugging
        from collections import Counter
        label_counts = Counter(labels)
        logger.info(
            "Training data validation passed: %d samples, %d classes, distribution: %s",
            len(training_data), len(unique_labels), dict(label_counts)
        )
        
        # Extract features and labels from training data
        X = []
        y = []

        for sample in training_data:
            extracted = self.extract_features(sample)
            features = self._prepare_features_for_model(extracted)
            self._ensure_feature_defaults(features)
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
            model = cast(lgb.LGBMClassifier, self.model)
            model.fit(X, y)
            
            # Return training metrics
            return {
                "samples": len(X),
                "classes": len(set(y)),
                "feature_importance": dict(
                    zip(self.feature_names, cast(lgb.LGBMClassifier, self.model).feature_importances_)
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
        version: str | None = None,
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

        if version is None:
            version = MODEL_VERSION

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

                # Save scaler separately
                scaler_path = f"{save_path}.scaler"
                temp_scaler_path = f"{scaler_path}.tmp"
                joblib.dump(self.scaler, temp_scaler_path)
                os.replace(temp_scaler_path, scaler_path)

                # Save metadata
                # Allow metadata values to be heterogeneous (numbers, dicts,
                # lists) by typing the metadata map as Dict[str, Any]. This
                # prevents static type-checkers from assuming all values are
                # strings when we later attach `metrics` as a dict.
                meta: Dict[str, Any] = {
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
                temp_files = [
                    f"{save_path}.tmp",
                    f"{save_path}.meta.json.tmp",
                    f"{save_path}.scaler.tmp",
                ]
                for temp_file in temp_files:
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
                    self.model = cast(lgb.LGBMClassifier, data["model"])
                    self.feature_names = data.get("feature_names", self.feature_names)
                    self.neighbor_count = data.get("neighbor_count", self.neighbor_count)
                else:
                    self.model = cast(lgb.LGBMClassifier, data)

                # Load scaler from separate file if available, else fallback to legacy
                scaler_path = f"{load_path}.scaler"
                if os.path.exists(scaler_path):
                    self.scaler = joblib.load(scaler_path)
                elif isinstance(data, dict):
                    self.scaler = data.get("scaler", StandardScaler())
                else:
                    self.scaler = StandardScaler()

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
