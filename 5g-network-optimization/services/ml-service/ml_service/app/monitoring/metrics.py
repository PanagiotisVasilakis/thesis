"""Prometheus metrics for ML service."""
from prometheus_client import Counter, Histogram, Gauge
import json
import logging
import time
import os
import threading
from typing import Dict, List

import psutil

logger = logging.getLogger(__name__)

# Track prediction requests
PREDICTION_REQUESTS = Counter(
    'ml_prediction_requests_total',
    'Total number of prediction requests',
    ['status']
)

# Track prediction latency
PREDICTION_LATENCY = Histogram(
    'ml_prediction_latency_seconds',
    'Latency of antenna selection predictions',
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]
)

# Track prediction outcomes
ANTENNA_PREDICTIONS = Counter(
    'ml_antenna_predictions_total',
    'Antenna selection predictions',
    ['antenna_id']
)

# Track prediction confidence
PREDICTION_CONFIDENCE = Gauge(
    'ml_prediction_confidence_avg',
    'Average confidence of antenna predictions',
    ['antenna_id']
)

# Track model training
MODEL_TRAINING_DURATION = Histogram(
    'ml_model_training_duration_seconds',
    'Duration of model training',
    buckets=[0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0]
)

MODEL_TRAINING_SAMPLES = Gauge(
    'ml_model_training_samples',
    'Number of samples used for model training'
)

MODEL_TRAINING_ACCURACY = Gauge(
    'ml_model_training_accuracy',
    'Accuracy of trained model'
)

# Track latest feature importance values
FEATURE_IMPORTANCE = Gauge(
    'ml_feature_importance',
    'Latest feature importance score',
    ['feature']
)

# --- Operational and Drift Metrics ---

# Data drift indicator updated by ``MetricsCollector``
DATA_DRIFT_SCORE = Gauge(
    'ml_data_drift_score',
    'Average change between consecutive feature distributions'
)

# Rate of failed prediction requests over the last collection interval
ERROR_RATE = Gauge(
    'ml_prediction_error_rate',
    'Fraction of prediction requests resulting in an error'
)

# Resource usage of the ML service process
CPU_USAGE = Gauge(
    'ml_cpu_usage_percent',
    'CPU utilisation of the ML service process'
)

MEMORY_USAGE = Gauge(
    'ml_memory_usage_bytes',
    'Resident memory usage of the ML service process in bytes'
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

    def __init__(self, window_size: int = 100) -> None:
        self.window_size = window_size
        self._current: List[Dict[str, float]] = []
        self._previous: List[Dict[str, float]] = []
        self._lock = threading.Lock()

    def update(self, features: Dict[str, float]) -> None:
        """Add feature vector from a prediction request."""
        numeric = {k: v for k, v in features.items() if isinstance(v, (int, float))}
        if not numeric:
            return
        with self._lock:
            self._current.append(numeric)
            if len(self._current) > self.window_size:
                self._current.pop(0)

    def _mean(self, samples: List[Dict[str, float]]) -> Dict[str, float]:
        totals: Dict[str, float] = {}
        counts: Dict[str, int] = {}
        for sample in samples:
            for k, v in sample.items():
                totals[k] = totals.get(k, 0.0) + v
                counts[k] = counts.get(k, 0) + 1
        return {k: totals[k] / counts[k] for k in totals}

    def compute_drift(self) -> float:
        """Return average absolute change between the latest windows."""
        with self._lock:
            if len(self._current) < self.window_size:
                return 0.0
            if not self._previous:
                self._previous = list(self._current)
                self._current.clear()
                return 0.0

            prev_means = self._mean(self._previous)
            curr_means = self._mean(self._current)
            keys = set(prev_means).intersection(curr_means)
            if not keys:
                self._previous = list(self._current)
                self._current.clear()
                return 0.0

            diff = sum(abs(curr_means[k] - prev_means[k]) for k in keys) / len(keys)
            self._previous = list(self._current)
            self._current.clear()
            return diff


class MetricsCollector:
    """Background thread updating operational metrics."""

    def __init__(self, interval: float = 10.0, drift_monitor: DataDriftMonitor | None = None) -> None:
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

    def start(self) -> None:
        self._last_success = PREDICTION_REQUESTS.labels(status='success')._value.get()
        self._last_error = PREDICTION_REQUESTS.labels(status='error')._value.get()
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
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

    def _run(self) -> None:
        """Main monitoring loop with comprehensive error handling."""
        consecutive_errors = 0
        max_consecutive_errors = 5
        
        while not self._stop.is_set():
            try:
                self._update_resource_usage()
                
                try:
                    self._update_error_rate()
                except Exception as e:
                    logger.warning("Error updating error rate metrics: %s", e)
                
                try:
                    drift_score = self.drift_monitor.compute_drift()
                    if 0 <= drift_score <= 1:  # Validate drift score
                        DATA_DRIFT_SCORE.set(drift_score)
                    else:
                        logger.warning("Invalid drift score: %s", drift_score)
                except Exception as e:
                    logger.warning("Error computing drift score: %s", e)
                
                # Reset error counter on successful iteration
                consecutive_errors = 0
                
            except Exception as e:
                consecutive_errors += 1
                logger.error(
                    "Error in monitoring loop (attempt %d/%d): %s",
                    consecutive_errors, max_consecutive_errors, e
                )
                
                # If too many consecutive errors, add delay to prevent tight error loop
                if consecutive_errors >= max_consecutive_errors:
                    logger.critical(
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
