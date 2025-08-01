"""Centralized configuration validation for the ML service."""

import os
import logging
import warnings
from pathlib import Path
from typing import Dict, Any, Optional, List, Union
from urllib.parse import urlparse
import secrets
import string

from pydantic import BaseModel, Field, ValidationError, validator


class DatabaseConfig(BaseModel):
    """Configuration for database connections."""
    host: str = Field(default="localhost", description="Database host")
    port: int = Field(default=5432, ge=1, le=65535, description="Database port")
    name: str = Field(..., min_length=1, description="Database name")
    username: str = Field(..., min_length=1, description="Database username")
    password: str = Field(..., min_length=1, description="Database password")
    ssl_mode: str = Field(default="prefer", description="SSL mode for database connection")
    
    @validator('ssl_mode')
    def validate_ssl_mode(cls, v):
        valid_modes = ['disable', 'allow', 'prefer', 'require', 'verify-ca', 'verify-full']
        if v not in valid_modes:
            raise ValueError(f"SSL mode must be one of: {valid_modes}")
        return v


class ModelConfig(BaseModel):
    """Configuration for ML model settings."""
    type: str = Field(default="lightgbm", description="Model type")
    path: Optional[str] = Field(default=None, description="Path to model file")
    neighbor_count: int = Field(default=3, ge=0, le=10, description="Number of neighbor antennas")
    auto_retrain: bool = Field(default=True, description="Enable automatic retraining")
    retrain_threshold: float = Field(default=0.1, ge=0.0, le=1.0, description="Drift threshold for retraining")
    backup_count: int = Field(default=5, ge=1, le=20, description="Number of model backups to keep")
    
    @validator('type')
    def validate_model_type(cls, v):
        valid_types = ['lightgbm', 'lstm', 'ensemble', 'online']
        if v not in valid_types:
            raise ValueError(f"Model type must be one of: {valid_types}")
        return v
    
    @validator('path')
    def validate_model_path(cls, v):
        if v is not None:
            path = Path(v)
            # Create parent directory if it doesn't exist
            path.parent.mkdir(parents=True, exist_ok=True)
        return v


class NEFConfig(BaseModel):
    """Configuration for NEF emulator connection."""
    api_url: str = Field(..., description="NEF emulator API URL")
    username: Optional[str] = Field(default=None, description="NEF username")
    password: Optional[str] = Field(default=None, description="NEF password")
    timeout: float = Field(default=30.0, ge=1.0, le=300.0, description="Request timeout in seconds")
    max_retries: int = Field(default=3, ge=1, le=10, description="Maximum retry attempts")
    retry_delay: float = Field(default=1.0, ge=0.1, le=10.0, description="Delay between retries")
    
    @validator('api_url')
    def validate_api_url(cls, v):
        try:
            parsed = urlparse(v)
            if not parsed.scheme or not parsed.netloc:
                raise ValueError("Invalid URL format")
            if parsed.scheme not in ['http', 'https']:
                raise ValueError("URL scheme must be http or https")
        except Exception as e:
            raise ValueError(f"Invalid API URL: {e}")
        return v


class SecurityConfig(BaseModel):
    """Configuration for security settings."""
    secret_key: str = Field(..., min_length=32, description="Secret key for JWT tokens")
    jwt_secret: str = Field(..., min_length=32, description="JWT signing secret")
    auth_username: str = Field(..., min_length=1, description="Authentication username")
    auth_password: str = Field(..., min_length=8, description="Authentication password")
    jwt_expiry_hours: int = Field(default=24, ge=1, le=168, description="JWT token expiry in hours")
    rate_limit_per_minute: int = Field(default=100, ge=1, le=10000, description="Rate limit per minute")
    
    @validator('secret_key', 'jwt_secret')
    def validate_secrets(cls, v):
        if v in ['dev', 'development', 'test', 'changeme']:
            raise ValueError("Secret must not use default/weak values")
        return v
    
    @validator('auth_password')
    def validate_password_strength(cls, v):
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")
        
        has_upper = any(c.isupper() for c in v)
        has_lower = any(c.islower() for c in v)
        has_digit = any(c.isdigit() for c in v)
        
        if not (has_upper and has_lower and has_digit):
            warnings.warn(
                "Password should contain uppercase, lowercase, and numeric characters",
                UserWarning
            )
        return v


class LoggingConfig(BaseModel):
    """Configuration for logging settings."""
    level: str = Field(default="INFO", description="Logging level")
    format: str = Field(
        default="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        description="Log format string"
    )
    file_path: Optional[str] = Field(default=None, description="Log file path")
    max_file_size: int = Field(default=10*1024*1024, ge=1024, description="Max log file size in bytes")
    backup_count: int = Field(default=5, ge=1, le=50, description="Number of log file backups")
    
    @validator('level')
    def validate_log_level(cls, v):
        valid_levels = ['CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG']
        if v.upper() not in valid_levels:
            raise ValueError(f"Log level must be one of: {valid_levels}")
        return v.upper()


