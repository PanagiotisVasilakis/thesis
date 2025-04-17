"""ML Service for 5G Network Optimization."""
from flask import Flask
import os
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

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
    from app.initialization.model_init import initialize_model
    app.logger.info("Initializing ML model...")
    initialize_model(app.config['MODEL_PATH'])
    app.logger.info("ML model initialization complete")
    
    # Register API blueprint
    from app.api import api_bp
    app.register_blueprint(api_bp)
    
    # Register visualization blueprint
    from app.api.visualization import viz_bp
    app.register_blueprint(viz_bp)
    
    # Log that initialization is complete
    app.logger.info("Flask application initialization complete")
    
    return app
    # Register Prometheus metrics
    from prometheus_client import make_wsgi_app
    from werkzeug.middleware.dispatcher import DispatcherMiddleware
    
    # Add metrics middleware
    from app.monitoring.metrics import MetricsMiddleware
    app.wsgi_app = MetricsMiddleware(app.wsgi_app)
    
    # Add Prometheus metrics endpoint
    metrics_app = make_wsgi_app()
    app.wsgi_app = DispatcherMiddleware(app.wsgi_app, {
        '/metrics': metrics_app
    })
    
    app.logger.info("Prometheus metrics enabled")
