"""Model initialization utilities."""
import os
import numpy as np
import logging
from app.models.antenna_selector import AntennaSelector

def generate_synthetic_training_data(num_samples=500):
    """Generate synthetic training data."""
    np.random.seed(42)
    
    # Define three antennas in a triangle formation
    antennas = {
        'antenna_1': (0, 0),
        'antenna_2': (1000, 0),
        'antenna_3': (500, 866)
    }
    
    data = []
    
    for i in range(num_samples):
        # Random position
        x = np.random.uniform(0, 1000)
        y = np.random.uniform(0, 866)
        
        # Random speed and direction
        speed = np.random.uniform(0, 10)
        angle = np.random.uniform(0, 2*np.pi)
        direction = [np.cos(angle), np.sin(angle), 0]
        
        # Find closest antenna (simplistic approach)
        distances = {}
        for antenna_id, pos in antennas.items():
            dist = np.sqrt((x - pos[0])**2 + (y - pos[1])**2)
            distances[antenna_id] = dist
        
        closest_antenna = min(distances, key=distances.get)
        
        # Generate RF metrics based on distance
        rf_metrics = {}
        for antenna_id, dist in distances.items():
            # Simple path loss model
            rsrp = -60 - 20 * np.log10(max(1, dist/10))
            sinr = 20 * (1 - dist/1500) + np.random.normal(0, 2)
            rf_metrics[antenna_id] = {'rsrp': rsrp, 'sinr': sinr}
        
        # Create sample
        sample = {
            'ue_id': f'synthetic_ue_{i}',
            'latitude': x,
            'longitude': y,
            'speed': speed,
            'direction': direction,
            'connected_to': closest_antenna,
            'rf_metrics': rf_metrics,
            'optimal_antenna': closest_antenna
        }
        
        data.append(sample)
    
    return data

def initialize_model(model_path=None):
    """Initialize the ML model with synthetic data if needed."""
    logger = logging.getLogger(__name__)
    
    model = AntennaSelector(model_path=model_path)
    
    # Check if model exists and is trained
    model_file_exists = model_path and os.path.exists(model_path)
    
    # Try a simple prediction to check if the model is trained
    try:
        test_features = {
            'latitude': 500,
            'longitude': 500,
            'speed': 1.0,
            'direction_x': 0.7,
            'direction_y': 0.7,
            'rsrp_current': -90,
            'sinr_current': 10
        }
        model.predict(test_features)
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
