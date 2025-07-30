"""Model initialization utilities."""
import logging
import os
import json
import threading
from ..models import (
    LightGBMSelector,
    LSTMSelector,
    EnsembleSelector,
    DEFAULT_TEST_FEATURES,
)

MODEL_CLASSES = {
    "lightgbm": LightGBMSelector,
    "lstm": LSTMSelector,
    "ensemble": EnsembleSelector,
}

from ..utils.synthetic_data import generate_synthetic_training_data
from ..utils.tuning import tune_and_train
from ..utils.env_utils import get_neighbor_count_from_env


class ModelManager:
    """Thread-safe manager for a singleton ML model instance."""

    _model_instance = None
    _lock = threading.Lock()

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
                json.dump({"model_type": model_type, "metrics": metrics}, f)
            logger.info(f"Metadata saved to {meta_path}")

        with cls._lock:
            cls._model_instance = model
        return model


