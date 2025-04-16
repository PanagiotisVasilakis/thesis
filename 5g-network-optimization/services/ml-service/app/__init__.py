from flask import Flask

def create_app(config=None):
    """Create Flask application."""
    app = Flask(__name__)
    
    # Load default configuration
    app.config.from_mapping(
        SECRET_KEY='dev',
        NEF_API_URL='http://nef-emulator:8080',
        MODEL_PATH='./models/handover_model.joblib'
    )
    
    # Load the instance config if it exists
    if config:
        app.config.update(config)
    
    # Register blueprints
    from app.routes import ml_api
    app.register_blueprint(ml_api)
    
    return app
