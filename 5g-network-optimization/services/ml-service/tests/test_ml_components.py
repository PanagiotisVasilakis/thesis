# Save this as tests/test_ml_components.py

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
    
    # Define antennas in a triangle formation
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
        
        # Calculate distance to each antenna
        distances = {}
        for antenna_id, location in antennas.items():
            dist = np.sqrt((x - location[0])**2 + (y - location[1])**2)
            distances[antenna_id] = dist
        
        # Find closest antenna
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

def test_feature_extraction():
    """Test feature extraction from UE data."""
    print("\nTesting feature extraction...")
    
    # Create model
    model = AntennaSelector()
    
    # Sample UE data
    ue_data = {
        'ue_id': 'test_ue_1',
        'latitude': 500.0,
        'longitude': 250.0,
        'speed': 5.0,
        'direction': [0.8, 0.6, 0],
        'connected_to': 'antenna_1',
        'rf_metrics': {
            'antenna_1': {'rsrp': -85, 'sinr': 10},
            'antenna_2': {'rsrp': -95, 'sinr': 5},
            'antenna_3': {'rsrp': -105, 'sinr': 2}
        }
    }
    
    # Extract features
    features = model.extract_features(ue_data)
    
    print("Extracted features:")
    for key, value in features.items():
        print(f"  {key}: {value}")
    
    # Check expected features
    expected_features = [
        'latitude', 'longitude', 'speed', 
        'direction_x', 'direction_y', 
        'rsrp_current', 'sinr_current'
    ]
    
    missing_features = [f for f in expected_features if f not in features]
    if missing_features:
        print(f"❌ Missing expected features: {missing_features}")
        return False
    
    return True

