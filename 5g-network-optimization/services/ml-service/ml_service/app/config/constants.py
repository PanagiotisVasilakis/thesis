"""Centralized constants and configuration values for the ML service."""

import os
from typing import Dict, Any

# Network and Service Configuration
DEFAULT_NEF_URL = "http://localhost:8080"
DEFAULT_SERVICE_PORT = 5050
DEFAULT_SERVICE_HOST = "0.0.0.0"
DEFAULT_METRICS_PORT = 9090

# Database Configuration
DEFAULT_DB_HOST = "localhost"
DEFAULT_DB_PORT = 5432
DEFAULT_DB_SSL_MODE = "prefer"

# Model Configuration
DEFAULT_MODEL_TYPE = "lightgbm"
DEFAULT_NEIGHBOR_COUNT = 3
DEFAULT_MODEL_BACKUP_COUNT = 5
DEFAULT_RETRAIN_THRESHOLD = 0.1
DEFAULT_N_ESTIMATORS = 100
DEFAULT_LIGHTGBM_MAX_DEPTH = 10
DEFAULT_LIGHTGBM_RANDOM_STATE = 42

# Prediction Diversity Monitoring (prevents model collapse)
DEFAULT_PREDICTION_HISTORY_LIMIT = 100  # Max predictions to track
DEFAULT_DIVERSITY_WINDOW_SIZE = 50       # Window for diversity check
DEFAULT_DIVERSITY_MIN_RATIO = 0.3        # Min unique predictions ratio

# Training Validation Thresholds
DEFAULT_MIN_TRAINING_SAMPLES = 100       # Minimum samples required
DEFAULT_MIN_TRAINING_CLASSES = 2         # Minimum unique classes
DEFAULT_MAX_CLASS_IMBALANCE_RATIO = 10.0 # Max ratio between largest/smallest class

# Ping-Pong Prevention Thresholds
DEFAULT_IMMEDIATE_RETURN_CONFIDENCE = 0.95  # Confidence needed to override immediate return

# Circuit Breaker Configuration
DEFAULT_CIRCUIT_BREAKER_FAILURE_THRESHOLD = 5
DEFAULT_CIRCUIT_BREAKER_RECOVERY_TIMEOUT = 60.0
DEFAULT_CIRCUIT_BREAKER_SUCCESS_THRESHOLD = 2
DEFAULT_CIRCUIT_BREAKER_TIMEOUT = 30.0

# Memory Management Configuration
DEFAULT_UE_TRACKING_MAX_UES = 10000
DEFAULT_UE_TRACKING_TTL_HOURS = 24.0
DEFAULT_SIGNAL_WINDOW_SIZE = 5
DEFAULT_POSITION_WINDOW_SIZE = 5
DEFAULT_FEATURE_CACHE_SIZE = 1000
DEFAULT_FEATURE_CACHE_TTL = 30.0
DEFAULT_LRU_CACHE_SIZE = 1000
DEFAULT_MEMORY_MANAGED_DICT_SIZE = 1000

# Memory Optimization Configuration
DEFAULT_UE_TRACKING_MEMORY_LIMIT_MB = 256  # 256MB limit for UE tracking
DEFAULT_CACHE_MEMORY_LIMIT_MB = 128        # 128MB limit for general caches
DEFAULT_UE_TRACKING_CLEANUP_INTERVAL = 60.0  # 1 minute cleanup interval
DEFAULT_MEMORY_MONITORING_ENABLED = True
DEFAULT_MEMORY_EMERGENCY_CLEANUP_RATIO = 0.2  # Clean 20% during emergency

# Data Collection Configuration
DEFAULT_COLLECTION_DURATION = 60.0
DEFAULT_COLLECTION_INTERVAL = 1.0
MIN_COLLECTION_INTERVAL = 0.1
MAX_COLLECTION_INTERVAL = 300.0
MAX_COLLECTION_DURATION = 86400.0  # 24 hours
MAX_COLLECTION_SAMPLES = 100000
DEFAULT_COLLECTION_RETRIES = 2

