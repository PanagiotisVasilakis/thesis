"""Prometheus metrics for ML service."""
from prometheus_client import CollectorRegistry, Counter, Histogram, Gauge
import json
import logging
import time
import os
import threading
from pathlib import Path
from typing import Any, Dict, List

import psutil

logger = logging.getLogger(__name__)

# Use a dedicated registry so tests can reload this module without
# "Duplicated timeseries" errors from the default global registry. Each
# metric is explicitly registered against this registry.
REGISTRY = CollectorRegistry()

from ..config.constants import (
    PREDICTION_LATENCY_BUCKETS,
    TRAINING_DURATION_BUCKETS,
    DEFAULT_DATA_DRIFT_WINDOW_SIZE,
    DEFAULT_DATA_DRIFT_MAX_SAMPLES,
    DEFAULT_SAMPLE_CHECK_INTERVAL,
    DEFAULT_METRICS_INTERVAL,
    DEFAULT_METRICS_STOP_TIMEOUT,
    env_constants
)
from ..utils.exception_handler import (
    ExceptionHandler,
    ResourceError,
    exception_context,
    safe_execute,
    ErrorSeverity
)
from ..utils.resource_manager import (
    global_resource_manager,
    ResourceType
)

# Track prediction requests
PREDICTION_REQUESTS = Counter(
    'ml_prediction_requests_total',
    'Total number of prediction requests',
    ['status'],
    registry=REGISTRY,
)

# Track prediction latency
PREDICTION_LATENCY = Histogram(
    'ml_prediction_latency_seconds',
    'Latency of antenna selection predictions',
    buckets=PREDICTION_LATENCY_BUCKETS,
    registry=REGISTRY,
)

# Track prediction outcomes
ANTENNA_PREDICTIONS = Counter(
    'ml_antenna_predictions_total',
    'Antenna selection predictions',
    ['antenna_id'],
    registry=REGISTRY,
)

# Track prediction confidence
PREDICTION_CONFIDENCE = Gauge(
    'ml_prediction_confidence_avg',
    'Average confidence of antenna predictions',
    ['antenna_id'],
    registry=REGISTRY,
)

# Track model training
MODEL_TRAINING_DURATION = Histogram(
    'ml_model_training_duration_seconds',
    'Duration of model training',
    buckets=TRAINING_DURATION_BUCKETS,
    registry=REGISTRY,
)

MODEL_TRAINING_SAMPLES = Gauge(
    'ml_model_training_samples',
    'Number of samples used for model training',
    registry=REGISTRY,
)

MODEL_TRAINING_ACCURACY = Gauge(
    'ml_model_training_accuracy',
    'Accuracy of trained model',
    registry=REGISTRY,
)

# Track latest feature importance values
FEATURE_IMPORTANCE = Gauge(
    'ml_feature_importance',
    'Latest feature importance score',
    ['feature'],
    registry=REGISTRY,
)

# --- Operational and Drift Metrics ---

# Data drift indicator updated by ``MetricsCollector``
DATA_DRIFT_SCORE = Gauge(
    'ml_data_drift_score',
    'Average change between consecutive feature distributions',
    registry=REGISTRY,
)

# Rate of failed prediction requests over the last collection interval
ERROR_RATE = Gauge(
    'ml_prediction_error_rate',
    'Fraction of prediction requests resulting in an error',
    registry=REGISTRY,
)

# Resource usage of the ML service process
CPU_USAGE = Gauge(
    'ml_cpu_usage_percent',
    'CPU utilisation of the ML service process',
    registry=REGISTRY,
)

MEMORY_USAGE = Gauge(
    'ml_memory_usage_bytes',
    'Resident memory usage of the ML service process in bytes',
    registry=REGISTRY,
)

# --- Anti-Ping-Pong Metrics ---

# Track ping-pong suppression events by reason
PING_PONG_SUPPRESSIONS = Counter(
    'ml_pingpong_suppressions_total',
    'Number of times ping-pong prevention blocked a handover',
    ['reason'],  # 'too_recent', 'too_many', 'immediate_return'
    registry=REGISTRY,
)

# Track time between consecutive handovers
HANDOVER_INTERVAL = Histogram(
    'ml_handover_interval_seconds',
    'Time between consecutive handovers for UEs',
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 300.0, 600.0],
    registry=REGISTRY,
)

