"""Visualization endpoints for ML Service."""
from flask import Blueprint, jsonify, request, current_app, send_file
import os
import json
import logging
from app.models.antenna_selector import AntennaSelector
from app.visualization.plotter import plot_antenna_coverage, plot_movement_trajectory
from app.utils.synthetic_data import generate_synthetic_training_data

viz_bp = Blueprint('visualization', __name__, url_prefix='/api/visualization')

logger = logging.getLogger(__name__)

# Initialize the model
model = AntennaSelector()


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
            logger.warning(
                f"Model not trained: {str(e)}. Training with synthetic data..."
            )
            training_data = generate_synthetic_training_data(500)
            model.train(training_data)
            logger.info("Model trained successfully with synthetic data")
        
        # Define absolute output directory path - this is the crucial fix
        output_dir = os.path.abspath(os.path.join(os.getcwd(), 'output'))
        os.makedirs(output_dir, exist_ok=True)
        
        # Generate visualization with absolute path
        output_file = plot_antenna_coverage(model, output_dir=output_dir)
        
        # Check if the file exists
        if not os.path.exists(output_file):
            logger.warning(f"Output file not found at {output_file}")
            # Try to find the file in the relative path
            relative_path = os.path.join('output', os.path.basename(output_file))
            if os.path.exists(relative_path):
                output_file = os.path.abspath(relative_path)
                logger.info(f"Found file at {output_file}")
        
        # Return the image file
        return send_file(output_file, mimetype='image/png')
    
    except Exception as e:
        import traceback
        logger.error(f"Error generating coverage map: {str(e)}")
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
        
        # Define absolute output directory path
        output_dir = os.path.abspath(os.path.join(os.getcwd(), 'output'))
        os.makedirs(output_dir, exist_ok=True)
        
        # Generate visualization with absolute path
        output_file = plot_movement_trajectory(movement_data, output_dir=output_dir)
        
        # Return the image file
        return send_file(output_file, mimetype='image/png')
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500
