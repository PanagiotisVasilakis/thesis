"""Flask error handlers for custom ML service exceptions."""

from flask import jsonify, g
import uuid

from .errors import (
    MLServiceError,
    ModelError,
    RequestValidationError,
    NEFConnectionError,
    ResourceNotFoundError,
)


def _format_error(err: Exception) -> dict:
    """Return the JSON payload for an error response."""
    cid = getattr(g, "correlation_id", str(uuid.uuid4()))
    return {"error": str(err), "type": err.__class__.__name__, "correlation_id": cid}


def register_error_handlers(app):
    """Register handlers for custom exceptions on the given Flask app."""

    def handle_request_validation(err):
        app.logger.error("Request validation failed: %s [cid=%s]", err, getattr(g, "correlation_id", ""))
        return jsonify(_format_error(err)), 400

    def handle_model_error(err):
        app.logger.error("Model error: %s [cid=%s]", err, getattr(g, "correlation_id", ""))
        return jsonify(_format_error(err)), 500

    def handle_nef_error(err):
        app.logger.error("NEF connection error: %s [cid=%s]", err, getattr(g, "correlation_id", ""))
        return jsonify(_format_error(err)), 502

    def handle_not_found(err):
        app.logger.error("Resource not found: %s [cid=%s]", err, getattr(g, "correlation_id", ""))
        return jsonify(_format_error(err)), 404

    def handle_generic(err):
        app.logger.error("Service error: %s [cid=%s]", err, getattr(g, "correlation_id", ""))
        return jsonify(_format_error(err)), 500

    app.register_error_handler(RequestValidationError, handle_request_validation)
    app.register_error_handler(ModelError, handle_model_error)
    app.register_error_handler(NEFConnectionError, handle_nef_error)
    app.register_error_handler(ResourceNotFoundError, handle_not_found)
    app.register_error_handler(MLServiceError, handle_generic)
