"""Test the AntennaSelector model."""
import numpy as np
import matplotlib.pyplot as plt
from sklearn.model_selection import train_test_split

import importlib.util
from pathlib import Path

ANT_PATH = Path(__file__).resolve().parents[1] / "app" / "models" / "antenna_selector.py"
spec = importlib.util.spec_from_file_location("antenna_selector", ANT_PATH)
antenna_selector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(antenna_selector)
AntennaSelector = antenna_selector.AntennaSelector

def generate_synthetic_data(num_samples=500):
    """Generate synthetic data for testing."""
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

def test_model_training_and_prediction():
    """Test training the model with synthetic data and making predictions."""
    # Generate synthetic data
    data = generate_synthetic_data(1000)
    print(f"Generated {len(data)} synthetic data points")
    
    # Split into training and test sets
    train_data, test_data = train_test_split(data, test_size=0.2, random_state=42)
    
    # Create and train model
    model = AntennaSelector()
    metrics = model.train(train_data)
    
    print(f"Trained model with {metrics['samples']} samples")
    print(f"Found {metrics['classes']} antenna classes")
    
    # Test prediction
    correct = 0
    for sample in test_data:
        features = model.extract_features(sample)
        prediction = model.predict(features)
        
        if prediction['antenna_id'] == sample['optimal_antenna']:
            correct += 1
    
    accuracy = correct / len(test_data)
    print(f"Model accuracy: {accuracy:.2%}")
    
    # Visualize feature importance
    feature_importance = metrics.get('feature_importance', {})
    if feature_importance:
        features = list(feature_importance.keys())
        importance = list(feature_importance.values())
        
        plt.figure(figsize=(10, 6))
        plt.barh(features, importance)
        plt.xlabel('Importance')
        plt.title('Feature Importance')
        plt.tight_layout()
        
        # Create directory if it doesn't exist
        os.makedirs('output', exist_ok=True)
        plt.savefig('output/feature_importance.png')
        print("Feature importance visualization saved to output/feature_importance.png")
    
    return accuracy > 0.7  # Expect at least 70% accuracy

if __name__ == "__main__":
    success = test_model_training_and_prediction()
    if success:
        print("✅ Model test passed!")
    else:
        print("❌ Model test failed!")