def test_model_training_and_prediction():
    """Test model training and prediction."""
    print("\nTesting model training and prediction...")
    
    # Generate synthetic data
    data = generate_synthetic_data(1000)
    print(f"Generated {len(data)} synthetic data points")
    
    # Split into training and test sets
    train_data, test_data = train_test_split(data, test_size=0.2, random_state=42)
    
    # Create and train model
    model = AntennaSelector()
    print("Training model...")
    metrics = model.train(train_data)
    
    print(f"Trained model with {metrics.get('samples', 0)} samples")
    print(f"Found {metrics.get('classes', 0)} antenna classes")
    
    # Test prediction accuracy
    correct = 0
    predictions = []
    
    print("Testing model on test data...")
    for sample in test_data:
        features = model.extract_features(sample)
        prediction = model.predict(features)
        
        # Store prediction result
        predictions.append((
            sample['ue_id'],
            sample['latitude'],
            sample['longitude'],
            sample['optimal_antenna'],
            prediction['antenna_id'],
            prediction['confidence']
        ))
        
        if prediction['antenna_id'] == sample['optimal_antenna']:
            correct += 1
    
    accuracy = correct / len(test_data)
    print(f"Model accuracy: {accuracy:.2%}")
    
    # Visualize feature importance if available
    feature_importance = metrics.get('feature_importance', {})
    if feature_importance:
        print("\nFeature importance:")
        sorted_features = sorted(
            feature_importance.items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        for feature, importance in sorted_features:
            print(f"  {feature}: {importance:.4f}")
        
        # Plot feature importance
        plt.figure(figsize=(10, 6))
        features = [f[0] for f in sorted_features]
        importances = [f[1] for f in sorted_features]
        
        plt.barh(features, importances)
        plt.xlabel('Importance')
        plt.title('Feature Importance')
        plt.tight_layout()
        
        os.makedirs('output', exist_ok=True)
        plt.savefig('output/feature_importance.png')
        plt.close()
        
        print("Feature importance visualization saved to output/feature_importance.png")
    
    # Visualize predictions in a 2D space
    visualize_predictions(test_data, predictions)
    
    # Save model
    try:
        model.save('test_model.joblib')
        print("Model saved to test_model.joblib")
    except Exception as e:
        print(f"Failed to save model: {str(e)}")
    
    return accuracy > 0.7  # Expect at least 70% accuracy

def visualize_predictions(test_data, predictions):
    """Visualize predictions in a 2D space."""
    print("\nVisualizing predictions...")
    
    # Extract coordinates and predictions
    lats = [sample['latitude'] for sample in test_data]
    lons = [sample['longitude'] for sample in test_data]
    true_antennas = [sample['optimal_antenna'] for sample in test_data]
    pred_antennas = [pred[4] for pred in predictions]
    
    # Define colors for each antenna
    antenna_colors = {
        'antenna_1': 'r',
        'antenna_2': 'g',
        'antenna_3': 'b'
    }
    
    # Create figure
    plt.figure(figsize=(12, 10))
    
    # Plot antenna locations
    antennas = {
        'antenna_1': (0, 0),
        'antenna_2': (1000, 0),
        'antenna_3': (500, 866)
    }
    
    for antenna_id, pos in antennas.items():
        plt.plot(pos[0], pos[1], 'ko', markersize=12)
        plt.text(pos[0] + 20, pos[1] + 20, antenna_id, fontsize=12)
    
    # Plot predictions
    for i, (lat, lon, true_ant, pred_ant) in enumerate(zip(lats, lons, true_antennas, pred_antennas)):
        # Use different markers for correct and incorrect predictions
        if true_ant == pred_ant:
            marker = 'o'  # Correct prediction
        else:
            marker = 'x'  # Incorrect prediction
        
        plt.plot(lat, lon, marker, color=antenna_colors[pred_ant], alpha=0.6, markersize=6)
    
    # Plot decision boundaries (simplified approach with a grid)
    grid_resolution = 50
    x_grid = np.linspace(0, 1000, grid_resolution)
    y_grid = np.linspace(0, 866, grid_resolution)
    X, Y = np.meshgrid(x_grid, y_grid)
    
    # Create a model for boundary prediction
    boundary_model = AntennaSelector()
    boundary_model.train(test_data)
    
    # Predict for each grid point
    Z = np.zeros((grid_resolution, grid_resolution), dtype=object)
    
    for i in range(grid_resolution):
        for j in range(grid_resolution):
            # Create dummy data
            dummy_data = {
                'latitude': X[i, j],
                'longitude': Y[i, j],
                'speed': 1.0,
                'direction': [1, 0, 0],
                'connected_to': 'antenna_1',
                'rf_metrics': {
                    'antenna_1': {'rsrp': -80, 'sinr': 10},
                    'antenna_2': {'rsrp': -80, 'sinr': 10},
                    'antenna_3': {'rsrp': -80, 'sinr': 10}
                }
            }
            
            # Make prediction
            features = boundary_model.extract_features(dummy_data)
            prediction = boundary_model.predict(features)
            Z[i, j] = prediction['antenna_id']
    
    # Convert Z to numeric for plotting
    Z_numeric = np.zeros_like(X)
    antenna_map = {'antenna_1': 1, 'antenna_2': 2, 'antenna_3': 3}
    
    for i in range(grid_resolution):
        for j in range(grid_resolution):
            Z_numeric[i, j] = antenna_map.get(Z[i, j], 0)
    
    # Plot decision boundaries
    plt.contourf(X, Y, Z_numeric, levels=3, alpha=0.2, cmap='viridis')
    
    plt.grid(True)
    plt.xlabel('X Position (m)')
    plt.ylabel('Y Position (m)')
    plt.title('Antenna Selection Predictions')
    
    # Add legend
    handles = []
    for antenna_id, color in antenna_colors.items():
        handles.append(plt.Line2D([0], [0], marker='o', color='w', 
                                  markerfacecolor=color, markersize=10, label=antenna_id))
    
    handles.append(plt.Line2D([0], [0], marker='o', color='w', 
                              markerfacecolor='k', markersize=10, label='Antenna Location'))
    
    handles.append(plt.Line2D([0], [0], marker='o', color='k', 
                              markerfacecolor='w', markersize=10, label='Correct Prediction'))
    
    handles.append(plt.Line2D([0], [0], marker='x', color='k', 
                              markerfacecolor='w', markersize=10, label='Incorrect Prediction'))
    
    plt.legend(handles=handles)
    
    os.makedirs('output', exist_ok=True)
    plt.savefig('output/prediction_visualization.png')
    plt.close()
    
    print("Prediction visualization saved to output/prediction_visualization.png")

if __name__ == "__main__":
    print("Testing ML Components...")
    
    results = []
    results.append(("Feature Extraction", test_feature_extraction()))
    results.append(("Model Training and Prediction", test_model_training_and_prediction()))
    
    print("\nSummary of Results:")
    for test_name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status} - {test_name}")