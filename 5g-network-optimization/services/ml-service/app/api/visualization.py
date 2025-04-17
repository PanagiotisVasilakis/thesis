"""Visualization endpoints for ML Service."""
from flask import Blueprint, jsonify, request, current_app, send_file
import os
import json
import numpy as np
from app.models.antenna_selector import AntennaSelector
from app.visualization.plotter import plot_antenna_coverage, plot_movement_trajectory

viz_bp = Blueprint('visualization', __name__, url_prefix='/api/visualization')

# Initialize the model
model = AntennaSelector()

def generate_synthetic_training_data(num_samples=500):
    """Generate synthetic data for training the model."""
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

@viz_bp.route('/coverage-map', methods=['GET'])
def coverage_map():
    """Generate and return an antenna coverage map."""
    try:
        # First, check if the model is trained
        try:
            # Try a simple prediction to see if model is trained
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
        except Exception as e:
            # Model is not trained, train it with synthetic data
            print(f"Model not trained: {str(e)}. Training with synthetic data...")
            training_data = generate_synthetic_training_data(500)
            model.train(training_data)
            print("Model trained successfully with synthetic data")
        
        # Generate visualization
        output_file = plot_antenna_coverage(model, output_dir='output')
        
        # Return the image file
        return send_file(output_file, mimetype='image/png')
    
    except Exception as e:
        import traceback
        print(f"Error generating coverage map: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@viz_bp.route('/trajectory', methods=['POST'])
def trajectory():
    """Generate and return a movement trajectory visualization."""
    try:
        # Get movement data from request
        movement_data = request.json
        
        if not movement_data:
            return jsonify({'error': 'No movement data provided'}), 400
        
        # Generate visualization
        output_file = plot_movement_trajectory(movement_data)
        
        # Return the image file
        return send_file(output_file, mimetype='image/png')
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500