# Performance Configuration
DEFAULT_CONNECTION_POOL_SIZE = 50
DEFAULT_PER_HOST_CONNECTION_LIMIT = 10
DEFAULT_CONNECTION_POOL_TTL = 300  # DNS cache TTL
DEFAULT_CONNECTION_KEEPALIVE_TIMEOUT = 30
DEFAULT_ASYNC_CONCURRENT_LIMIT = 10
DEFAULT_WORKER_PROCESSES = 4
DEFAULT_WORKER_THREADS = 2
DEFAULT_REQUEST_TIMEOUT = 30
DEFAULT_MAX_REQUEST_SIZE = 50 * 1024 * 1024  # 50MB

# Async Model Operations Configuration
DEFAULT_ASYNC_MODEL_WORKERS = 4
DEFAULT_MODEL_PREDICTION_TIMEOUT = 30.0
DEFAULT_MODEL_TRAINING_TIMEOUT = 600.0  # 10 minutes
DEFAULT_MODEL_EVALUATION_TIMEOUT = 300.0  # 5 minutes
DEFAULT_ASYNC_MODEL_QUEUE_SIZE = 1000
DEFAULT_ASYNC_MODEL_OPERATION_TIMEOUT = 300.0

# Monitoring and Metrics Configuration
DEFAULT_DATA_DRIFT_WINDOW_SIZE = 100
DEFAULT_DATA_DRIFT_MAX_SAMPLES = 10000
DEFAULT_SAMPLE_CHECK_INTERVAL = 1000
DEFAULT_METRICS_INTERVAL = 10.0
DEFAULT_STATS_LOG_INTERVAL = 3600.0  # 1 hour
DEFAULT_THREAD_MONITOR_JOIN_TIMEOUT = 5.0
DEFAULT_METRICS_STOP_TIMEOUT = 5.0
DEFAULT_FILE_WATCH_INTERVAL = 5.0

# Rate Limiting Configuration
DEFAULT_RATE_LIMIT_PER_MINUTE = 100
DEFAULT_RATE_LIMIT_BURST = 10

# Security Configuration
DEFAULT_JWT_EXPIRY_HOURS = 24
DEFAULT_SECRET_KEY_LENGTH = 64
DEFAULT_JWT_SECRET_LENGTH = 64
DEFAULT_PASSWORD_MIN_LENGTH = 8
DEFAULT_AUTH_USERNAME = "admin"

# Metrics Authentication Configuration
DEFAULT_METRICS_AUTH_ENABLED = True
DEFAULT_METRICS_AUTH_USERNAME = "metrics"
DEFAULT_METRICS_AUTH_PASSWORD = None  # Must be set via environment
DEFAULT_METRICS_API_KEY = None  # Must be set via environment
DEFAULT_METRICS_JWT_EXPIRY_SECONDS = 3600  # 1 hour
DEFAULT_METRICS_MAX_FAILED_ATTEMPTS = 5
DEFAULT_METRICS_LOCKOUT_DURATION = 300  # 5 minutes

# Input Sanitization Configuration
DEFAULT_INPUT_SANITIZER_STRICT_MODE = True
DEFAULT_INPUT_MAX_STRING_LENGTH = 10000
DEFAULT_INPUT_MAX_LIST_SIZE = 1000
DEFAULT_INPUT_MAX_DICT_SIZE = 1000
DEFAULT_INPUT_MAX_NESTING_DEPTH = 10
DEFAULT_INPUT_ALLOW_HTML = False
DEFAULT_INPUT_MAX_JSON_SIZE = 1024 * 1024  # 1MB

# Logging Configuration
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
DEFAULT_LOG_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
DEFAULT_LOG_BACKUP_COUNT = 5

# NEF Client Configuration
DEFAULT_NEF_TIMEOUT = 30.0
DEFAULT_NEF_MAX_RETRIES = 3
DEFAULT_NEF_RETRY_DELAY = 1.0
DEFAULT_NEF_EXPONENTIAL_BACKOFF_BASE = 2

# HTTP Status and Response Configuration
DEFAULT_FALLBACK_ANTENNA_ID = "antenna_1"
DEFAULT_FALLBACK_CONFIDENCE = 0.5
DEFAULT_FALLBACK_RSRP = -120.0
DEFAULT_FALLBACK_SINR = 0.0
DEFAULT_FALLBACK_RSRQ = -30.0

