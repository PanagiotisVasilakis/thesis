"""Model initialization utilities."""
import hashlib
import json
import logging
import os
import threading
from collections import deque
from datetime import datetime
from pathlib import Path
from packaging.version import Version, InvalidVersion

from .thread_monitor import (
    get_thread_monitor, 
    safe_thread_execution, 
    ThreadFailureLevel,
)
from .model_version import MODEL_VERSION
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

FINAL_METADATA_REQUIRED_FIELDS = {
    "model_type",
    "trained_at",
    "version",
    "training_data_source",
    "scenario_seeds",
    "dataset_size",
    "selected_features",
    "validation_metrics",
    "calibration_state",
    "git_commit",
    "feature_config_sha256",
}

from ..utils.env_utils import get_neighbor_count_from_env
from ..utils.synthetic_data import generate_synthetic_training_data
from ..utils.tuning import tune_and_train


def _truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _pretrained_model_required() -> bool:
    """Return True when synthetic startup training is forbidden."""
    return (
        _truthy_env("THESIS_FINAL_RUN")
        or _truthy_env("REQUIRE_PRETRAINED_MODEL")
        or _truthy_env("DISABLE_SYNTHETIC_MODEL_BOOTSTRAP")
    )


def _sha256_file(path: str | Path) -> str | None:
    candidate = Path(path)
    if not candidate.is_file():
        return None
    digest = hashlib.sha256()
    with candidate.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _default_feature_config_path() -> Path:
    return Path(__file__).resolve().parents[1] / "config" / "features.yaml"


def _feature_config_path() -> Path:
    return Path(os.environ.get("FEATURE_CONFIG_PATH", str(_default_feature_config_path())))


