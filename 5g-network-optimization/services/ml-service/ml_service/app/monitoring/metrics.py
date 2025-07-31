"""Prometheus metrics for ML service."""
from prometheus_client import Counter, Histogram, Gauge
import time
import os
import threading
from typing import Dict, List

import psutil

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

def track_training(duration, num_samples, accuracy=None):
    """Track model training."""
    MODEL_TRAINING_DURATION.observe(duration)
    MODEL_TRAINING_SAMPLES.set(num_samples)
    if accuracy is not None:
        MODEL_TRAINING_ACCURACY.set(accuracy)


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
        self.interval = interval
        self.drift_monitor = drift_monitor or DataDriftMonitor()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._last_success = 0.0
        self._last_error = 0.0
        self._process = psutil.Process(os.getpid())

    def start(self) -> None:
        self._last_success = PREDICTION_REQUESTS.labels(status='success')._value.get()
        self._last_error = PREDICTION_REQUESTS.labels(status='error')._value.get()
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join()

    def _run(self) -> None:
        while not self._stop.is_set():
            self._update_resource_usage()
            self._update_error_rate()
            DATA_DRIFT_SCORE.set(self.drift_monitor.compute_drift())
            self._stop.wait(self.interval)

    def _update_resource_usage(self) -> None:
        CPU_USAGE.set(self._process.cpu_percent(interval=None))
        MEMORY_USAGE.set(self._process.memory_info().rss)

    def _update_error_rate(self) -> None:
        success = PREDICTION_REQUESTS.labels(status='success')._value.get()
        error = PREDICTION_REQUESTS.labels(status='error')._value.get()
        total = (success - self._last_success) + (error - self._last_error)
        if total > 0:
            ERROR_RATE.set((error - self._last_error) / total)
        self._last_success = success
        self._last_error = error
