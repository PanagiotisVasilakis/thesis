"""Antenna selector model for 5G network optimization."""
import numpy as np
from sklearn.ensemble import RandomForestClassifier
import joblib
import os
import logging

DEFAULT_TEST_FEATURES = {
    "latitude": 500,
    "longitude": 500,
    "speed": 1.0,
    "direction_x": 0.7,
    "direction_y": 0.7,
    "rsrp_current": -90,
    "sinr_current": 10,
    "best_rsrp_diff": 0.0,
    "best_sinr_diff": 0.0,
}

class AntennaSelector:
    """ML model for selecting optimal antenna based on UE data."""

    def __init__(self, model_path=None):
        """Initialize the model."""
        self.model_path = model_path
        self.model = None
        # Base features independent of neighbour count
        self.base_feature_names = [
            'latitude', 'longitude', 'speed',
            'direction_x', 'direction_y',
            'rsrp_current', 'sinr_current',
            'best_rsrp_diff', 'best_sinr_diff'
        ]
        self.neighbor_count = 0
        self.feature_names = list(self.base_feature_names)
        
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
    
    def extract_features(self, data, include_neighbors=True):
        """Extract features from UE data.

        Parameters
        ----------
        data : dict
            UE data including position, direction and rf_metrics.
        include_neighbors : bool, optional
            When True, include RSRP/SINR of neighbouring antennas sorted by
            signal strength. The number of neighbours is determined from the
            first call and kept constant afterwards.
        """
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

        best_rsrp = features['rsrp_current']
        best_sinr = features['sinr_current']

        # Neighbor metrics ordered by signal strength
        neighbors = []
        if include_neighbors and rf_metrics:
            neighbors = [
                (aid, vals.get('rsrp', -120), vals.get('sinr', 0))
                for aid, vals in rf_metrics.items()
                if aid != current_antenna
            ]
            neighbors.sort(key=lambda x: x[1], reverse=True)

            if neighbors:
                best_rsrp = neighbors[0][1]
                best_sinr = neighbors[0][2]

            if self.neighbor_count == 0:
                self.neighbor_count = len(neighbors)
                for idx in range(self.neighbor_count):
                    self.feature_names.extend([
                        f'rsrp_a{idx+1}', f'sinr_a{idx+1}'
                    ])

            for idx in range(self.neighbor_count):
                if idx < len(neighbors):
                    features[f'rsrp_a{idx+1}'] = neighbors[idx][1]
                    features[f'sinr_a{idx+1}'] = neighbors[idx][2]
                else:
                    features[f'rsrp_a{idx+1}'] = -120
                    features[f'sinr_a{idx+1}'] = 0

        # Signal quality improvement compared to current connection
        features['best_rsrp_diff'] = best_rsrp - features['rsrp_current']
        features['best_sinr_diff'] = best_sinr - features['sinr_current']
        
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
            joblib.dump({
                'model': self.model,
                'feature_names': self.feature_names,
                'neighbor_count': self.neighbor_count,
            }, save_path)
            return True
        return False
    
    def load(self, path=None):
        """Load the model from disk."""
        load_path = path or self.model_path
        if load_path and os.path.exists(load_path):
            data = joblib.load(load_path)
            if isinstance(data, dict) and 'model' in data:
                self.model = data['model']
                self.feature_names = data.get('feature_names', self.feature_names)
                self.neighbor_count = data.get('neighbor_count', self.neighbor_count)
            else:
                self.model = data
            return True
        return False
