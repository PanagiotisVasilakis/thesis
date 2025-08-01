"""ML Service for 5G Network Optimization."""
from flask import Flask, Response, g, request
import uuid
import os
from prometheus_client import generate_latest
from ml_service.app.monitoring.metrics import MetricsMiddleware, MetricsCollector
from ml_service.app.rate_limiter import init_app as init_limiter
from ml_service.app.error_handlers import register_error_handlers
from .initialization.model_init import MODEL_VERSION


def create_app(config=None):
    """Create and configure the Flask application."""
    app = Flask(__name__)

    # Load default configuration
    app.config.from_mapping(
        SECRET_KEY="dev",
        NEF_API_URL="http://localhost:8080",
        MODEL_PATH=os.path.join(
            os.path.dirname(__file__),
            f"models/antenna_selector_v{MODEL_VERSION}.joblib",
        ),
        AUTH_USERNAME=os.getenv("AUTH_USERNAME", "admin"),
        AUTH_PASSWORD=os.getenv("AUTH_PASSWORD", "admin"),
        JWT_SECRET=os.getenv("JWT_SECRET", "change-me"),
        JWT_EXPIRES_MINUTES=int(os.getenv("JWT_EXPIRES_MINUTES", "30")),
    )

    # Load provided configuration if available
    if config:
        app.config.update(config)

    # Create models directory if it doesn't exist
    os.makedirs(os.path.dirname(app.config["MODEL_PATH"]), exist_ok=True)

    # Initialize model with synthetic data if needed
    from .initialization.model_init import ModelManager

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

    @app.route("/metrics")
    def metrics():
        """Expose Prometheus metrics."""
        return Response(
            generate_latest(),
            mimetype="text/plain; version=0.0.4",
        )

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
