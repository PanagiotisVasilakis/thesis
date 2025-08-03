"""Example demonstrating dependency injection usage in the ML service."""

import asyncio
import logging
from typing import Dict, Any, List

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import DI components
from ml_service.app.core.dependency_injection import get_container, inject, autowired
from ml_service.app.core.service_configuration import configure_services
from ml_service.app.core.application_bootstrap import initialize_application
from ml_service.app.core.interfaces import (
    ModelInterface,
    CacheInterface,
    MetricsCollectorInterface,
    LoggerInterface
)
from ml_service.app.services.prediction_service import PredictionService, TrainingService


def basic_di_example():
    """Basic dependency injection example."""
    logger.info("=== Basic DI Example ===")
    
    # Get and configure DI container
    container = get_container()
    configure_services(container)
    
    # Get services through container
    model = container.get('ModelInterface')
    cache = container.get('CacheInterface')
    metrics = container.get('MetricsCollectorInterface')
    logger_service = container.get('LoggerInterface')
    
    logger.info(f"Model service: {type(model).__name__}")
    logger.info(f"Cache service: {type(cache).__name__}")
    logger.info(f"Metrics service: {type(metrics).__name__}")
    logger.info(f"Logger service: {type(logger_service).__name__}")
    
    # Test basic functionality
    test_features = {
        "latitude": 100,
        "longitude": 200,
        "speed": 10,
        "direction_x": 0.7,
        "direction_y": 0.7,
        "heading_change_rate": 0.0,
        "path_curvature": 0.0,
        "velocity": 10.0,
        "acceleration": 0.0,
        "cell_load": 0.5,
        "handover_count": 1,
        "time_since_handover": 60.0,
        "signal_trend": 0.1,
        "environment": 0.0,
        "rsrp_stddev": 5.0,
        "sinr_stddev": 2.0,
        "rsrp_current": -80,
        "sinr_current": 15,
        "rsrq_current": -8,
        "best_rsrp_diff": 5.0,
        "best_sinr_diff": 3.0,
        "best_rsrq_diff": 2.0,
        "altitude": 100.0,
    }
    
    # Make prediction
    result = model.predict(test_features)
    logger.info(f"Prediction result: {result}")
    
    # Test cache
    cache.set("test_key", "test_value", ttl=60.0)
    cached_value = cache.get("test_key")
    logger.info(f"Cache test: {cached_value}")
    
    # Test metrics
    metrics.track_prediction(result["antenna_id"], result["confidence"])
    metrics_data = metrics.get_metrics()
    logger.info(f"Metrics: {len(metrics_data.get('predictions', []))} predictions tracked")


@inject('ModelInterface', 'CacheInterface', 'MetricsCollectorInterface', 'LoggerInterface')
def injected_function_example(model: ModelInterface,
                             cache: CacheInterface,
                             metrics: MetricsCollectorInterface,
                             logger_service: LoggerInterface,
                             custom_param: str = "default"):
    """Example function using @inject decorator."""
    logger.info("=== Injected Function Example ===")
    
    logger_service.info(f"Function called with custom_param: {custom_param}")
    
    # Use injected services
    test_data = {"latitude": 150, "longitude": 250, "speed": 15}
    features = model.extract_features(test_data)
    result = model.predict(features)
    
    # Cache result
    cache_key = f"prediction:{hash(str(test_data))}"
    cache.set(cache_key, result)
    
    # Track metrics
    metrics.track_prediction(result["antenna_id"], result["confidence"])
    
    logger_service.info(f"Prediction: {result['antenna_id']} (confidence: {result['confidence']:.3f})")
    
    return result


