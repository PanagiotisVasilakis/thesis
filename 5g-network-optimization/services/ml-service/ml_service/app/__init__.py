"""ML Service for 5G Network Optimization."""
from flask import Flask, Response
import os
import logging
from prometheus_client import generate_latest
from ml_service.app.monitoring.metrics import MetricsMiddleware

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
    
    # Create models directory if it doesn't exist
    os.makedirs(os.path.dirname(app.config['MODEL_PATH']), exist_ok=True)
    
    # Initialize model with synthetic data if needed
    from .initialization.model_init import ModelManager
    app.logger.info("Initializing ML model...")
    ModelManager.initialize(app.config['MODEL_PATH'])
    app.logger.info("ML model initialization complete")
    
    # Register API blueprint
    from .api import api_bp
    app.register_blueprint(api_bp)
    
    # Register visualization blueprint
    from .api.visualization import viz_bp
    app.register_blueprint(viz_bp)

    @app.route("/metrics")
    def metrics():
        """Expose Prometheus metrics."""
        return Response(generate_latest(), mimetype="text/plain; version=0.0.4")

    # Wrap the application with metrics middleware
    app.wsgi_app = MetricsMiddleware(app.wsgi_app)

    # Log that initialization is complete
    app.logger.info("Flask application initialization complete")

    return app
