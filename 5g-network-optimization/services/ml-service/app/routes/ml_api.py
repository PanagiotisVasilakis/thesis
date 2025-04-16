from flask import Blueprint, request, jsonify, current_app
import requests
import json

ml_api = Blueprint('ml_api', __name__, url_prefix='/api/ml')

@ml_api.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'ok',
        'service': 'ml-service'
    })

@ml_api.route('/network-state', methods=['GET'])
def get_network_state():
    """Get network state from NEF emulator"""
    try:
        nef_url = current_app.config['NEF_API_URL']
        response = requests.get(f"{nef_url}/api/network-state")
        return jsonify(response.json())
    except Exception as e:
        return jsonify({'error': str(e)}), 500
