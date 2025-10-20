"""DI-enabled API routes for ML Service demonstrating dependency injection."""

from flask import jsonify, request, current_app, g, Blueprint
import time
from pathlib import Path
from functools import wraps
import asyncio
from pydantic import ValidationError

from ..core.dependency_injection import inject, ServiceLocator, get_container
from ..core.interfaces import (
    ModelInterface,
    NEFClientInterface,
    DataCollectorInterface,
    CacheInterface,
    MetricsCollectorInterface,
    ConfigurationInterface,
    LoggerInterface,
)
from ..errors import (
    RequestValidationError,
    ModelError,
    NEFConnectionError,
)
from ..schemas import PredictionRequest, PredictionRequestWithQoS, TrainingSample, FeedbackSample
from ..validation import (
    validate_json_input,
    validate_request_size,
    validate_content_type,
    LoginRequest,
    CollectDataRequest,
)
from ..rate_limiter import limiter, limit_for

# Create blueprint for DI-enabled routes
di_bp = Blueprint('di_api', __name__, url_prefix='/di/api/v1')


class RouteServices:
    """Service locator for route handlers."""

    def __init__(self):
        self._container = get_container()

    @property
    def model(self) -> ModelInterface:
        return self._container.get('ModelInterface')

    @property
    def nef_client(self) -> NEFClientInterface:
        return self._container.get('NEFClientInterface')

    @property
    def data_collector(self) -> DataCollectorInterface:
        return self._container.get('DataCollectorInterface')

    @property
    def cache(self) -> CacheInterface:
        return self._container.get('CacheInterface')

    @property
    def metrics(self) -> MetricsCollectorInterface:
        return self._container.get('MetricsCollectorInterface')

    @property
    def config(self) -> ConfigurationInterface:
        return self._container.get('ConfigurationInterface')

    @property
    def logger(self) -> LoggerInterface:
        return self._container.get('LoggerInterface')


def get_services() -> RouteServices:
    """Get services for current request."""
    if not hasattr(g, 'services'):
        g.services = RouteServices()
    return g.services


def require_auth_di(func):
    """DI-enabled authentication decorator."""

    def _check_token():
        if current_app.testing:
            return None

        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return jsonify({"error": "Missing token"}), 401

        token = header.split(" ", 1)[1]

        # Use DI for authentication service when available
        try:
            auth_service = get_container().get('AuthenticationInterface')
            user = auth_service.verify_token(token)
        except Exception:
            # Fallback to original method
            from ..auth import verify_token
            user = verify_token(token)

        if not user:
            return jsonify({"error": "Invalid token"}), 401
        g.user = user

    if asyncio.iscoroutinefunction(func):

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            resp = _check_token()
            if resp is not None:
                return resp
            return await func(*args, **kwargs)

        return async_wrapper
    else:

        @wraps(func)
        def wrapper(*args, **kwargs):
            resp = _check_token()
            if resp is not None:
                return resp
            return func(*args, **kwargs)

        return wrapper


