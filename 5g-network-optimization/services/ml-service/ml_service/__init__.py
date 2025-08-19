"""ML service package."""

# The full application factory pulls in heavy optional dependencies
# (e.g. LightGBM and Dask). Importing it at module import time causes
# unnecessary import-time side effects during test collection.  To keep
# imports lightweight and avoid import errors in environments where
# optional dependencies are absent, we expose ``create_app`` lazily.

from typing import Any, Dict, Optional


def create_app(config: Optional[Dict[str, Any]] = None):
    """Lazy wrapper for the Flask application factory."""
    from .app import create_app as _create_app

    return _create_app(config)


__all__ = ["create_app"]

