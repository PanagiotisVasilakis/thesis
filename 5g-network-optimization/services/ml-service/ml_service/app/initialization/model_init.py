"""Model initialization utilities."""
import logging
from collections import deque
import os
import json
import threading

# Semantic version of the expected model format. Bump whenever the
# persisted model or metadata structure changes in a backwards incompatible
# way so older files can be detected gracefully.
MODEL_VERSION = "1.0"
from ..errors import ModelError
from ..models import (
    LightGBMSelector,
    LSTMSelector,
    EnsembleSelector,
    OnlineHandoverModel,
    DEFAULT_TEST_FEATURES,
)

MODEL_CLASSES = {
    "lightgbm": LightGBMSelector,
    "lstm": LSTMSelector,
    "ensemble": EnsembleSelector,
    "online": OnlineHandoverModel,
}

# Maximum number of feedback samples to keep in memory for possible
# drift-triggered retraining.  When the buffer exceeds this size the
# oldest entries will be discarded.
FEEDBACK_BUFFER_LIMIT = 1000

from ..utils.synthetic_data import generate_synthetic_training_data
from ..utils.tuning import tune_and_train
from ..utils.env_utils import get_neighbor_count_from_env


def _load_metadata(path: str) -> dict:
    """Return metadata stored alongside the model if available."""
    meta_path = path + ".meta.json"
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception as exc:  # noqa: BLE001 - log failure
            logging.getLogger(__name__).warning(
                "Failed to load metadata from %s: %s", meta_path, exc
            )
    return {}


class ModelManager:
    """Thread-safe manager for a singleton ML model instance."""

    _model_instance = None
    _lock = threading.Lock()
    # Bounded buffer holding recent feedback samples for potential retraining
    _feedback_data: deque[dict] = deque(maxlen=FEEDBACK_BUFFER_LIMIT)

    @classmethod
    def get_instance(
        cls,
        model_path: str | None = None,
        neighbor_count: int | None = None,
        model_type: str | None = None,
    ):
        """Return the singleton model instance, creating it if needed."""
        with cls._lock:
            if model_path is None:
                model_path = os.environ.get("MODEL_PATH")
            if model_type is None:
                model_type = os.environ.get("MODEL_TYPE", "lightgbm").lower()

            if model_path:
                meta = _load_metadata(model_path)
                meta_type = meta.get("model_type")
                if meta_type:
                    model_type = meta_type

            if cls._model_instance is None:
                model_cls = MODEL_CLASSES.get(model_type, LightGBMSelector)
                if neighbor_count is None:
                    cls._model_instance = model_cls(model_path=model_path)
                else:
                    cls._model_instance = model_cls(
                        model_path=model_path,
                        neighbor_count=neighbor_count,
                    )

            return cls._model_instance

    @classmethod
    def initialize(
        cls,
        model_path: str | None = None,
        neighbor_count: int | None = None,
        model_type: str | None = None,
    ):
        """Initialize the ML model with synthetic data if needed."""
        logger = logging.getLogger(__name__)

        if neighbor_count is None:
            neighbor_count = get_neighbor_count_from_env(logger=logger)

        if model_type is None:
            model_type = os.environ.get("MODEL_TYPE", "lightgbm").lower()

        meta = _load_metadata(model_path) if model_path else {}
        meta_type = meta.get("model_type")
        if meta_type and meta_type != model_type:
            logger.error(
                "Model type mismatch: metadata has %s but %s was requested",
                meta_type,
                model_type,
            )
            raise ModelError("Model type mismatch")
        if meta_type:
            model_type = meta_type
        meta_version = meta.get("version")
        if meta_version and meta_version != MODEL_VERSION:
            logger.warning(
                "Model version %s differs from expected %s",
                meta_version,
                MODEL_VERSION,
            )

        model_cls = MODEL_CLASSES.get(model_type, LightGBMSelector)
        if neighbor_count is None:
            model = model_cls(model_path=model_path)
        else:
            model = model_cls(model_path=model_path, neighbor_count=neighbor_count)

        # Determine if the model is already trained
        loaded = False
        if model_path and os.path.exists(model_path):
            loaded = model.load(model_path)
        if loaded:
            logger.info("Model is already trained and ready")
            with cls._lock:
                cls._model_instance = model
            return model

        # Model needs training
        logger.info("Model needs training")

        # Generate synthetic data and train
        logger.info("Generating synthetic training data...")
        training_data = generate_synthetic_training_data(500)

        if model_type == "lightgbm" and os.getenv("LIGHTGBM_TUNE") == "1":
            n_iter = int(os.getenv("LIGHTGBM_TUNE_N_ITER", "10"))
            cv = int(os.getenv("LIGHTGBM_TUNE_CV", "3"))
            logger.info(
                "Tuning LightGBM hyperparameters with n_iter=%s, cv=%s...",
                n_iter,
                cv,
            )
            metrics = tune_and_train(model, training_data, n_iter=n_iter, cv=cv)
        else:
            logger.info("Training model with synthetic data...")
            metrics = model.train(training_data)

        logger.info(
            f"Model trained successfully with {metrics.get('samples')} samples"
        )

        # Save the model and metadata
        if model_path:
            model.save(model_path)
            logger.info(f"Model saved to {model_path}")
            meta_path = model_path + ".meta.json"
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "model_type": model_type,
                        "metrics": metrics,
                        "version": MODEL_VERSION,
                    },
                    f,
                )
            logger.info(f"Metadata saved to {meta_path}")

        with cls._lock:
            cls._model_instance = model
        return model

    @classmethod
    def feed_feedback(cls, sample: dict, *, success: bool = True) -> bool:
        """Feed a single feedback sample to the model.

        Parameters
        ----------
        sample:
            Training-like sample containing ``optimal_antenna``.
        success:
            Whether the handover succeeded. Used for drift detection.

        Returns
        -------
        bool
            ``True`` if the model was retrained due to drift.
        """

        model = cls.get_instance()
        retrained = False
        with cls._lock:
            if hasattr(model, "update"):
                model.update(sample, success=success)
            cls._feedback_data.append(sample | {"success": success})
            if hasattr(model, "drift_detected") and model.drift_detected():
                logging.getLogger(__name__).info("Drift detected; retraining model")
                try:
                    model.retrain(cls._feedback_data)
                    cls._feedback_data.clear()
                    if hasattr(model, "save"):
                        model.save()
                    retrained = True
                except Exception:  # noqa: BLE001 - log failure
                    logging.getLogger(__name__).exception("Retraining failed")
        return retrained


