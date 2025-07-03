"""Main entry point for ML Service."""
from services.logging_config import configure_logging
from ml_service.app import create_app

configure_logging()
app = create_app()

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5050, debug=True)
