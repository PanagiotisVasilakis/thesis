"""Main entry point for ML Service."""
import logging
import os

try:
    from services.logging_config import configure_logging  # type: ignore
except ImportError:
    def configure_logging(level=None, log_file=None):
        logging.basicConfig(level=level or logging.INFO)

from ml_service.app import create_app

configure_logging(level=os.getenv("LOG_LEVEL"), log_file=os.getenv("LOG_FILE"))
app = create_app()

if __name__ == "__main__":
    cert = os.getenv("SSL_CERTFILE")
    key = os.getenv("SSL_KEYFILE")
    ssl_context = (cert, key) if cert and key else None
    debug_mode = os.getenv("FLASK_DEBUG", "False").lower() in ("true", "1", "yes")
    app.run(host="0.0.0.0", port=5050, debug=debug_mode, ssl_context=ssl_context)
