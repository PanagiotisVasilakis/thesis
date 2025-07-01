"""API package for ML Service."""
from flask import Blueprint

api_bp = Blueprint('api', __name__, url_prefix='/api')

from ml_service.api import routes
