"""Model initialization utilities."""
import os
import logging
from ..models import (
    AntennaSelector,
    LightGBMSelector,
    DEFAULT_TEST_FEATURES,
)

from ..utils.synthetic_data import generate_synthetic_training_data

# Singleton instance for model reuse
_model_instance = None

# Supported model classes mapped by type name
MODEL_TYPES = {
    "random_forest": AntennaSelector,
    "lightgbm": LightGBMSelector,
}

def get_model(model_path=None, model_type=None):
    """Return a singleton model instance of the requested type.

    ``model_type`` can be ``"random_forest"`` or ``"lightgbm"`` and defaults to
    the ``MODEL_TYPE`` environment variable. Subsequent calls return the same
    instance unless the requested type differs from the cached one.
    """
    global _model_instance

    model_type = model_type or os.environ.get("MODEL_TYPE", "random_forest")
    model_class = MODEL_TYPES.get(model_type, AntennaSelector)

    if _model_instance is None or not isinstance(_model_instance, model_class):
        _model_instance = model_class(model_path=model_path)

    return _model_instance

def initialize_model(model_path=None, model_type=None):
    """Initialize the ML model with synthetic data if needed."""
    logger = logging.getLogger(__name__)

    model_type = model_type or os.environ.get("MODEL_TYPE", "random_forest")
    model_class = MODEL_TYPES.get(model_type, AntennaSelector)

    model = model_class(model_path=model_path)
    
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
        
        logger.info("Training model with synthetic data...")
        metrics = model.train(training_data)
        
        logger.info(f"Model trained successfully with {metrics.get('samples')} samples")
        
        # Save the model
        if model_path:
            model.save(model_path)
            logger.info(f"Model saved to {model_path}")
        
        return model