# Validation Configuration
DEFAULT_MAX_USERNAME_LENGTH = 100
DEFAULT_MAX_PASSWORD_LENGTH = 1000
DEFAULT_SAFE_STRING_MAX_LENGTH = 100
DEFAULT_LATITUDE_MIN = -90.0
DEFAULT_LATITUDE_MAX = 90.0
DEFAULT_LONGITUDE_MIN = -180.0
DEFAULT_LONGITUDE_MAX = 180.0

# Test and Synthetic Data Configuration
DEFAULT_TEST_FEATURES = {
    "latitude": 500,
    "longitude": 500,
    "speed": 1.0,
    "direction_x": 0.7,
    "direction_y": 0.7,
    "heading_change_rate": 0.0,
    "path_curvature": 0.0,
    "velocity": 1.0,
    "acceleration": 0.0,
    "cell_load": 0.0,
    "handover_count": 0,
    "time_since_handover": 0.0,
    "signal_trend": 0.0,
    "environment": 0.0,
    "rsrp_stddev": 0.0,
    "sinr_stddev": 0.0,
    "rsrp_current": -90,
    "sinr_current": 10,
    "rsrq_current": -10,
    "best_rsrp_diff": 0.0,
    "best_sinr_diff": 0.0,
    "best_rsrq_diff": 0.0,
    "altitude": 0.0,
    "service_type": "default",
    "service_type_label": "default",
    "service_priority": 5,
    "latency_requirement_ms": 50.0,
    "throughput_requirement_mbps": 100.0,
    "jitter_ms": 5.0,
    "reliability_pct": 99.0,
    "latency_ms": 50.0,
    "throughput_mbps": 100.0,
    "packet_loss_rate": 0.0,
    "observed_latency_ms": 50.0,
    "observed_throughput_mbps": 100.0,
    "observed_jitter_ms": 5.0,
    "observed_packet_loss_rate": 0.0,
    "latency_delta_ms": 0.0,
    "throughput_delta_mbps": 0.0,
    "reliability_delta_pct": 1.0,
}

DEFAULT_SYNTHETIC_DATA_GRID_SIZE = 1000
DEFAULT_SYNTHETIC_DATA_BATCH_SIZE = 100

# Prometheus Metrics Configuration
PREDICTION_LATENCY_BUCKETS = [0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]
TRAINING_DURATION_BUCKETS = [0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0]

# Visualization Configuration
DEFAULT_VISUALIZATION_RESOLUTION = 100
DEFAULT_VISUALIZATION_GRID_SIZE = 1000
DEFAULT_ANTENNA_POSITIONS = {
    "antenna_1": (0, 0), 
    "antenna_2": (1000, 0), 
    "antenna_3": (500, 866)
}

# Docker and Container Configuration
DEFAULT_CONTAINER_USER_ID = 1001
DEFAULT_CONTAINER_GROUP_ID = 1001
DEFAULT_GUNICORN_MAX_REQUESTS = 1000
DEFAULT_GUNICORN_MAX_REQUESTS_JITTER = 100