@autowired
class ExampleServiceClass:
    """Example service class using @autowired decorator."""
    
    def __init__(self,
                 model: ModelInterface,
                 cache: CacheInterface,
                 metrics: MetricsCollectorInterface,
                 logger_service: LoggerInterface,
                 service_name: str = "ExampleService"):
        """Initialize with injected dependencies."""
        self.model = model
        self.cache = cache
        self.metrics = metrics
        self.logger = logger_service
        self.service_name = service_name
        
        self.logger.info(f"{self.service_name} initialized with DI")
    
    def process_ue_data(self, ue_id: str, ue_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process UE data and make prediction."""
        self.logger.info(f"Processing UE {ue_id}")
        
        # Extract features and predict
        features = self.model.extract_features(ue_data)
        result = self.model.predict(features)
        
        # Cache result
        cache_key = f"{self.service_name}:prediction:{ue_id}"
        self.cache.set(cache_key, result, ttl=30.0)
        
        # Track metrics
        self.metrics.track_prediction(result["antenna_id"], result["confidence"])
        
        self.logger.info(f"UE {ue_id} -> {result['antenna_id']} (confidence: {result['confidence']:.3f})")
        
        return {
            "ue_id": ue_id,
            "predicted_antenna": result["antenna_id"],
            "confidence": result["confidence"],
            "service": self.service_name
        }
    
    def get_service_stats(self) -> Dict[str, Any]:
        """Get service statistics."""
        cache_stats = self.cache.get_stats()
        metrics_data = self.metrics.get_metrics()
        
        return {
            "service_name": self.service_name,
            "cache_stats": cache_stats,
            "predictions_count": len(metrics_data.get("predictions", []))
        }


def prediction_service_example():
    """Example using PredictionService with DI."""
    logger.info("=== PredictionService Example ===")
    
    # Initialize application
    bootstrap = initialize_application()
    container = bootstrap.get_container()
    
    # Create prediction service with DI
    model = container.get('ModelInterface')
    cache = container.get('CacheInterface')
    metrics = container.get('MetricsCollectorInterface')
    logger_service = container.get('LoggerInterface')
    
    prediction_service = PredictionService(model, cache, metrics, logger_service)
    
    # Test single prediction
    ue_data = {
        "latitude": 200,
        "longitude": 300,
        "speed": 20,
        "connected_to": "antenna_2"
    }
    
    result = prediction_service.predict_single("ue_001", ue_data)
    logger.info(f"Single prediction: {result}")
    
    # Test batch prediction
    ue_batch = [
        {"ue_id": "ue_001", "latitude": 100, "longitude": 200, "speed": 10},
        {"ue_id": "ue_002", "latitude": 150, "longitude": 250, "speed": 15},
        {"ue_id": "ue_003", "latitude": 200, "longitude": 300, "speed": 20}
    ]
    
    batch_results = prediction_service.predict_batch(ue_batch)
    logger.info(f"Batch prediction completed: {len(batch_results)} results")
    
    # Get service stats
    stats = prediction_service.get_prediction_stats()
    logger.info(f"Service stats: {stats}")


async def async_example():
    """Example with async operations."""
    logger.info("=== Async Example ===")
    
    # Initialize application
    bootstrap = initialize_application()
    container = bootstrap.get_container()
    
    # Get services
    model = container.get('ModelInterface')
    cache = container.get('CacheInterface')
    metrics = container.get('MetricsCollectorInterface')
    logger_service = container.get('LoggerInterface')
    
    # Create services
    prediction_service = PredictionService(model, cache, metrics, logger_service)
    training_service = TrainingService(model, metrics, logger_service)
    
    # Test async prediction
    ue_data = {
        "latitude": 300,
        "longitude": 400,
        "speed": 25,
        "connected_to": "antenna_3"
    }
    
    async_result = await prediction_service.predict_single_async("ue_async_001", ue_data)
    logger.info(f"Async prediction: {async_result}")
    
    # Test async training
    training_data = [
        {"latitude": 100, "longitude": 200, "optimal_antenna": "antenna_1"},
        {"latitude": 150, "longitude": 250, "optimal_antenna": "antenna_2"},
        {"latitude": 200, "longitude": 300, "optimal_antenna": "antenna_3"}
    ]
    
    training_result = await training_service.train_model_async(training_data, validate_data=False)
    logger.info(f"Async training: {training_result}")


def flask_integration_example():
    """Example of Flask integration with DI."""
    logger.info("=== Flask Integration Example ===")
    
    from ml_service.app.core.application_bootstrap import create_app_with_di
    
    # Create Flask app with DI
    app = create_app_with_di({
        'TESTING': True,
        'NEF_URL': 'http://localhost:8080',
        'LOG_LEVEL': 'DEBUG'
    })
    
    # Test app context
    with app.app_context():
        container = app.di_container
        
        # Get services
        model = container.get('ModelInterface')
        cache = container.get('CacheInterface')
        
        logger.info(f"Flask app DI container has {len(container.get_registered_services())} services")
        
        # Test model in Flask context
        test_data = {"latitude": 400, "longitude": 500, "speed": 30}
        features = model.extract_features(test_data)
        result = model.predict(features)
        
        logger.info(f"Flask context prediction: {result}")


def main():
    """Main example function."""
    logger.info("Starting Dependency Injection Examples")
    
    try:
        # Run examples
        basic_di_example()
        print()
        
        # Configure DI for remaining examples
        bootstrap = initialize_application()
        
        # Function injection example
        result = injected_function_example(custom_param="DI works!")
        print()
        
        # Class injection example
        service = ExampleServiceClass(service_name="DIExampleService")
        ue_result = service.process_ue_data("ue_test_001", {
            "latitude": 123,
            "longitude": 456,
            "speed": 12,
            "connected_to": "antenna_1"
        })
        logger.info(f"Service result: {ue_result}")
        stats = service.get_service_stats()
        logger.info(f"Service stats: {stats}")
        print()
        
        # PredictionService example
        prediction_service_example()
        print()
        
        # Async example
        asyncio.run(async_example())
        print()
        
        # Flask integration example
        flask_integration_example()
        
        logger.info("All examples completed successfully!")
        
    except Exception as exc:
        logger.error(f"Example failed: {exc}")
        raise


if __name__ == "__main__":
    main()