def _validate_pretrained_artifact(model_path: str | None) -> None:
    """Fail fast when final thesis mode lacks a complete model artifact."""
    if not model_path:
        raise ModelError(
            "Final thesis mode requires MODEL_PATH to point to a pretrained model artifact"
        )

    path = Path(model_path)
    meta_path = Path(f"{model_path}.meta.json")
    scaler_path = Path(f"{model_path}.scaler")
    feature_config = _feature_config_path()
    missing = [
        str(candidate)
        for candidate in (path, meta_path, scaler_path, feature_config)
        if not candidate.is_file()
    ]
    if missing:
        raise ModelError(
            "Final thesis mode requires existing model artifact files: "
            + ", ".join(missing)
        )

    metadata = _load_metadata(model_path)
    missing_metadata = sorted(
        field
        for field in FINAL_METADATA_REQUIRED_FIELDS
        if not metadata.get(field)
    )
    if missing_metadata:
        raise ModelError(
            "Final thesis model metadata missing required field(s): "
            + ", ".join(missing_metadata)
        )

    feature_config_sha256 = _sha256_file(feature_config)
    if metadata.get("feature_config_sha256") != feature_config_sha256:
        raise ModelError(
            "Final thesis model metadata feature_config_sha256 does not match "
            "FEATURE_CONFIG_PATH"
        )


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
        except (json.JSONDecodeError, ValueError) as exc:
            # Handle JSON parsing and value conversion errors
            logging.getLogger(__name__).warning(
                "Failed to parse metadata from %s: %s", meta_path, exc
            )
        except (IOError, OSError) as exc:
            # Handle file system errors
            logging.getLogger(__name__).warning(
                "Failed to read metadata file %s: %s", meta_path, exc
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
    def discover_versions(cls, base_path: str) -> None:
        """Discover available model versions under ``base_path``.

        Any files matching ``antenna_selector_v*.joblib`` are registered so that
        :meth:`switch_version` can load them later.
        """
        if not os.path.isdir(base_path):
            return

        with cls._lock:
            cls._model_paths.clear()
            for name in os.listdir(base_path):
                if not name.endswith(".joblib"):
                    continue
                path = os.path.join(base_path, name)
                if ver := _parse_version_from_path(path):
                    cls._model_paths[ver] = path

    @classmethod
    def list_versions(cls) -> list[str]:
        """Return all discovered model versions."""
        with cls._lock:
            return sorted(cls._model_paths.keys())

    @classmethod
    def _restore_previous_state(
        cls,
        previous_model,
        previous_path: str | None,
    ) -> None:
        cls._model_instance = previous_model
        cls._last_good_model_path = previous_path
        if previous_model is None:
            cls._init_event.clear()
        else:
            cls._init_event.set()

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

            require_pretrained = _pretrained_model_required()
            if require_pretrained:
                _validate_pretrained_artifact(model_path)

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

            if require_pretrained:
                raise ModelError(
                    "Final thesis mode requires loading an existing pretrained "
                    f"model artifact; refusing synthetic bootstrap for {model_path}"
                )

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
                "Model trained successfully with %s samples",
                metrics.get('samples')
            )

            if model_path:
                model.save(
                    model_path,
                    model_type=model_type,
                    metrics=metrics,
                    version=MODEL_VERSION,
                )
                logger.info("Model saved to %s", model_path)

            with cls._lock:
                cls._model_instance = model
                cls._last_good_model_path = model_path
                ver = _parse_version_from_path(model_path) if model_path else None
                if ver:
                    cls._model_paths[ver] = model_path
                cls._init_event.set()
            return model
        except (OSError, IOError) as e:
            logger.error("File system error during model initialization: %s", e)
            with cls._lock:
                cls._restore_previous_state(previous_model, previous_path)
            # Report as critical since model initialization is essential
            get_thread_monitor().report_failure(
                "model_initialization",
                e,
                ThreadFailureLevel.CRITICAL,
                {"model_path": model_path, "model_type": model_type}
            )
            raise
        except (ValueError, TypeError) as e:
            logger.error("Configuration error during model initialization: %s", e)
            with cls._lock:
                cls._restore_previous_state(previous_model, previous_path)
            get_thread_monitor().report_failure(
                "model_initialization",
                e,
                ThreadFailureLevel.ERROR,
                {"model_path": model_path, "model_type": model_type}
            )
            raise
        except ImportError as e:
            logger.error("Missing dependency for model initialization: %s", e)
            with cls._lock:
                cls._restore_previous_state(previous_model, previous_path)
            get_thread_monitor().report_failure(
                "model_initialization",
                e,
                ThreadFailureLevel.CRITICAL,
                {"model_path": model_path, "model_type": model_type}
            )
            raise
        except Exception as e:
            logger.critical("Unexpected error during model initialization: %s", e)
            with cls._lock:
                cls._restore_previous_state(previous_model, previous_path)
            get_thread_monitor().report_failure(
                "model_initialization",
                e,
                ThreadFailureLevel.CRITICAL,
                {"model_path": model_path, "model_type": model_type, "unexpected": True}
            )
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

        # Discover any existing model versions before loading
        if model_path:
            cls.discover_versions(os.path.dirname(model_path))
        elif os.environ.get("MODEL_PATH"):
            cls.discover_versions(os.path.dirname(os.environ["MODEL_PATH"]))

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

                # Use safe thread execution with monitoring
                cls._init_thread = safe_thread_execution(
                    target_func=cls._initialize_sync,
                    thread_name="model_background_init",
                    args=(model_path, neighbor_count, model_type, previous_model, previous_path),
                    failure_level=ThreadFailureLevel.CRITICAL,
                    context={
                        "model_path": model_path,
                        "model_type": model_type,
                        "neighbor_count": neighbor_count
                    },
                    max_retries=1  # One retry for critical model initialization
                )
                cls._init_thread.start()
                
                # Start thread monitoring if not already running
                get_thread_monitor().start_monitoring()
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
                    metrics = model.retrain(cls._feedback_data)
                    cls._feedback_data.clear()
                    cls.save_active_model(metrics)
                    retrained = True
                except (ValueError, TypeError) as e:
                    logging.getLogger(__name__).error("Model retraining failed due to data issues: %s", e)
                    get_thread_monitor().report_failure(
                        "model_retraining",
                        e,
                        ThreadFailureLevel.ERROR,
                        {"feedback_samples": len(cls._feedback_data)}
                    )
                except (MemoryError, OSError) as e:
                    logging.getLogger(__name__).error("Model retraining failed due to resource issues: %s", e)
                    get_thread_monitor().report_failure(
                        "model_retraining",
                        e,
                        ThreadFailureLevel.CRITICAL,
                        {"feedback_samples": len(cls._feedback_data)}
                    )
                except Exception as e:
                    logging.getLogger(__name__).critical("Unexpected model retraining failure: %s", e)
                    get_thread_monitor().report_failure(
                        "model_retraining",
                        e,
                        ThreadFailureLevel.CRITICAL,
                        {"feedback_samples": len(cls._feedback_data), "unexpected": True}
                    )
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
        if cls._init_event.wait(timeout):
            return True

        logger = logging.getLogger(__name__)

        with cls._lock:
            thread = cls._init_thread

        if thread and thread.is_alive():
            thread.join(timeout)
            return cls._init_event.is_set()

        with cls._lock:
            model_path = cls._last_good_model_path or os.environ.get("MODEL_PATH")
            previous_model = cls._model_instance
            previous_path = cls._last_good_model_path
            model_type = os.environ.get("MODEL_TYPE", "lightgbm").lower()

        if not cls._init_event.is_set() and model_path:
            logger.warning(
                "Model initialization thread not active while awaiting readiness; "
                "running synchronous initialization"
            )
            try:
                cls._initialize_sync(
                    model_path,
                    None,
                    model_type,
                    previous_model,
                    previous_path,
                )
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Synchronous model initialization failed during readiness wait: %s",
                    exc,
                )
                return False

        return cls._init_event.is_set()

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
            return {
                "final_mode": _pretrained_model_required(),
                "synthetic_bootstrap_allowed": not _pretrained_model_required(),
                "artifact_complete": False,
            }
        meta = _load_metadata(path)
        ts = meta.get("trained_at")
        if isinstance(ts, datetime):
            meta["trained_at"] = ts.isoformat()
        meta_path = f"{path}.meta.json"
        scaler_path = f"{path}.scaler"
        feature_config = _feature_config_path()
        meta.update(
            {
                "model_path": path,
                "model_sha256": _sha256_file(path),
                "metadata_path": meta_path,
                "metadata_sha256": _sha256_file(meta_path),
                "scaler_path": scaler_path,
                "scaler_sha256": _sha256_file(scaler_path),
                "feature_config_path": str(feature_config),
                "feature_config_sha256": _sha256_file(feature_config),
                "final_mode": _pretrained_model_required(),
                "synthetic_bootstrap_allowed": not _pretrained_model_required(),
            }
        )
        meta["artifact_complete"] = bool(
            meta["model_sha256"]
            and meta["metadata_sha256"]
            and meta["scaler_sha256"]
            and meta["feature_config_sha256"]
        )
        return meta

    @classmethod
    def save_active_model(cls, metrics: dict | None = None) -> bool:
        """Persist the current model alongside updated metadata."""
        with cls._lock:
            model = cls._model_instance
            path = cls._last_good_model_path or os.environ.get("MODEL_PATH")
            model_type = os.environ.get("MODEL_TYPE", "lightgbm").lower()
        if not model or not path or not hasattr(model, "save"):
            return False

        meta = _load_metadata(path)
        if m_type := meta.get("model_type"):
            model_type = m_type

        try:
            model.save(
                path,
                model_type=model_type,
                metrics=metrics,
                version=MODEL_VERSION,
            )
            return True
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).exception("Failed to save model")
            return False
