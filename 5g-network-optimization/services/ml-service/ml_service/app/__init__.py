"""ML Service for 5G Network Optimization."""

from flask import Flask


def create_app(config=None):
    """Create and configure the Flask application."""
    # Import heavy dependencies lazily to keep module import light-weight
    import os
    import uuid
    from flask import Response, g, request
    from prometheus_client import generate_latest

    from ml_service.app.monitoring import metrics
    from ml_service.app.monitoring.metrics import MetricsMiddleware, MetricsCollector
    from ml_service.app.rate_limiter import init_app as init_limiter
    from ml_service.app.error_handlers import register_error_handlers
    from .initialization.model_init import MODEL_VERSION

    app = Flask(__name__)

    # Load default configuration
    app.config.from_mapping(
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
    )
    
    # Ensure required auth configuration is provided
    if not app.config.get("AUTH_USERNAME") or not app.config.get("AUTH_PASSWORD"):
        app.logger.warning(
            "AUTH_USERNAME and AUTH_PASSWORD environment variables are not set. "
            "Authentication will be disabled. This is not recommended for production."
        )

    # Load provided configuration if available
    if config:
        app.config.update(config)

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

    # Register visualization blueprint
    from .api.visualization import viz_bp

    app.register_blueprint(viz_bp)

    # Initialise rate limiting (disabled during testing)
    if not app.testing:
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
    app.metrics_collector = collector

    @app.teardown_appcontext
    def _shutdown_metrics_collector(exception=None):
        """Stop background metric collection when the app context ends."""
        if hasattr(app, "metrics_collector"):
            app.metrics_collector.stop()

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
