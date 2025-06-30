"""Main entry point for ML Service."""
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))
from logging_config import configure_logging
from app import create_app

configure_logging()
app = create_app()

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5050, debug=True)