class PerformanceConfig(BaseModel):
    """Configuration for performance settings."""
    worker_processes: int = Field(default=4, ge=1, le=32, description="Number of worker processes")
    worker_threads: int = Field(default=2, ge=1, le=16, description="Threads per worker")
    request_timeout: int = Field(default=30, ge=5, le=300, description="Request timeout in seconds")
    max_request_size: int = Field(default=50*1024*1024, ge=1024, description="Max request size in bytes")
    connection_pool_size: int = Field(default=50, ge=1, le=1000, description="HTTP connection pool size")
    enable_metrics: bool = Field(default=True, description="Enable Prometheus metrics")
    metrics_port: int = Field(default=9090, ge=1024, le=65535, description="Metrics server port")


class MLServiceConfig(BaseModel):
    """Complete configuration for the ML service."""
    # Core settings
    debug: bool = Field(default=False, description="Enable debug mode")
    testing: bool = Field(default=False, description="Enable testing mode")
    host: str = Field(default="0.0.0.0", description="Server host")
    port: int = Field(default=5050, ge=1024, le=65535, description="Server port")
    
    # Component configurations
    model: ModelConfig = Field(default_factory=ModelConfig)
    nef: NEFConfig
    security: SecurityConfig
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    performance: PerformanceConfig = Field(default_factory=PerformanceConfig)
    database: Optional[DatabaseConfig] = Field(default=None, description="Database configuration")
    
    # Environment-specific overrides
    environment: str = Field(default="development", description="Deployment environment")
    
    @validator('environment')
    def validate_environment(cls, v):
        valid_envs = ['development', 'testing', 'staging', 'production']
        if v not in valid_envs:
            raise ValueError(f"Environment must be one of: {valid_envs}")
        return v
    
    @validator('debug')
    def validate_debug_in_production(cls, v, values):
        if v and values.get('environment') == 'production':
            raise ValueError("Debug mode cannot be enabled in production")
        return v