class MetricsMiddleware:
    """Middleware to track metrics for API endpoints."""

    def __init__(self, app):
        """Initialize the middleware."""
        self.app = app

    def __call__(self, environ, start_response):
        """Track metrics for the request."""
        path = environ.get('PATH_INFO', '')

        # Only track metrics for API endpoints
        if path.startswith('/api/'):
            # Track start time
            start_time = time.time()

            # Track response
            def custom_start_response(status, headers, exc_info=None):
                status_code = int(status.split()[0])
                endpoint = path.split('/')[-1]

                # Track request status
                if status_code < 400:
                    PREDICTION_REQUESTS.labels(status='success').inc()
                else:
                    PREDICTION_REQUESTS.labels(status='error').inc()

                # Track latency if it's a prediction request
                if endpoint == 'predict':
                    PREDICTION_LATENCY.observe(time.time() - start_time)

                return start_response(status, headers, exc_info)

            return self.app(environ, custom_start_response)

        return self.app(environ, start_response)

def track_prediction(antenna_id, confidence):
    """Track antenna prediction."""
    ANTENNA_PREDICTIONS.labels(antenna_id=antenna_id).inc()
    PREDICTION_CONFIDENCE.labels(antenna_id=antenna_id).set(confidence)

def store_feature_importance(feature_importance: Dict[str, float], path: str | None = None) -> None:
    """Persist feature importance values to a JSON file.

    Parameters
    ----------
    feature_importance:
        Mapping of feature name to importance score.
    path:
        Optional override for the output path. Defaults to the
        ``FEATURE_IMPORTANCE_PATH`` environment variable or
        ``/tmp/feature_importance.json``.
    """
    file_path = path or os.environ.get("FEATURE_IMPORTANCE_PATH", "/tmp/feature_importance.json")
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(feature_importance, f)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to store feature importance: %s", exc)


def track_training(
    duration: float,
    num_samples: int,
    accuracy: float | None = None,
    feature_importance: Dict[str, float] | None = None,
    store_path: str | None = None,
) -> None:
    """Track model training and feature importance."""
    MODEL_TRAINING_DURATION.observe(duration)
    MODEL_TRAINING_SAMPLES.set(num_samples)
    if accuracy is not None:
        MODEL_TRAINING_ACCURACY.set(accuracy)
    if feature_importance:
        for name, value in feature_importance.items():
            FEATURE_IMPORTANCE.labels(feature=name).set(value)
        store_feature_importance(feature_importance, path=store_path)


class DataDriftMonitor:
    """Compute feature distribution changes over rolling windows."""

    def __init__(
        self,
        window_size: int = DEFAULT_DATA_DRIFT_WINDOW_SIZE,
        max_samples: int = DEFAULT_DATA_DRIFT_MAX_SAMPLES,
        *,
        threshold: float = 1.0,
        thresholds: Dict[str, float] | None = None,
        baseline: Dict[str, float] | None = None,
        baseline_path: str | None = None,
    ) -> None:
        if window_size <= 0:
            raise ValueError("Window size must be positive")
        if max_samples < window_size * 2:
            raise ValueError("Max samples must be at least 2x window size")

        self.window_size = window_size
        self.max_samples = max_samples
        self.threshold = threshold
        self.thresholds = thresholds or {}
        self._baseline: Dict[str, float] | None = baseline or (
            self._load_baseline(baseline_path) if baseline_path else None
        )

        self._current: List[Dict[str, float]] = []
        self._previous: List[Dict[str, float]] = []
        self._lock = threading.Lock()
        self._sample_count = 0

        import logging
        self.logger = logging.getLogger(__name__)

    def _load_baseline(self, path: str) -> Dict[str, float] | None:
        """Load baseline distribution from a JSON or YAML file."""
        if not path:
            return None
        try:
            p = Path(path)
            if not p.exists():
                self.logger.warning("Baseline file %s does not exist", path)
                return None
            text = p.read_text(encoding="utf-8")
            if p.suffix.lower() in {".yaml", ".yml"}:
                import yaml
                data = yaml.safe_load(text) or {}
            else:
                data = json.loads(text)
            return {str(k): float(v) for k, v in data.items()}
        except Exception as exc:  # noqa: BLE001
            self.logger.error("Failed to load baseline from %s: %s", path, exc)
            return None

    def update(self, features: Dict[str, float]) -> None:
        """Add feature vector from a prediction request with memory bounds."""
        numeric = {k: v for k, v in features.items() if isinstance(v, (int, float))}
        if not numeric:
            return
            
        with self._lock:
            self._sample_count += 1
            self._current.append(numeric)
            
            # Enforce window size limit
            if len(self._current) > self.window_size:
                self._current.pop(0)
            
            # Enforce global memory limit - emergency cleanup
            if self._sample_count % DEFAULT_SAMPLE_CHECK_INTERVAL == 0:  # Check periodically
                total_samples = len(self._current) + len(self._previous)
                if total_samples > self.max_samples:
                    self.logger.warning(
                        "DataDriftMonitor approaching memory limit (%d/%d samples). "
                        "Performing emergency cleanup.", 
                        total_samples, self.max_samples
                    )
                    # Keep only most recent samples
                    excess = total_samples - self.max_samples // 2
                    if len(self._previous) > excess:
                        self._previous = self._previous[excess:]
                    else:
                        self._previous.clear()
                        remaining_excess = excess - len(self._previous)
                        if len(self._current) > remaining_excess:
                            self._current = self._current[remaining_excess:]

    def _mean(self, samples: List[Dict[str, float]]) -> Dict[str, float]:
        totals: Dict[str, float] = {}
        counts: Dict[str, int] = {}
        for sample in samples:
            for k, v in sample.items():
                totals[k] = totals.get(k, 0.0) + v
                counts[k] = counts.get(k, 0) + 1
        return {k: totals[k] / counts[k] for k in totals}

    def compute_drift(self) -> float:
        """Return average absolute change between current window and baseline.

        The first full window establishes the baseline distribution unless one
        is provided explicitly. Subsequent windows are compared against this
        baseline. When drift for any feature exceeds its configured threshold, a
        warning is logged.
        """
        with self._lock:
            if len(self._current) < self.window_size:
                return 0.0

            curr_means = self._mean(self._current)
            if self._baseline is None:
                self._baseline = curr_means
                self._current.clear()
                return 0.0

            keys = set(self._baseline).intersection(curr_means)
            if not keys:
                self._current.clear()
                return 0.0

            diffs = {k: abs(curr_means[k] - self._baseline[k]) for k in keys}
            self._current.clear()

            alerts = {k: v for k, v in diffs.items() if v > self.thresholds.get(k, self.threshold)}
            for feat, val in alerts.items():
                self._log_alert(feat, val, self.thresholds.get(feat, self.threshold))

            return sum(diffs.values()) / len(diffs)
    
    def get_memory_stats(self) -> Dict[str, Any]:
        """Get memory usage statistics for monitoring."""
        with self._lock:
            return {
                "current_samples": len(self._current),
                "previous_samples": len(self._previous),
                "total_samples": len(self._current) + len(self._previous),
                "max_samples": self.max_samples,
                "window_size": self.window_size,
                "sample_count": self._sample_count,
                "memory_utilization": (len(self._current) + len(self._previous)) / self.max_samples
            }
    
    def reset(self) -> None:
        """Reset all stored data and counters."""
        with self._lock:
            self._current.clear()
            self._previous.clear()
            self._sample_count = 0
            self.logger.info("DataDriftMonitor reset - all data cleared")

    def _log_alert(self, feature: str, drift: float, threshold: float) -> None:
        """Log a warning when drift exceeds the configured threshold."""
        self.logger.warning(
            "Data drift detected for %s: %.4f exceeds threshold %.4f",
            feature,
            drift,
            threshold,
        )


