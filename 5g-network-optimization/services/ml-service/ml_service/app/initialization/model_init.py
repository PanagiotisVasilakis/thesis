"""Model initialization utilities."""
import logging
import os
from ..models import (
    LightGBMSelector,
    DEFAULT_TEST_FEATURES,
)

from ..utils.synthetic_data import generate_synthetic_training_data
from ..utils.tuning import tune_and_train

# Singleton instance for model reuse
_model_instance = None

def get_model(model_path=None, neighbor_count: int | None = None):
    """Return a singleton LightGBM model instance."""
    global _model_instance

    if model_path is None:
        model_path = os.environ.get("MODEL_PATH")

    if _model_instance is None:
        if neighbor_count is None:
            _model_instance = LightGBMSelector(model_path=model_path)
        else:
            _model_instance = LightGBMSelector(
                model_path=model_path,
                neighbor_count=neighbor_count,
            )

    return _model_instance

def initialize_model(model_path=None, neighbor_count: int | None = None):
    """Initialize the LightGBM model with synthetic data if needed."""
    global _model_instance
    logger = logging.getLogger(__name__)

    if neighbor_count is None:
        model = LightGBMSelector(model_path=model_path)
    else:
        model = LightGBMSelector(model_path=model_path, neighbor_count=neighbor_count)
    
    # Try a simple prediction to check if the model is trained
    try:
        model.predict(DEFAULT_TEST_FEATURES)
        logger.info("Model is already trained and ready")
        _model_instance = model
        return model
    except Exception as e:
        # Model needs training
        logger.info(f"Model needs training: {str(e)}")
        
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
        
        logger.info(f"Model trained successfully with {metrics.get('samples')} samples")
        
        # Save the model
        if model_path:
            model.save(model_path)
            logger.info(f"Model saved to {model_path}")

        _model_instance = model
        return model