# Environment Variables with Defaults
def get_env_int(key: str, default: int) -> int:
    """Get integer environment variable with default."""
    try:
        return int(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default

def get_env_float(key: str, default: float) -> float:
    """Get float environment variable with default."""
    try:
        return float(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default

def get_env_bool(key: str, default: bool) -> bool:
    """Get boolean environment variable with default."""
    value = os.getenv(key, str(default)).lower()
    return value in ('true', '1', 'yes', 'on')

def get_env_str(key: str, default: str) -> str:
    """Get string environment variable with default."""
    return os.getenv(key, default)

# Dynamic Configuration Based on Environment
class EnvironmentConstants:
    """Environment-specific constants that can be overridden via environment variables."""
    
    # Network Configuration
    NEF_URL = get_env_str("NEF_API_URL", DEFAULT_NEF_URL)
    SERVICE_PORT = get_env_int("PORT", DEFAULT_SERVICE_PORT)
    SERVICE_HOST = get_env_str("HOST", DEFAULT_SERVICE_HOST)
    METRICS_PORT = get_env_int("METRICS_PORT", DEFAULT_METRICS_PORT)
    
    # Model Configuration
    MODEL_TYPE = get_env_str("MODEL_TYPE", DEFAULT_MODEL_TYPE)
    NEIGHBOR_COUNT = get_env_int("NEIGHBOR_COUNT", DEFAULT_NEIGHBOR_COUNT)
    N_ESTIMATORS = get_env_int("N_ESTIMATORS", DEFAULT_N_ESTIMATORS)
    AUTO_RETRAIN = get_env_bool("AUTO_RETRAIN", True)
    RETRAIN_THRESHOLD = get_env_float("RETRAIN_THRESHOLD", DEFAULT_RETRAIN_THRESHOLD)
    
    # Memory Management
    UE_TRACKING_MAX_UES = get_env_int("UE_TRACKING_MAX_UES", DEFAULT_UE_TRACKING_MAX_UES)
    UE_TRACKING_TTL_HOURS = get_env_float("UE_TRACKING_TTL_HOURS", DEFAULT_UE_TRACKING_TTL_HOURS)
    SIGNAL_WINDOW_SIZE = get_env_int("SIGNAL_WINDOW_SIZE", DEFAULT_SIGNAL_WINDOW_SIZE)
    POSITION_WINDOW_SIZE = get_env_int("POSITION_WINDOW_SIZE", DEFAULT_POSITION_WINDOW_SIZE)
    FEATURE_CACHE_SIZE = get_env_int("FEATURE_CACHE_SIZE", DEFAULT_FEATURE_CACHE_SIZE)
    FEATURE_CACHE_TTL = get_env_float("FEATURE_CACHE_TTL", DEFAULT_FEATURE_CACHE_TTL)
    
    # Performance
    CONNECTION_POOL_SIZE = get_env_int("CONNECTION_POOL_SIZE", DEFAULT_CONNECTION_POOL_SIZE)
    PER_HOST_CONNECTION_LIMIT = get_env_int("PER_HOST_CONNECTION_LIMIT", DEFAULT_PER_HOST_CONNECTION_LIMIT)
    WORKER_PROCESSES = get_env_int("WORKER_PROCESSES", DEFAULT_WORKER_PROCESSES)
    WORKER_THREADS = get_env_int("WORKER_THREADS", DEFAULT_WORKER_THREADS)
    REQUEST_TIMEOUT = get_env_int("REQUEST_TIMEOUT", DEFAULT_REQUEST_TIMEOUT)
    
    # Circuit Breaker
    CIRCUIT_BREAKER_FAILURE_THRESHOLD = get_env_int("CB_FAILURE_THRESHOLD", DEFAULT_CIRCUIT_BREAKER_FAILURE_THRESHOLD)
    CIRCUIT_BREAKER_RECOVERY_TIMEOUT = get_env_float("CB_RECOVERY_TIMEOUT", DEFAULT_CIRCUIT_BREAKER_RECOVERY_TIMEOUT)
    CIRCUIT_BREAKER_SUCCESS_THRESHOLD = get_env_int("CB_SUCCESS_THRESHOLD", DEFAULT_CIRCUIT_BREAKER_SUCCESS_THRESHOLD)
    CIRCUIT_BREAKER_TIMEOUT = get_env_float("CB_TIMEOUT", DEFAULT_CIRCUIT_BREAKER_TIMEOUT)
    
    # Data Collection
    COLLECTION_DURATION = get_env_float("COLLECTION_DURATION", DEFAULT_COLLECTION_DURATION)
    COLLECTION_INTERVAL = get_env_float("COLLECTION_INTERVAL", DEFAULT_COLLECTION_INTERVAL)
    COLLECTION_RETRIES = get_env_int("COLLECTION_RETRIES", DEFAULT_COLLECTION_RETRIES)
    
    # Monitoring
    DATA_DRIFT_WINDOW_SIZE = get_env_int("DATA_DRIFT_WINDOW_SIZE", DEFAULT_DATA_DRIFT_WINDOW_SIZE)
    DATA_DRIFT_MAX_SAMPLES = get_env_int("DATA_DRIFT_MAX_SAMPLES", DEFAULT_DATA_DRIFT_MAX_SAMPLES)
    METRICS_INTERVAL = get_env_float("METRICS_INTERVAL", DEFAULT_METRICS_INTERVAL)
    STATS_LOG_INTERVAL = get_env_float("STATS_LOG_INTERVAL", DEFAULT_STATS_LOG_INTERVAL)
    
    # Rate Limiting
    RATE_LIMIT_PER_MINUTE = get_env_int("RATE_LIMIT_PER_MINUTE", DEFAULT_RATE_LIMIT_PER_MINUTE)
    
    # NEF Client
    NEF_TIMEOUT = get_env_float("NEF_TIMEOUT", DEFAULT_NEF_TIMEOUT)
    NEF_MAX_RETRIES = get_env_int("NEF_MAX_RETRIES", DEFAULT_NEF_MAX_RETRIES)
    NEF_RETRY_DELAY = get_env_float("NEF_RETRY_DELAY", DEFAULT_NEF_RETRY_DELAY)
    
    # Security
    JWT_EXPIRY_HOURS = get_env_int("JWT_EXPIRY_HOURS", DEFAULT_JWT_EXPIRY_HOURS)
    JWT_SECRET = get_env_str("JWT_SECRET", None)
    
    # Metrics Authentication
    METRICS_AUTH_ENABLED = get_env_bool("METRICS_AUTH_ENABLED", DEFAULT_METRICS_AUTH_ENABLED)
    METRICS_AUTH_USERNAME = get_env_str("METRICS_AUTH_USERNAME", DEFAULT_METRICS_AUTH_USERNAME)
    METRICS_AUTH_PASSWORD = get_env_str("METRICS_AUTH_PASSWORD", DEFAULT_METRICS_AUTH_PASSWORD)
    METRICS_API_KEY = get_env_str("METRICS_API_KEY", DEFAULT_METRICS_API_KEY)
    METRICS_JWT_EXPIRY_SECONDS = get_env_int("METRICS_JWT_EXPIRY_SECONDS", DEFAULT_METRICS_JWT_EXPIRY_SECONDS)
    METRICS_MAX_FAILED_ATTEMPTS = get_env_int("METRICS_MAX_FAILED_ATTEMPTS", DEFAULT_METRICS_MAX_FAILED_ATTEMPTS)
    METRICS_LOCKOUT_DURATION = get_env_int("METRICS_LOCKOUT_DURATION", DEFAULT_METRICS_LOCKOUT_DURATION)
    
    # Input Sanitization
    INPUT_SANITIZER_STRICT_MODE = get_env_bool("INPUT_SANITIZER_STRICT_MODE", DEFAULT_INPUT_SANITIZER_STRICT_MODE)
    INPUT_MAX_STRING_LENGTH = get_env_int("INPUT_MAX_STRING_LENGTH", DEFAULT_INPUT_MAX_STRING_LENGTH)
    INPUT_MAX_LIST_SIZE = get_env_int("INPUT_MAX_LIST_SIZE", DEFAULT_INPUT_MAX_LIST_SIZE)
    INPUT_MAX_DICT_SIZE = get_env_int("INPUT_MAX_DICT_SIZE", DEFAULT_INPUT_MAX_DICT_SIZE)
    INPUT_MAX_NESTING_DEPTH = get_env_int("INPUT_MAX_NESTING_DEPTH", DEFAULT_INPUT_MAX_NESTING_DEPTH)
    INPUT_ALLOW_HTML = get_env_bool("INPUT_ALLOW_HTML", DEFAULT_INPUT_ALLOW_HTML)
    INPUT_MAX_JSON_SIZE = get_env_int("INPUT_MAX_JSON_SIZE", DEFAULT_INPUT_MAX_JSON_SIZE)
    
    # Memory Optimization
    UE_TRACKING_MEMORY_LIMIT_MB = get_env_int("UE_TRACKING_MEMORY_LIMIT_MB", DEFAULT_UE_TRACKING_MEMORY_LIMIT_MB)
    CACHE_MEMORY_LIMIT_MB = get_env_int("CACHE_MEMORY_LIMIT_MB", DEFAULT_CACHE_MEMORY_LIMIT_MB)
    UE_TRACKING_CLEANUP_INTERVAL = get_env_float("UE_TRACKING_CLEANUP_INTERVAL", DEFAULT_UE_TRACKING_CLEANUP_INTERVAL)
    MEMORY_MONITORING_ENABLED = get_env_bool("MEMORY_MONITORING_ENABLED", DEFAULT_MEMORY_MONITORING_ENABLED)
    MEMORY_EMERGENCY_CLEANUP_RATIO = get_env_float("MEMORY_EMERGENCY_CLEANUP_RATIO", DEFAULT_MEMORY_EMERGENCY_CLEANUP_RATIO)
    
    # Logging
    LOG_LEVEL = get_env_str("LOG_LEVEL", DEFAULT_LOG_LEVEL)
    LOG_MAX_FILE_SIZE = get_env_int("LOG_MAX_SIZE", DEFAULT_LOG_MAX_FILE_SIZE)
    LOG_BACKUP_COUNT = get_env_int("LOG_BACKUP_COUNT", DEFAULT_LOG_BACKUP_COUNT)
    
    # Async Model Operations
    ASYNC_MODEL_WORKERS = get_env_int("ASYNC_MODEL_WORKERS", DEFAULT_ASYNC_MODEL_WORKERS)
    MODEL_PREDICTION_TIMEOUT = get_env_float("MODEL_PREDICTION_TIMEOUT", DEFAULT_MODEL_PREDICTION_TIMEOUT)
    MODEL_TRAINING_TIMEOUT = get_env_float("MODEL_TRAINING_TIMEOUT", DEFAULT_MODEL_TRAINING_TIMEOUT)
    MODEL_EVALUATION_TIMEOUT = get_env_float("MODEL_EVALUATION_TIMEOUT", DEFAULT_MODEL_EVALUATION_TIMEOUT)
    ASYNC_MODEL_QUEUE_SIZE = get_env_int("ASYNC_MODEL_QUEUE_SIZE", DEFAULT_ASYNC_MODEL_QUEUE_SIZE)
    ASYNC_MODEL_OPERATION_TIMEOUT = get_env_float("ASYNC_MODEL_OPERATION_TIMEOUT", DEFAULT_ASYNC_MODEL_OPERATION_TIMEOUT)
    
    @classmethod
    def get_all_constants(cls) -> Dict[str, Any]:
        """Get all environment constants as a dictionary."""
        return {
            key: value for key, value in cls.__dict__.items()
            if not key.startswith('_') and not callable(value)
        }
    
    @classmethod
    def validate_constants(cls) -> Dict[str, str]:
        """Validate all constants and return any validation errors."""
        errors = {}
        
        # Validate ranges
        if cls.SERVICE_PORT < 1024 or cls.SERVICE_PORT > 65535:
            errors["SERVICE_PORT"] = f"Port must be between 1024-65535, got {cls.SERVICE_PORT}"
        
        if cls.NEIGHBOR_COUNT < 0 or cls.NEIGHBOR_COUNT > 10:
            errors["NEIGHBOR_COUNT"] = f"Neighbor count must be 0-10, got {cls.NEIGHBOR_COUNT}"
        
        if cls.RETRAIN_THRESHOLD < 0.0 or cls.RETRAIN_THRESHOLD > 1.0:
            errors["RETRAIN_THRESHOLD"] = f"Retrain threshold must be 0.0-1.0, got {cls.RETRAIN_THRESHOLD}"
        
        if cls.COLLECTION_INTERVAL < MIN_COLLECTION_INTERVAL or cls.COLLECTION_INTERVAL > MAX_COLLECTION_INTERVAL:
            errors["COLLECTION_INTERVAL"] = f"Collection interval must be {MIN_COLLECTION_INTERVAL}-{MAX_COLLECTION_INTERVAL}, got {cls.COLLECTION_INTERVAL}"
        
        if cls.UE_TRACKING_MAX_UES <= 0:
            errors["UE_TRACKING_MAX_UES"] = f"UE tracking max UEs must be positive, got {cls.UE_TRACKING_MAX_UES}"
        
        if cls.FEATURE_CACHE_TTL <= 0:
            errors["FEATURE_CACHE_TTL"] = f"Feature cache TTL must be positive, got {cls.FEATURE_CACHE_TTL}"
        
        return errors

# Create instance for easy access
env_constants = EnvironmentConstants()

# Backward compatibility aliases
FALLBACK_ANTENNA_ID = DEFAULT_FALLBACK_ANTENNA_ID
FALLBACK_CONFIDENCE = DEFAULT_FALLBACK_CONFIDENCE