@di_bp.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint using DI."""
    services = get_services()
    services.logger.debug("Health check requested")

    return jsonify({"status": "ok", "service": "ml-service-di", "di_enabled": True})


@di_bp.route("/predict", methods=["POST"])
@require_auth_di
@limiter.limit(limit_for("predict"))
@validate_content_type("application/json")
@validate_request_size(5)  # 5MB max for prediction requests
@validate_json_input(PredictionRequest)
def predict_di():
    """Make antenna selection prediction using dependency injection."""
    req = request.validated_data  # type: ignore[attr-defined]
    services = get_services()

    # Log request
    services.logger.info(f"Prediction request for UE: {req.ue_id}")

    try:
        # Check cache first
        cache_key = f"prediction:{req.ue_id}:{hash(str(req.model_dump()))}"
        cached_result = services.cache.get(cache_key)

        if cached_result:
            services.logger.debug(f"Cache hit for UE: {req.ue_id}")
            services.metrics.track_prediction(cached_result["antenna_id"], cached_result["confidence"])
            return jsonify(
                {
                    "ue_id": req.ue_id,
                    "predicted_antenna": cached_result["antenna_id"],
                    "confidence": cached_result["confidence"],
                    "features_used": cached_result.get("features_used", []),
                    "cached": True,
                    "di_enabled": True,
                }
            )

        # Extract features and predict using DI model
        features = services.model.extract_features(req.model_dump(exclude_none=True))
        result = services.model.predict(features)

        # Cache result
        cache_value = {
            "antenna_id": result["antenna_id"],
            "confidence": result["confidence"],
            "features_used": list(features.keys()),
        }
        services.cache.set(cache_key, cache_value, ttl=30.0)  # 30 second TTL

        # Track metrics
        services.metrics.track_prediction(result["antenna_id"], result["confidence"])

        services.logger.info(
            f"Prediction completed for UE {req.ue_id}: {result['antenna_id']} "
            f"(confidence: {result['confidence']:.3f})"
        )

        return jsonify(
            {
                "ue_id": req.ue_id,
                "predicted_antenna": result["antenna_id"],
                "confidence": result["confidence"],
                "features_used": list(features.keys()),
                "cached": False,
                "di_enabled": True,
            }
        )

    except (ValueError, TypeError, KeyError) as exc:
        services.logger.error(f"Prediction failed for UE {req.ue_id}: {exc}")
        raise ModelError(f"Prediction failed: {exc}") from exc
    except Exception as exc:
        services.logger.error(f"Unexpected error in prediction for UE {req.ue_id}: {exc}")
        raise ModelError(f"Unexpected prediction error: {exc}") from exc


@di_bp.route("/predict-with-qos", methods=["POST"])
@require_auth_di
@limiter.limit(limit_for("predict"))
@validate_content_type("application/json")
@validate_request_size(5)  # 5MB max for prediction requests
@validate_json_input(PredictionRequestWithQoS)
def predict_di_with_qos():
    """Make antenna selection prediction considering QoS requirements using DI."""
    req = request.validated_data  # type: ignore[attr-defined]
    services = get_services()

    services.logger.info(f"Prediction request with QoS for UE: {req.ue_id}")

    try:
        # Extract features and predict using DI model
        features = services.model.extract_features(req.model_dump(exclude_none=True))
        result = services.model.predict(features)

        services.metrics.track_prediction(result["antenna_id"], result["confidence"])

        return jsonify(
            {
                "ue_id": req.ue_id,
                "predicted_antenna": result["antenna_id"],
                "confidence": result["confidence"],
                "qos_compliance": result.get("qos_compliance", True),
                "features_used": list(features.keys()),
                "cached": False,
                "di_enabled": True,
            }
        )

    except (ValueError, TypeError, KeyError) as exc:
        services.logger.error(f"Prediction failed for UE {req.ue_id}: {exc}")
        raise ModelError(f"Prediction failed: {exc}") from exc
    except Exception as exc:
        services.logger.error(f"Unexpected error in prediction for UE {req.ue_id}: {exc}")
        raise ModelError(f"Unexpected prediction error: {exc}") from exc


@di_bp.route("/nef-status", methods=["GET"])
@require_auth_di
def nef_status_di():
    """Check NEF connectivity using dependency injection."""
    services = get_services()

    try:
        response = services.nef_client.get_status()

        if hasattr(response, 'status_code') and response.status_code == 200:
            services.logger.info("NEF status check successful")
            return jsonify({
                "status": "connected",
                "nef_version": response.headers.get("X-API-Version", "unknown"),
                "di_enabled": True
            })

        services.logger.warning(f"NEF returned non-200 status: {response}")
        raise NEFConnectionError(f"NEF returned non-200 status: {response}")

    except Exception as exc:
        services.logger.error(f"NEF connection error: {exc}")
        raise NEFConnectionError(f"Failed to connect to NEF: {exc}") from exc


@di_bp.route("/collect-data", methods=["POST"])
@require_auth_di
@limiter.limit(limit_for("collect_data"))
@validate_content_type("application/json")
@validate_request_size(1)  # 1MB max for data collection params
@validate_json_input(CollectDataRequest, required=False)
async def collect_data_di():
    """Collect training data using dependency injection."""
    params = getattr(request, "validated_data", None)
    if params is None:
        params = CollectDataRequest.model_validate({})
    services = get_services()

    duration = params.duration
    interval = params.interval
    username = params.username
    password = params.password

    services.logger.info(f"Data collection request: {duration}s duration, {interval}s interval")

    # Authenticate if credentials provided
    if username and password and not services.data_collector.login():
        services.logger.error("Data collection authentication failed")
        raise RequestValidationError("Authentication failed")

    if not services.data_collector.get_ue_movement_state():
        services.logger.error("No UEs found in movement state")
        raise RequestValidationError("No UEs found in movement state")

    try:
        samples = await services.data_collector.collect_training_data(
            duration=duration, interval=interval
        )

        services.logger.info(f"Data collection completed: {len(samples)} samples")

        return jsonify({
            "samples": len(samples),
            "di_enabled": True
        })

    except Exception as exc:
        services.logger.error(f"Data collection failed: {exc}")
        raise NEFConnectionError(exc) from exc


@di_bp.route("/cache-stats", methods=["GET"])
@require_auth_di
def cache_stats_di():
    """Get cache statistics using dependency injection."""
    services = get_services()

    try:
        stats = services.cache.get_stats()

        return jsonify({
            "cache_stats": stats,
            "di_enabled": True
        })

    except Exception as exc:
        services.logger.error(f"Error getting cache stats: {exc}")
        return jsonify({"error": "Failed to get cache stats", "di_enabled": True}), 500


@di_bp.route("/metrics", methods=["GET"])
@require_auth_di
def metrics_di():
    """Get metrics using dependency injection."""
    services = get_services()

    try:
        metrics = services.metrics.get_metrics()

        return jsonify({
            "metrics": metrics,
            "di_enabled": True
        })

    except Exception as exc:
        services.logger.error(f"Error getting metrics: {exc}")
        return jsonify({"error": "Failed to get metrics", "di_enabled": True}), 500


@di_bp.route("/config", methods=["GET"])
@require_auth_di
def config_di():
    """Get configuration using dependency injection."""
    services = get_services()

    try:
        config = services.config.get_all()

        # Filter out sensitive information
        safe_config = {k: v for k, v in config.items()
                      if not any(sensitive in k.lower()
                               for sensitive in ['password', 'secret', 'key', 'token'])}

        return jsonify({
            "config": safe_config,
            "di_enabled": True
        })

    except Exception as exc:
        services.logger.error(f"Error getting config: {exc}")
        return jsonify({"error": "Failed to get config", "di_enabled": True}), 500


@di_bp.route("/services", methods=["GET"])
@require_auth_di
def services_info_di():
    """Get information about registered services."""
    container = get_container()
    services = get_services()

    try:
        registered_services = container.get_registered_services()

        return jsonify({
            "registered_services": registered_services,
            "service_count": len(registered_services),
            "di_enabled": True
        })

    except Exception as exc:
        services.logger.error(f"Error getting services info: {exc}")
        return jsonify({"error": "Failed to get services info", "di_enabled": True}), 500


# Utility function to inject services into any function
def inject_services(func):
    """Decorator to inject services into function parameters."""
    return inject(
        ModelInterface,
        NEFClientInterface,
        DataCollectorInterface,
        CacheInterface,
        MetricsCollectorInterface,
        ConfigurationInterface,
        LoggerInterface
    )(func)
