"""Antenna selector model for 5G network optimization."""
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
import joblib
import os
import logging

class AntennaSelector:
    """ML model for selecting optimal antenna based on UE data."""
    
    def __init__(self, model_path=None):
        """Initialize the model."""
        self.model_path = model_path
        self.model = None
        self.feature_names = [
            'latitude', 'longitude', 'speed',
            'direction_x', 'direction_y',
            'rsrp_current', 'sinr_current'
        ]
        
        # Try to load existing model
        try:
            if model_path and os.path.exists(model_path):
                self.load(model_path)
            else:
                self._initialize_model()
        except Exception as e:
            logging.warning(f"Could not load model: {e}")
            self._initialize_model()
    
    def _initialize_model(self):
        """Initialize a new model."""
        self.model = RandomForestClassifier(
            n_estimators=100,
            max_depth=10,
            random_state=42
        )
    
    def extract_features(self, data):
        """Extract features from UE data."""
        features = {}
        
        # Location features
        features['latitude'] = data.get('latitude', 0)
        features['longitude'] = data.get('longitude', 0)
        
        # Movement features
        features['speed'] = data.get('speed', 0)
        direction = data.get('direction', (0, 0, 0))
        # Convert direction to 2D unit vector components
        if isinstance(direction, (list, tuple)) and len(direction) >= 2:
            # Normalize if needed
            magnitude = (direction[0]**2 + direction[1]**2)**0.5
            if magnitude > 0:
                features['direction_x'] = direction[0] / magnitude
                features['direction_y'] = direction[1] / magnitude
            else:
                features['direction_x'] = 0
                features['direction_y'] = 0
        else:
            features['direction_x'] = 0
            features['direction_y'] = 0
        
        # Signal features
        rf_metrics = data.get('rf_metrics', {})
        current_antenna = data.get('connected_to')
        if current_antenna and current_antenna in rf_metrics:
            features['rsrp_current'] = rf_metrics[current_antenna].get('rsrp', -120)
            features['sinr_current'] = rf_metrics[current_antenna].get('sinr', 0)
        else:
            features['rsrp_current'] = -120  # Default poor signal
            features['sinr_current'] = 0     # Default neutral SINR
        
        return features
    
    def predict(self, features):
        """Predict the optimal antenna for the UE."""
        # If model is not trained, return dummy prediction
        if not hasattr(self.model, 'predict_proba'):
            return {
                'antenna_id': 'antenna_1',  # Default antenna
                'confidence': 0.5           # Neutral confidence
            }
        
        # Convert features to the format expected by the model
        X = np.array([[features[name] for name in self.feature_names]])
        
        # Get prediction and probability
        antenna_id = self.model.predict(X)[0]
        probabilities = self.model.predict_proba(X)[0]
        confidence = max(probabilities)
        
        return {
            'antenna_id': antenna_id,
            'confidence': float(confidence)
        }
    
    def train(self, training_data):
        """Train the model with provided data."""
        # Extract features and labels from training data
        X = []
        y = []
        
        for sample in training_data:
            features = self.extract_features(sample)
            feature_vector = [features[name] for name in self.feature_names]
            
            # The label is the optimal antenna ID
            label = sample.get('optimal_antenna')
            
            X.append(feature_vector)
            y.append(label)
        
        # Convert to numpy arrays
        X = np.array(X)
        y = np.array(y)
        
        # Train the model
        self.model.fit(X, y)
        
        # Return training metrics
        return {
            'samples': len(X),
            'classes': len(set(y)),
            'feature_importance': dict(zip(
                self.feature_names,
                self.model.feature_importances_
            ))
        }
    
    def save(self, path=None):
        """Save the model to disk."""
        save_path = path or self.model_path
        if save_path:
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            joblib.dump(self.model, save_path)
            return True
        return False
    
    def load(self, path=None):
        """Load the model from disk."""
        load_path = path or self.model_path
        if load_path and os.path.exists(load_path):
            self.model = joblib.load(load_path)
            return True
        return False
