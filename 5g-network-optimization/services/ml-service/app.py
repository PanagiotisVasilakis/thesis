"""Main entry point for ML Service."""
import os

from services.logging_config import configure_logging
from ml_service.app import create_app

configure_logging(level=os.getenv("LOG_LEVEL"), log_file=os.getenv("LOG_FILE"))
app = create_app()

if __name__ == "__main__":
    cert = os.getenv("SSL_CERTFILE")
    key = os.getenv("SSL_KEYFILE")
    ssl_context = (cert, key) if cert and key else None
    app.run(host="0.0.0.0", port=5050, debug=True, ssl_context=ssl_context)
