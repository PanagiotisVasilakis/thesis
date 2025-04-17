"""ML Service for 5G Network Optimization."""
from flask import Flask
import os

def create_app(config=None):
    """Create and configure the Flask application."""
    app = Flask(__name__)
    
    # Load default configuration
    app.config.from_mapping(
        SECRET_KEY='dev',
        NEF_API_URL='http://localhost:8080',
        MODEL_PATH=os.path.join(os.path.dirname(__file__), 'models/antenna_selector.joblib')
    )
    
    # Load provided configuration if available
    if config:
        app.config.update(config)
    
    # Register blueprints
    from app.api import api_bp
    app.register_blueprint(api_bp)
    
    return app

    # Register visualization blueprint
    from app.api.visualization import viz_bp
    app.register_blueprint(viz_bp)
