"""Model initialization utilities."""
import os
import logging
from app.models.antenna_selector import AntennaSelector, DEFAULT_TEST_FEATURES

from app.utils.synthetic_data import generate_synthetic_training_data

def initialize_model(model_path=None):
    """Initialize the ML model with synthetic data if needed."""
    logger = logging.getLogger(__name__)
    
    model = AntennaSelector(model_path=model_path)
    
    # Check if model exists and is trained
    model_file_exists = model_path and os.path.exists(model_path)
    
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
