"""Prometheus metrics for ML service."""
from prometheus_client import Counter, Histogram, Gauge
import time

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

class MetricsMiddleware:
    """Middleware to track metrics for API endpoints."""
    
    def __init__(self, app):
        """Initialize the middleware."""
        self.app = app
    
    def __call__(self, environ, start_response):
        """Track metrics for the request."""
        path = environ.get('PATH_INFO', '')
        method = environ.get('REQUEST_METHOD', '')
        
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

# Update in app/__init__.py to integrate the metrics middleware
"""
# Add to create_app function
from app.monitoring.metrics import MetricsMiddleware
app.wsgi_app = MetricsMiddleware(app.wsgi_app)
"""
