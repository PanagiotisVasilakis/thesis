"""Application bootstrap for initializing dependency injection."""

import logging
from typing import Dict, Any, Optional
from flask import Flask

from .dependency_injection import get_container, configure_container
from .service_configuration import configure_services, get_service_factory
from .interfaces import *
from ..config.constants import env_constants

logger = logging.getLogger(__name__)


class ApplicationBootstrap:
    """Bootstrap class for initializing the application with dependency injection."""
    
    def __init__(self, app: Optional[Flask] = None):
        """Initialize bootstrap with optional Flask app."""
        self._app = app
        self._container = get_container()
        self._initialized = False
    
    def initialize(self, config_overrides: Optional[Dict[str, Any]] = None) -> None:
        """Initialize the application with dependency injection."""
        if self._initialized:
            logger.warning("Application already initialized")
            return
        
        logger.info("Initializing application with dependency injection...")
        
        try:
            # Configure DI container with services
            config_overrides = config_overrides or {}
            configure_services(self._container, **config_overrides)
            
            # Register Flask app if provided
            if self._app:
                self._register_flask_services()
            
            # Validate configuration
            self._validate_configuration()
            
            # Register cleanup handlers
            self._register_cleanup_handlers()
            
            self._initialized = True
            logger.info("Application initialization completed successfully")
            
        except Exception as exc:
            logger.error(f"Application initialization failed: {exc}")
            raise
    
    def _register_flask_services(self) -> None:
        """Register Flask-specific services."""
        logger.debug("Registering Flask-specific services")
        
        # Register Flask app instance
        self._container.register_instance('FlaskApp', self._app)
        
        # Create Flask-aware logger
        flask_logger = self._app.logger
        self._container.register_instance('FlaskLogger', flask_logger)
        
        # Register Flask config as additional configuration source
        flask_config = dict(self._app.config)
        self._container.register_instance('FlaskConfig', flask_config)
    
    def _validate_configuration(self) -> None:
        """Validate the configuration."""
        logger.debug("Validating configuration")
        
        try:
            config_service = self._container.get('ConfigurationInterface')
            validation_errors = config_service.validate_config()
            
            if validation_errors:
                logger.warning("Configuration validation warnings:")
                for key, error in validation_errors.items():
                    logger.warning(f"  {key}: {error}")
            else:
                logger.debug("Configuration validation passed")
                
        except Exception as exc:
            logger.error(f"Configuration validation failed: {exc}")
            raise
    
    def _register_cleanup_handlers(self) -> None:
        """Register cleanup handlers for graceful shutdown."""
        logger.debug("Registering cleanup handlers")
        
        import atexit
        
        def cleanup_resources():
            """Cleanup all registered resources."""
            try:
                logger.info("Cleaning up application resources...")
                
                # Get resource manager and cleanup
                if self._container.is_registered('ResourceManagerInterface'):
                    resource_manager = self._container.get('ResourceManagerInterface')
                    resource_manager.cleanup_all_resources()
                
                # Clear DI container
                self._container.clear()
                
                logger.info("Application cleanup completed")
                
            except Exception as exc:
                logger.error(f"Error during cleanup: {exc}")
        
        atexit.register(cleanup_resources)
    
    def get_container(self):
        """Get the DI container."""
        return self._container
    
    def get_service(self, interface_name: str):
        """Get a service by interface name."""
        if not self._initialized:
            raise RuntimeError("Application not initialized")
        
        return self._container.get(interface_name)
    
    def is_initialized(self) -> bool:
        """Check if application is initialized."""
        return self._initialized
    
    def get_service_info(self) -> Dict[str, Any]:
        """Get information about registered services."""
        return {
            "initialized": self._initialized,
            "registered_services": self._container.get_registered_services(),
            "service_count": len(self._container.get_registered_services())
        }


# Global bootstrap instance
_bootstrap: Optional[ApplicationBootstrap] = None


def get_bootstrap() -> ApplicationBootstrap:
    """Get the global bootstrap instance."""
    global _bootstrap
    
    if _bootstrap is None:
        _bootstrap = ApplicationBootstrap()
    
    return _bootstrap


def initialize_application(app: Optional[Flask] = None, 
                          config_overrides: Optional[Dict[str, Any]] = None) -> ApplicationBootstrap:
    """Initialize the application with dependency injection."""
    bootstrap = get_bootstrap()
    
    if app:
        bootstrap._app = app
    
    bootstrap.initialize(config_overrides)
    return bootstrap


