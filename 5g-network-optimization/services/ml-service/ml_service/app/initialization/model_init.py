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

def get_model(model_path=None):
    """Return a singleton LightGBM model instance."""
    global _model_instance

    if _model_instance is None:
        _model_instance = LightGBMSelector(model_path=model_path)

    return _model_instance

def initialize_model(model_path=None):
    """Initialize the LightGBM model with synthetic data if needed."""
    logger = logging.getLogger(__name__)

    model = LightGBMSelector(model_path=model_path)
    
    # Try a simple prediction to check if the model is trained
    try:
        model.predict(DEFAULT_TEST_FEATURES)
        logger.info("Model is already trained and ready")
        return model
    except Exception as e:
        # Model needs training
        logger.info(f"Model needs training: {str(e)}")
        
        # Generate synthetic data and train
        logger.info("Generating synthetic training data...")
        training_data = generate_synthetic_training_data(500)
        
        if os.getenv("LIGHTGBM_TUNE") == "1":
            logger.info("Tuning LightGBM hyperparameters...")
            metrics = tune_and_train(model, training_data, n_iter=10)
        else:
            logger.info("Training model with synthetic data...")
            metrics = model.train(training_data)
        
        logger.info(f"Model trained successfully with {metrics.get('samples')} samples")
        
        # Save the model
        if model_path:
            model.save(model_path)
            logger.info(f"Model saved to {model_path}")
        
        return model

