"""Model initialization utilities."""
import json
import logging
import os
import threading
from collections import deque
from datetime import datetime, timezone
from packaging.version import Version, InvalidVersion

# Semantic version of the expected model format. Bump whenever the
# persisted model or metadata structure changes in a backwards incompatible
# way so older files can be detected gracefully.
MODEL_VERSION = "1.0.0"
from ..errors import ModelError
from ..models import (EnsembleSelector, LightGBMSelector, LSTMSelector,
                      OnlineHandoverModel)

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

from ..utils.env_utils import get_neighbor_count_from_env
from ..utils.synthetic_data import generate_synthetic_training_data
from ..utils.tuning import tune_and_train


def _load_metadata(path: str) -> dict:
    """Return metadata stored alongside the model if available."""
    meta_path = path + ".meta.json"
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    ts = data.get("trained_at")
                    if ts is not None:
                        try:
                            data["trained_at"] = datetime.fromisoformat(ts)
                        except ValueError:
                            logging.getLogger(__name__).warning(
                                "Invalid trained_at timestamp %s in %s", ts, meta_path
                            )
                            data["trained_at"] = None
                    return data
        except Exception as exc:  # noqa: BLE001 - log failure
            logging.getLogger(__name__).warning(
                "Failed to load metadata from %s: %s", meta_path, exc
            )
    return {}


def _parse_version_from_path(path: str) -> str | None:
    """Extract semantic version from the model filename if present."""
    base = os.path.basename(path)
    if "_v" in base:
        ver = base.rsplit("_v", 1)[-1].split(".joblib", 1)[0]
        if ver:
            return ver
    return None