def create_app_with_di(config_overrides: Optional[Dict[str, Any]] = None) -> Flask:
    """Create Flask app with dependency injection configured."""
    from flask import Flask
    
    app = Flask(__name__)
    
    # Load configuration
    app.config.update({
        'NEF_API_URL': env_constants.NEF_URL,
        'MODEL_PATH': '/tmp/ml_model.pkl',
        'AUTH_USERNAME': 'admin',
        'AUTH_PASSWORD': 'password',
        'SECRET_KEY': 'dev-secret-key',
        'JWT_SECRET': 'jwt-secret-key'
    })
    
    # Override with provided config
    if config_overrides:
        app.config.update(config_overrides)
    
    # Initialize dependency injection
    bootstrap = initialize_application(app, config_overrides)
    
    # Register blueprints
    from ..api.di_routes import di_bp
    app.register_blueprint(di_bp)
    
    # Add DI context to app
    app.di_container = bootstrap.get_container()
    app.di_bootstrap = bootstrap
    
    logger.info("Flask app created with dependency injection")
    
    return app


class DIFlaskExtension:
    """Flask extension for dependency injection."""
    
    def __init__(self, app: Optional[Flask] = None):
        """Initialize the extension."""
        self._bootstrap = None
        
        if app is not None:
            self.init_app(app)
    
    def init_app(self, app: Flask, config_overrides: Optional[Dict[str, Any]] = None) -> None:
        """Initialize the extension with Flask app."""
        # Initialize bootstrap
        self._bootstrap = initialize_application(app, config_overrides)
        
        # Add to app context
        app.di_container = self._bootstrap.get_container()
        app.di_bootstrap = self._bootstrap
        
        # Add context processors
        @app.context_processor
        def inject_di_services():
            """Inject DI services into template context."""
            return {
                'di_container': self._bootstrap.get_container(),
                'di_services': self._bootstrap.get_service_info()
            }
        
        # Add before_request handler for service injection
        @app.before_request
        def setup_request_services():
            """Setup services for each request."""
            from flask import g
            g.di_container = self._bootstrap.get_container()
        
        logger.info("DI Flask extension initialized")
    
    def get_service(self, interface_name: str):
        """Get a service by interface name."""
        if not self._bootstrap:
            raise RuntimeError("Extension not initialized")
        
        return self._bootstrap.get_service(interface_name)
    
    def get_container(self):
        """Get the DI container."""
        if not self._bootstrap:
            raise RuntimeError("Extension not initialized")
        
        return self._bootstrap.get_container()


# Example usage functions
def setup_production_app() -> Flask:
    """Setup production Flask app with DI."""
    config_overrides = {
        'NEF_URL': env_constants.NEF_URL,
        'MODEL_PATH': '/app/models/antenna_selector.pkl',
        'LOG_LEVEL': 'INFO',
        'FEATURE_CACHE_SIZE': 5000,
        'FEATURE_CACHE_TTL': 60.0
    }
    
    return create_app_with_di(config_overrides)


def setup_development_app() -> Flask:
    """Setup development Flask app with DI."""
    config_overrides = {
        'NEF_URL': 'http://localhost:8080',
        'MODEL_PATH': '/tmp/dev_model.pkl',
        'LOG_LEVEL': 'DEBUG',
        'FEATURE_CACHE_SIZE': 1000,
        'FEATURE_CACHE_TTL': 30.0
    }
    
    return create_app_with_di(config_overrides)


def setup_test_app() -> Flask:
    """Setup test Flask app with DI."""
    config_overrides = {
        'TESTING': True,
        'NEF_URL': 'http://mock-nef:8080',
        'MODEL_PATH': '/tmp/test_model.pkl',
        'LOG_LEVEL': 'DEBUG',
        'FEATURE_CACHE_SIZE': 100,
        'FEATURE_CACHE_TTL': 10.0
    }
    
    return create_app_with_di(config_overrides)


# Convenience functions for common DI patterns
def get_model_service() -> ModelInterface:
    """Get the model service."""
    return get_bootstrap().get_service('ModelInterface')


def get_cache_service() -> CacheInterface:
    """Get the cache service."""
    return get_bootstrap().get_service('CacheInterface')


def get_metrics_service() -> MetricsCollectorInterface:
    """Get the metrics service."""
    return get_bootstrap().get_service('MetricsCollectorInterface')