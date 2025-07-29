"""Model initialization utilities."""
import logging
import os
import threading
from ..models import (
    LightGBMSelector,
    DEFAULT_TEST_FEATURES,
)

from ..utils.synthetic_data import generate_synthetic_training_data
from ..utils.tuning import tune_and_train


class ModelManager:
    """Thread-safe manager for a singleton ML model instance."""

    _model_instance = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(
        cls, model_path: str | None = None, neighbor_count: int | None = None
    ):
        """Return the singleton model instance, creating it if needed."""
        with cls._lock:
            if model_path is None:
                model_path = os.environ.get("MODEL_PATH")

            if cls._model_instance is None:
                if neighbor_count is None:
                    cls._model_instance = LightGBMSelector(model_path=model_path)
                else:
                    cls._model_instance = LightGBMSelector(
                        model_path=model_path,
                        neighbor_count=neighbor_count,
                    )

            return cls._model_instance

    @classmethod
    def initialize(
        cls, model_path: str | None = None, neighbor_count: int | None = None
    ):
        """Initialize the LightGBM model with synthetic data if needed."""
        logger = logging.getLogger(__name__)

        if neighbor_count is None:
            model = LightGBMSelector(model_path=model_path)
        else:
            model = LightGBMSelector(model_path=model_path, neighbor_count=neighbor_count)

        # Determine if the model is already trained
        if hasattr(model.model, "booster_") or (model_path and os.path.exists(model_path)):
            logger.info("Model is already trained and ready")
            with cls._lock:
                cls._model_instance = model
            return model

        # Model needs training
        logger.info("Model needs training")

        # Generate synthetic data and train
        logger.info("Generating synthetic training data...")
        training_data = generate_synthetic_training_data(500)

        if os.getenv("LIGHTGBM_TUNE") == "1":
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

        # Save the model
        if model_path:
            model.save(model_path)
            logger.info(f"Model saved to {model_path}")

        with cls._lock:
            cls._model_instance = model
        return model