class ModelManager:
    """Thread-safe manager for a singleton ML model instance."""

    _model_instance = None
    _lock = threading.Lock()
    # Bounded buffer holding recent feedback samples for potential retraining
    _feedback_data: deque[dict] = deque(maxlen=FEEDBACK_BUFFER_LIMIT)
    # Path of the last successfully initialized model
    _last_good_model_path: str | None = None
    # Mapping of discovered model paths keyed by semantic version
    _model_paths: dict[str, str] = {}
    # Signal set when initialization completes
    _init_event = threading.Event()
    # Background initialization thread
    _init_thread: threading.Thread | None = None

    @classmethod
    def _initialize_sync(
        cls,
        model_path: str | None,
        neighbor_count: int | None,
        model_type: str | None,
        previous_model=None,
        previous_path: str | None = None,
    ):
        """Internal helper performing synchronous initialization."""
        logger = logging.getLogger(__name__)
        try:
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
            if meta_version:
                try:
                    if Version(str(meta_version)) != Version(MODEL_VERSION):
                        logger.warning(
                            "Model version %s differs from expected %s",
                            meta_version,
                            MODEL_VERSION,
                        )
                except InvalidVersion:
                    logger.warning("Invalid model version %s in metadata", meta_version)

            model_cls = MODEL_CLASSES.get(model_type, LightGBMSelector)
            if neighbor_count is None:
                model = model_cls(model_path=model_path)
            else:
                model = model_cls(
                    model_path=model_path, neighbor_count=neighbor_count
                )

            loaded = False
            if model_path and os.path.exists(model_path):
                loaded = model.load(model_path)
            if loaded:
                logger.info("Model is already trained and ready")
                with cls._lock:
                    cls._model_instance = model
                    cls._last_good_model_path = model_path
                    ver = _parse_version_from_path(model_path)
                    if ver:
                        cls._model_paths[ver] = model_path
                    cls._init_event.set()
                return model

            logger.info("Model needs training")

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
                metrics = tune_and_train(
                    model, training_data, n_iter=n_iter, cv=cv
                )
            else:
                logger.info("Training model with synthetic data...")
                metrics = model.train(training_data)

            logger.info(
                f"Model trained successfully with {metrics.get('samples')} samples"
            )

            if model_path:
                model.save(model_path)
                logger.info(f"Model saved to {model_path}")
                meta_path = model_path + ".meta.json"
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(
                        {
                            "model_type": model_type,
                            "metrics": metrics,
                            "trained_at": datetime.now(timezone.utc).isoformat(),
                            "version": MODEL_VERSION,
                        },
                        f,
                    )
                logger.info(f"Metadata saved to {meta_path}")

            with cls._lock:
                cls._model_instance = model
                cls._last_good_model_path = model_path
                ver = _parse_version_from_path(model_path) if model_path else None
                if ver:
                    cls._model_paths[ver] = model_path
                cls._init_event.set()
            return model
        except Exception:  # noqa: BLE001
            logger.exception("Model initialization failed")
            with cls._lock:
                cls._model_instance = previous_model
                cls._last_good_model_path = previous_path
                cls._init_event.set()
            raise

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
        *,
        background: bool = True,
    ):
        """Initialize the ML model.

        If ``background`` is ``True`` (default), the heavy initialization work is
        executed in a background thread and a lightweight placeholder model is
        returned immediately. When ``background`` is ``False`` the initialization
        runs synchronously and the fully initialized model is returned.
        """

        logger = logging.getLogger(__name__)

        # Preserve the current model state in case initialization fails
        with cls._lock:
            previous_model = cls._model_instance
            previous_path = cls._last_good_model_path

        if neighbor_count is None:
            neighbor_count = get_neighbor_count_from_env(logger=logger)

        if background:
            with cls._lock:
                if cls._init_thread and cls._init_thread.is_alive():
                    return cls._model_instance

                cls._init_event.clear()

                placeholder_cls = MODEL_CLASSES.get(
                    model_type or os.environ.get("MODEL_TYPE", "lightgbm").lower(),
                    LightGBMSelector,
                )

                if neighbor_count is None:
                    neighbor_count = get_neighbor_count_from_env(
                        logger=logging.getLogger(__name__)
                    )

                cls._model_instance = placeholder_cls(neighbor_count=neighbor_count)

                cls._init_thread = threading.Thread(
                    target=cls._initialize_sync,
                    args=(model_path, neighbor_count, model_type, previous_model, previous_path),
                    daemon=True,
                )
                cls._init_thread.start()
                return cls._model_instance

        return cls._initialize_sync(model_path, neighbor_count, model_type, previous_model, previous_path)

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

    @classmethod
    def switch_version(cls, version: str):
        """Load a previously registered model version.

        If loading fails the current model remains active.
        """
        with cls._lock:
            path = cls._model_paths.get(version)
            if not path:
                raise ValueError(f"Unknown model version {version}")
            previous_model = cls._model_instance
            previous_path = cls._last_good_model_path

        try:
            return cls._initialize_sync(path, None, None, previous_model, previous_path)
        except Exception:
            # _initialize_sync already restored the previous model
            logging.getLogger(__name__).warning(
                "Failed to switch to version %s, using last good model", version
            )
            return cls.get_instance()

    @classmethod
    def wait_until_ready(cls, timeout: float | None = None) -> bool:
        """Block until model initialization completes.

        Parameters
        ----------
        timeout:
            Optional timeout in seconds.

        Returns
        -------
        bool
            ``True`` if the model became ready before the timeout.
        """

        return cls._init_event.wait(timeout)

    @classmethod
    def is_ready(cls) -> bool:
        """Return ``True`` if initialization has finished."""

        return cls._init_event.is_set()

    @classmethod
    def get_metadata(cls) -> dict:
        """Return metadata for the active model if available."""

        with cls._lock:
            path = cls._last_good_model_path or os.environ.get("MODEL_PATH")
        if not path:
            return {}
        meta = _load_metadata(path)
        ts = meta.get("trained_at")
        if isinstance(ts, datetime):
            meta["trained_at"] = ts.isoformat()
        return meta
