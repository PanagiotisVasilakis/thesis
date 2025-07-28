"""Main entry point for ML Service."""
import os

from services.logging_config import configure_logging
from ml_service.app import create_app

configure_logging(level=os.getenv("LOG_LEVEL"), log_file=os.getenv("LOG_FILE"))
app = create_app()

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5050, debug=True)