class ConfigValidator:
    """Centralized configuration validator and loader."""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self._config: Optional[MLServiceConfig] = None
        self._validation_errors: List[str] = []
    
    def _generate_secure_key(self, length: int = 64) -> str:
        """Generate a cryptographically secure random key."""
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
        return ''.join(secrets.choice(alphabet) for _ in range(length))
    
    def _load_from_environment(self) -> Dict[str, Any]:
        """Load configuration from environment variables."""
        config_data = {
            "debug": os.getenv("FLASK_DEBUG", "false").lower() == "true",
            "testing": os.getenv("TESTING", "false").lower() == "true",
            "host": os.getenv("HOST", "0.0.0.0"),
            "port": int(os.getenv("PORT", "5050")),
            "environment": os.getenv("ENVIRONMENT", "development"),
        }
        
        # Model configuration
        config_data["model"] = {
            "type": os.getenv("MODEL_TYPE", "lightgbm"),
            "path": os.getenv("MODEL_PATH"),
            "neighbor_count": int(os.getenv("NEIGHBOR_COUNT", "3")),
            "auto_retrain": os.getenv("AUTO_RETRAIN", "true").lower() == "true",
            "retrain_threshold": float(os.getenv("RETRAIN_THRESHOLD", "0.1")),
            "backup_count": int(os.getenv("MODEL_BACKUP_COUNT", "5")),
        }
        
        # NEF configuration
        nef_url = os.getenv("NEF_API_URL")
        if not nef_url:
            raise ValueError("NEF_API_URL environment variable is required")
        
        config_data["nef"] = {
            "api_url": nef_url,
            "username": os.getenv("NEF_USERNAME"),
            "password": os.getenv("NEF_PASSWORD"),
            "timeout": float(os.getenv("NEF_TIMEOUT", "30.0")),
            "max_retries": int(os.getenv("NEF_MAX_RETRIES", "3")),
            "retry_delay": float(os.getenv("NEF_RETRY_DELAY", "1.0")),
        }
        
        # Security configuration
        secret_key = os.getenv("SECRET_KEY")
        jwt_secret = os.getenv("JWT_SECRET")
        auth_username = os.getenv("AUTH_USERNAME")
        auth_password = os.getenv("AUTH_PASSWORD")
        
        # Generate secure defaults if not provided (with warnings)
        if not secret_key:
            secret_key = self._generate_secure_key()
            self.logger.warning("SECRET_KEY not set, generated random key (will not persist across restarts)")
        
        if not jwt_secret:
            jwt_secret = self._generate_secure_key()
            self.logger.warning("JWT_SECRET not set, generated random key (will not persist across restarts)")
        
        if not auth_username:
            auth_username = "admin"
            self.logger.warning("AUTH_USERNAME not set, using default 'admin'")
        
        if not auth_password:
            auth_password = self._generate_secure_key(16)
            self.logger.warning("AUTH_PASSWORD not set, generated random password: %s", auth_password)
        
        config_data["security"] = {
            "secret_key": secret_key,
            "jwt_secret": jwt_secret,
            "auth_username": auth_username,
            "auth_password": auth_password,
            "jwt_expiry_hours": int(os.getenv("JWT_EXPIRY_HOURS", "24")),
            "rate_limit_per_minute": int(os.getenv("RATE_LIMIT_PER_MINUTE", "100")),
        }
        
        # Logging configuration
        config_data["logging"] = {
            "level": os.getenv("LOG_LEVEL", "INFO"),
            "format": os.getenv("LOG_FORMAT", "%(asctime)s - %(name)s - %(levelname)s - %(message)s"),
            "file_path": os.getenv("LOG_FILE"),
            "max_file_size": int(os.getenv("LOG_MAX_SIZE", str(10*1024*1024))),
            "backup_count": int(os.getenv("LOG_BACKUP_COUNT", "5")),
        }
        
        # Performance configuration
        config_data["performance"] = {
            "worker_processes": int(os.getenv("WORKER_PROCESSES", "4")),
            "worker_threads": int(os.getenv("WORKER_THREADS", "2")),
            "request_timeout": int(os.getenv("REQUEST_TIMEOUT", "30")),
            "max_request_size": int(os.getenv("MAX_REQUEST_SIZE", str(50*1024*1024))),
            "connection_pool_size": int(os.getenv("CONNECTION_POOL_SIZE", "50")),
            "enable_metrics": os.getenv("ENABLE_METRICS", "true").lower() == "true",
            "metrics_port": int(os.getenv("METRICS_PORT", "9090")),
        }
        
        # Optional database configuration
        db_host = os.getenv("DB_HOST")
        if db_host:
            config_data["database"] = {
                "host": db_host,
                "port": int(os.getenv("DB_PORT", "5432")),
                "name": os.getenv("DB_NAME", "mlservice"),
                "username": os.getenv("DB_USERNAME", "mlservice"),
                "password": os.getenv("DB_PASSWORD", ""),
                "ssl_mode": os.getenv("DB_SSL_MODE", "prefer"),
            }
        
        return config_data
    
    def validate_config(self, config_data: Optional[Dict[str, Any]] = None) -> MLServiceConfig:
        """Validate configuration data and return validated config object."""
        if config_data is None:
            config_data = self._load_from_environment()
        
        self._validation_errors.clear()
        
        try:
            self._config = MLServiceConfig(**config_data)
            self.logger.info("Configuration validation successful")
            return self._config
            
        except ValidationError as e:
            self._validation_errors = [str(error) for error in e.errors()]
            error_msg = f"Configuration validation failed: {'; '.join(self._validation_errors)}"
            self.logger.error(error_msg)
            raise ValueError(error_msg) from e
    
    def get_config(self) -> MLServiceConfig:
        """Get the validated configuration object."""
        if self._config is None:
            raise RuntimeError("Configuration not validated. Call validate_config() first.")
        return self._config
    
    def get_validation_errors(self) -> List[str]:
        """Get list of validation errors from the last validation attempt."""
        return self._validation_errors.copy()
    
    def check_production_readiness(self) -> List[str]:
        """Check if configuration is ready for production deployment."""
        if self._config is None:
            return ["Configuration not validated"]
        
        warnings = []
        
        if self._config.environment != "production":
            warnings.append("Environment is not set to 'production'")
        
        if self._config.debug:
            warnings.append("Debug mode is enabled")
        
        if self._config.security.auth_password == "admin":
            warnings.append("Using default admin password")
        
        if len(self._config.security.secret_key) < 32:
            warnings.append("Secret key is too short")
        
        if self._config.nef.api_url.startswith("http://"):
            warnings.append("NEF API URL uses insecure HTTP")
        
        if not self._config.logging.file_path:
            warnings.append("No log file configured")
        
        if self._config.performance.worker_processes < 2:
            warnings.append("Only one worker process configured")
        
        return warnings


# Global configuration validator instance
config_validator = ConfigValidator()


def get_validated_config() -> MLServiceConfig:
    """Get the globally validated configuration."""
    return config_validator.get_config()


def validate_startup_config() -> MLServiceConfig:
    """Validate configuration at application startup."""
    try:
        config = config_validator.validate_config()
        
        # Check production readiness
        warnings = config_validator.check_production_readiness()
        if warnings:
            logging.getLogger(__name__).warning(
                "Production readiness warnings: %s", "; ".join(warnings)
            )
        
        return config
        
    except Exception as e:
        logging.getLogger(__name__).critical("Configuration validation failed: %s", e)
        raise