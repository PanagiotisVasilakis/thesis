"""Visualization endpoints for ML Service."""
from flask import Blueprint, jsonify, request, current_app, send_file
import os
import json
from app.models.antenna_selector import AntennaSelector
from app.visualization.plotter import plot_antenna_coverage, plot_movement_trajectory

viz_bp = Blueprint('visualization', __name__, url_prefix='/api/visualization')

# Initialize the model
model = AntennaSelector()

@viz_bp.route('/coverage-map', methods=['GET'])
def coverage_map():
    """Generate and return an antenna coverage map."""
    try:
        # Load model if available
        model_path = current_app.config.get('MODEL_PATH')
        if os.path.exists(model_path):
            model.load(model_path)
        
        # Generate visualization
        output_file = plot_antenna_coverage(model)
        
        # Return the image file
        return send_file(output_file, mimetype='image/png')
    
    except Exception as e:
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