class MetricsCollector:
    """Background thread updating operational metrics."""

    def __init__(self, interval: float = DEFAULT_METRICS_INTERVAL, drift_monitor: DataDriftMonitor | None = None) -> None:
        if interval <= 0:
            raise ValueError(f"Interval must be positive, got {interval}")
        if interval < 1.0:
            logger.warning("Very short monitoring interval (%.2fs) may impact performance", interval)
        
        self.interval = interval
        self.drift_monitor = drift_monitor or DataDriftMonitor()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="MetricsCollector")
        self._last_success = 0.0
        self._last_error = 0.0
        
        # Initialize process monitor with error handling
        try:
            self._process = psutil.Process(os.getpid())
            logger.info("Metrics collector initialized for PID %d", os.getpid())
        except psutil.NoSuchProcess:
            logger.critical("Cannot initialize process monitor - current process doesn't exist")
            raise
        except Exception as e:
            logger.error("Error initializing process monitor: %s", e)
            raise
        
        # Register with resource manager
        self._resource_id = global_resource_manager.register_resource(
            self,
            ResourceType.OTHER,
            cleanup_method=self._cleanup_resources,
            metadata={
                "component": "MetricsCollector",
                "interval": self.interval,
                "pid": os.getpid()
            }
        )

    def start(self) -> None:
        self._last_success = PREDICTION_REQUESTS.labels(status='success')._value.get()
        self._last_error = PREDICTION_REQUESTS.labels(status='error')._value.get()
        self._thread.start()

    def stop(self, timeout: float = DEFAULT_METRICS_STOP_TIMEOUT) -> None:
        """Stop the metrics collection thread.
        
        Args:
            timeout: Maximum time to wait for thread to stop
        """
        if not self._thread.is_alive():
            logger.info("Metrics collector already stopped")
            return
        
        logger.info("Stopping metrics collector...")
        self._stop.set()
        
        try:
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                logger.warning(
                    "Metrics collector thread did not stop within %.1fs timeout",
                    timeout
                )
            else:
                logger.info("Metrics collector stopped successfully")
        except Exception as e:
            logger.error("Error stopping metrics collector: %s", e)
    
    def _cleanup_resources(self) -> None:
        """Clean up metrics collector resources."""
        try:
            # Stop background thread
            self.stop()
            
            # Reset drift monitor
            if hasattr(self, 'drift_monitor') and self.drift_monitor:
                self.drift_monitor.reset()
            
            # Unregister from resource manager
            if hasattr(self, '_resource_id') and self._resource_id:
                global_resource_manager.unregister_resource(self._resource_id, force_cleanup=False)
                self._resource_id = None
            
            logger.info("Metrics collector resources cleaned up")
        except Exception as e:
            logger.error("Error cleaning up metrics collector resources: %s", e)

    def _run(self) -> None:
        """Main monitoring loop with comprehensive error handling."""
        consecutive_errors = 0
        max_consecutive_errors = 5
        handler = ExceptionHandler("MetricsCollector")
        
        while not self._stop.is_set():
            try:
                # Update resource usage with error handling
                safe_execute(
                    self._update_resource_usage,
                    context="Resource usage update",
                    severity=ErrorSeverity.MEDIUM,
                    logger_name="MetricsCollector"
                )
                
                # Update error rate with error handling
                safe_execute(
                    self._update_error_rate,
                    context="Error rate update",
                    severity=ErrorSeverity.LOW,
                    logger_name="MetricsCollector"
                )
                
                # Compute drift score with validation
                drift_score = safe_execute(
                    self.drift_monitor.compute_drift,
                    context="Drift score computation",
                    default_return=0.0,
                    severity=ErrorSeverity.LOW,
                    logger_name="MetricsCollector"
                )
                
                if drift_score is not None and 0 <= drift_score <= 1:
                    DATA_DRIFT_SCORE.set(drift_score)
                elif drift_score is not None:
                    handler.log_error(
                        ValueError(f"Invalid drift score: {drift_score}"),
                        "Drift score validation",
                        ErrorSeverity.LOW
                    )
                
                # Reset error counter on successful iteration
                consecutive_errors = 0
                
            except Exception as e:
                consecutive_errors += 1
                severity = ErrorSeverity.CRITICAL if consecutive_errors >= max_consecutive_errors else ErrorSeverity.HIGH
                
                handler.log_error(
                    e,
                    f"Monitoring loop (attempt {consecutive_errors}/{max_consecutive_errors})",
                    severity
                )
                
                # If too many consecutive errors, add delay to prevent tight error loop
                if consecutive_errors >= max_consecutive_errors:
                    handler.logger.critical(
                        "Too many consecutive monitoring errors (%d), "
                        "adding extended delay to prevent resource exhaustion",
                        consecutive_errors
                    )
                    self._stop.wait(self.interval * 5)  # Extended delay
                    consecutive_errors = 0  # Reset counter
            
            # Wait for next iteration
            self._stop.wait(self.interval)

    def _update_resource_usage(self) -> None:
        """Update resource usage metrics with error handling."""
        try:
            # Check if process is still valid
            if not self._process.is_running():
                logger.warning("Process is no longer running, recreating process monitor")
                self._process = psutil.Process(os.getpid())
            
            # Get CPU usage with timeout protection
            cpu_percent = self._process.cpu_percent(interval=None)
            if cpu_percent is not None and 0 <= cpu_percent <= 100:
                CPU_USAGE.set(cpu_percent)
            else:
                logger.warning("Invalid CPU percentage: %s", cpu_percent)
            
            # Get memory info with error handling
            memory_info = self._process.memory_info()
            if memory_info and memory_info.rss > 0:
                MEMORY_USAGE.set(memory_info.rss)
            else:
                logger.warning("Invalid memory info: %s", memory_info)
                
        except psutil.NoSuchProcess:
            logger.error("Process no longer exists, recreating monitor")
            try:
                self._process = psutil.Process(os.getpid())
            except psutil.NoSuchProcess:
                logger.critical("Cannot recreate process monitor - current process doesn't exist")
        except psutil.ZombieProcess:
            logger.error("Process is a zombie, attempting to recreate monitor")
            try:
                self._process = psutil.Process(os.getpid())
            except (psutil.NoSuchProcess, psutil.ZombieProcess):
                logger.critical("Cannot recreate process monitor - process is zombie or gone")
        except psutil.AccessDenied:
            logger.error("Access denied to process information")
        except Exception as e:
            logger.error("Unexpected error updating resource usage: %s", e)

    def _update_error_rate(self) -> None:
        success = PREDICTION_REQUESTS.labels(status='success')._value.get()
        error = PREDICTION_REQUESTS.labels(status='error')._value.get()
        total = (success - self._last_success) + (error - self._last_error)
        if total > 0:
            ERROR_RATE.set((error - self._last_error) / total)
        self._last_success = success
        self._last_error = error
