"""API package for ML Service."""
from flask import Blueprint

api_bp = Blueprint("api", __name__, url_prefix="/api")

from . import routes  # noqa: F401,E402  # imported for side effects
