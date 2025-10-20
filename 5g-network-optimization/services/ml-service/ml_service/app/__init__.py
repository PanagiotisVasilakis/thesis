"""ML Service for 5G Network Optimization."""

from flask import Flask

# Re-export commonly patched components for tests
from .monitoring.metrics import MetricsCollector  # noqa: F401


def create_app(config=None):
    """Create and configure the Flask application."""
    # Import heavy dependencies lazily to keep module import light-weight
    import os
    import uuid
    from flask import Response, g, request
    from prometheus_client import generate_latest

    from ml_service.app.monitoring import metrics
    from ml_service.app.monitoring.metrics import MetricsMiddleware
    from ml_service.app.rate_limiter import init_app as init_limiter
    from ml_service.app.error_handlers import register_error_handlers
    from .initialization.model_init import MODEL_VERSION

    app = Flask(__name__)

    def _parse_roles(raw: str | list[str] | None) -> list[str]:
        if raw is None:
            return []
        if isinstance(raw, list):
            return [role for role in raw if role]
        parts = [part.strip() for part in str(raw).split(",")]
        return [part for part in parts if part]

    def _parse_rate_limits() -> dict[str, str]:
        return {
            "login": os.getenv("RATELIMIT_LOGIN", "10 per minute"),
            "predict": os.getenv("RATELIMIT_PREDICT", "60 per minute"),
            "predict_async": os.getenv("RATELIMIT_PREDICT_ASYNC", "60 per minute"),
            "train": os.getenv("RATELIMIT_TRAIN", "10 per minute"),
            "train_async": os.getenv("RATELIMIT_TRAIN_ASYNC", "6 per hour"),
            "collect_data": os.getenv("RATELIMIT_COLLECT_DATA", "5 per minute"),
            "feedback": os.getenv("RATELIMIT_FEEDBACK", "30 per minute"),
            "refresh": os.getenv("RATELIMIT_REFRESH", "30 per hour"),
            "circuit_breaker": os.getenv("RATELIMIT_CIRCUIT_BREAKER", "20 per minute"),
        }

    # Load default configuration
    default_roles = _parse_roles(os.getenv("AUTH_ROLES"))
    if not default_roles:
        default_roles = ["admin"]
    default_config = dict(
        SECRET_KEY=os.getenv("SECRET_KEY", os.urandom(32).hex()),
        NEF_API_URL="http://localhost:8080",
        MODEL_PATH=os.path.join(
            os.path.dirname(__file__),
            f"models/antenna_selector_v{MODEL_VERSION}.joblib",
        ),
        AUTH_USERNAME=os.getenv("AUTH_USERNAME"),
        AUTH_PASSWORD=os.getenv("AUTH_PASSWORD"),
        JWT_SECRET=os.getenv("JWT_SECRET", os.urandom(32).hex()),
        JWT_EXPIRES_MINUTES=int(os.getenv("JWT_EXPIRES_MINUTES", "30")),
        JWT_REFRESH_SECRET=os.getenv("JWT_REFRESH_SECRET"),
        JWT_REFRESH_EXPIRES_MINUTES=int(os.getenv("JWT_REFRESH_EXPIRES_MINUTES", "4320")),
        AUTH_ROLES=default_roles,
        RATELIMIT_DEFAULT=os.getenv("RATELIMIT_DEFAULT", "100 per minute"),
        RATELIMIT_STORAGE_URI=os.getenv("RATELIMIT_STORAGE_URI", "memory://"),
        RATE_LIMITS=_parse_rate_limits(),
    )
    app.config.from_mapping(default_config)
    
    # Ensure required auth configuration is provided
    if config:
        app.config.update(config)
        app.config["AUTH_ROLES"] = _parse_roles(app.config.get("AUTH_ROLES")) or default_roles

    if not app.config.get("AUTH_USERNAME") or not app.config.get("AUTH_PASSWORD"):
        # Check if we're in test mode - in which case allow no auth
        if not app.testing:
            app.logger.error(
                "AUTH_USERNAME and AUTH_PASSWORD environment variables are not set. "
                "Authentication is required for production deployment."
            )
            # Raise an error to prevent the application from starting without authentication in production
            raise ValueError(
                "Authentication credentials must be provided via AUTH_USERNAME and AUTH_PASSWORD environment variables for production deployments"
            )
        else:
            app.logger.warning(
                "AUTH_USERNAME and AUTH_PASSWORD environment variables are not set. "
                "Applying default credentials for tests only."
            )
            if not app.config.get("AUTH_USERNAME"):
                app.config["AUTH_USERNAME"] = os.getenv("TEST_AUTH_USERNAME", "test_user")
            if not app.config.get("AUTH_PASSWORD"):
                app.config["AUTH_PASSWORD"] = os.getenv(
                    "TEST_AUTH_PASSWORD", "test_secure_password_123!"
                )

    # Create models directory if it doesn't exist
    os.makedirs(os.path.dirname(app.config["MODEL_PATH"]), exist_ok=True)

    # Initialize model with synthetic data if needed. Skip during tests to
    # avoid expensive background training and related side effects.
    from .initialization.model_init import ModelManager

    if not app.testing:
        app.logger.info("Initializing ML model...")
        ModelManager.initialize(app.config["MODEL_PATH"], background=True)
        app.logger.info("ML model initialization started")

    # Register API blueprint
    from .api import api_bp

    app.register_blueprint(api_bp)

    # Register circuit breaker management blueprint
    from .api.circuit_breaker import circuit_breaker_bp

    app.register_blueprint(circuit_breaker_bp)

    # Register visualization blueprint
    from .api.visualization import viz_bp

    app.register_blueprint(viz_bp)

    # Initialise rate limiting (disabled automatically during testing)
    init_limiter(app)

    # Import metrics authentication
    from .auth.metrics_auth import require_metrics_auth, get_metrics_authenticator
    
    @app.route("/metrics")
    @require_metrics_auth if not app.testing else (lambda f: f)
    def metrics_endpoint():
        """Expose Prometheus metrics with authentication."""
        return Response(
            generate_latest(metrics.REGISTRY),
            mimetype="text/plain; version=0.0.4",
        )

    @app.route("/metrics/auth/token", methods=["POST"])
    @require_metrics_auth if not app.testing else (lambda f: f)
    def create_metrics_token():
        """Create a JWT token for metrics access."""
        from .auth.metrics_auth import create_metrics_auth_token
        try:
            token = create_metrics_auth_token()
            return {"token": token, "expires_in": app.config.get("METRICS_JWT_EXPIRY_SECONDS", 3600)}
        except Exception as e:
            app.logger.error("Failed to create metrics token: %s", e)
            return {"error": "Failed to create token"}, 500

    @app.route("/metrics/auth/stats")
    @require_metrics_auth if not app.testing else (lambda f: f)
    def metrics_auth_stats():
        """Get metrics authentication statistics."""
        auth = get_metrics_authenticator()
        return auth.get_auth_stats()

    # Wrap the application with metrics middleware
    app.wsgi_app = MetricsMiddleware(app.wsgi_app)

    # Start background collector for drift and resource metrics
    collector = MetricsCollector()
    collector.start()
    app.metrics_collector = collector  # type: ignore[attr-defined]

    @app.teardown_appcontext
    def _shutdown_metrics_collector(exception=None):
        """Stop background metric collection when the app context ends."""
        if hasattr(app, "metrics_collector"):
            app.metrics_collector.stop()  # type: ignore[attr-defined]

    register_error_handlers(app)

    @app.before_request
    def _set_correlation_id():
        g.correlation_id = str(uuid.uuid4())
        app.logger.info(
            "Received %s request for %s [cid=%s]",
            request.method,
            request.path,
            g.correlation_id,
        )

    @app.after_request
    def _log_response(resp):
        cid = getattr(g, "correlation_id", "")
        app.logger.info("Responding with %s [cid=%s]", resp.status, cid)
        resp.headers["X-Correlation-ID"] = cid
        return resp

    # Log that initialization is complete
    app.logger.info("Flask application initialization complete")

    return app
