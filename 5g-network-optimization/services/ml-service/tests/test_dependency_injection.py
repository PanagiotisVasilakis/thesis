"""Tests for dependency injection functionality."""

import pytest
from unittest.mock import MagicMock, patch
from typing import Dict, Any, List, Optional

from ml_service.app.core.dependency_injection import (
    DIContainer,
    get_container,
    inject,
    autowired,
    ServiceLocator,
    singleton,
    transient,
    factory_method
)
from ml_service.app.core.interfaces import (
    ModelInterface,
    NEFClientInterface,
    CacheInterface,
    MetricsCollectorInterface,
    LoggerInterface
)
from ml_service.app.core.service_configuration import (
    configure_services,
    DefaultModelService,
    DefaultCacheService,
    ServiceFactory
)
from ml_service.app.services.prediction_service import (
    PredictionService,
    TrainingService,
    create_prediction_service,
    create_training_service
)


class MockModel:
    """Mock model for testing."""
    
    def predict(self, features: Dict[str, Any]) -> Dict[str, Any]:
        return {"antenna_id": "antenna_1", "confidence": 0.8}
    
    def train(self, training_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        return {"samples": len(training_data), "accuracy": 0.95}
    
    def extract_features(self, data: Dict[str, Any], include_neighbors: bool = True) -> Dict[str, Any]:
        return {"latitude": 100, "longitude": 200, "speed": 10}
    
    def save(self, path: Optional[str] = None, **kwargs) -> bool:
        return True
    
    def load(self, path: Optional[str] = None) -> bool:
        return True
    
    async def predict_async(self, features: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        return {"antenna_id": "antenna_1", "confidence": 0.8}
    
    async def train_async(self, training_data: List[Dict[str, Any]], **kwargs) -> Dict[str, Any]:
        return {"samples": len(training_data), "accuracy": 0.95}
    
    async def evaluate_async(self, test_data: List[Dict[str, Any]], **kwargs) -> Dict[str, Any]:
        return {"accuracy": 0.93}


class MockCache:
    """Mock cache for testing."""
    
    def __init__(self):
        self._data = {}
        self._stats = {"hits": 0, "misses": 0}
    
    def get(self, key: str) -> Any:
        if key in self._data:
            self._stats["hits"] += 1
            return self._data[key]
        self._stats["misses"] += 1
        return None
    
    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        self._data[key] = value
    
    def delete(self, key: str) -> None:
        self._data.pop(key, None)
    
    def clear(self) -> None:
        self._data.clear()
    
    def get_stats(self) -> Dict[str, Any]:
        return self._stats.copy()


class MockMetrics:
    """Mock metrics collector for testing."""
    
    def __init__(self):
        self._predictions = []
        self._training_sessions = []
        self._requests = []
    
    def track_prediction(self, antenna_id: str, confidence: float) -> None:
        self._predictions.append({"antenna_id": antenna_id, "confidence": confidence})
    
    def track_training(self, duration: float, samples: int, accuracy: Optional[float] = None) -> None:
        self._training_sessions.append({
            "duration": duration,
            "samples": samples,
            "accuracy": accuracy
        })
    
    def track_request(self, endpoint: str, status_code: int, duration: float) -> None:
        self._requests.append({
            "endpoint": endpoint,
            "status_code": status_code,
            "duration": duration
        })
    
    def get_metrics(self) -> Dict[str, Any]:
        return {
            "predictions": self._predictions,
            "training_sessions": self._training_sessions,
            "requests": self._requests
        }


class MockLogger:
    """Mock logger for testing."""
    
    def __init__(self):
        self._logs = []
    
    def info(self, message: str, *args, **kwargs) -> None:
        self._logs.append(("INFO", message % args if args else message))
    
    def warning(self, message: str, *args, **kwargs) -> None:
        self._logs.append(("WARNING", message % args if args else message))
    
    def error(self, message: str, *args, **kwargs) -> None:
        self._logs.append(("ERROR", message % args if args else message))
    
    def debug(self, message: str, *args, **kwargs) -> None:
        self._logs.append(("DEBUG", message % args if args else message))
    
    def get_logs(self) -> List[tuple]:
        return self._logs.copy()


class TestDIContainer:
    """Test cases for DIContainer."""
    
    def test_container_creation(self):
        """Test DI container creation."""
        container = DIContainer()
        assert container is not None
    
    def test_register_singleton(self):
        """Test singleton registration."""
        container = DIContainer()
        
        # Register singleton
        container.register_singleton('TestService', MockModel)
        
        # Get instances
        instance1 = container.get('TestService')
        instance2 = container.get('TestService')
        
        # Should be same instance
        assert instance1 is instance2
        assert isinstance(instance1, MockModel)
    
    def test_register_transient(self):
        """Test transient registration."""
        container = DIContainer()
        
        # Register transient
        container.register_transient('TestService', MockModel)
        
        # Get instances
        instance1 = container.get('TestService')
        instance2 = container.get('TestService')
        
        # Should be different instances
        assert instance1 is not instance2
        assert isinstance(instance1, MockModel)
        assert isinstance(instance2, MockModel)
    
    def test_register_instance(self):
        """Test instance registration."""
        container = DIContainer()
        mock_instance = MockModel()
        
        # Register instance
        container.register_instance('TestService', mock_instance)
        
        # Get instance
        retrieved = container.get('TestService')
        
        # Should be same instance
        assert retrieved is mock_instance
    
    def test_register_factory(self):
        """Test factory registration."""
        container = DIContainer()
        
        def model_factory():
            return MockModel()
        
        # Register factory
        container.register_factory('TestService', model_factory)
        
        # Get instances
        instance1 = container.get('TestService')
        instance2 = container.get('TestService')
        
        # Should be different instances from factory
        assert instance1 is not instance2
        assert isinstance(instance1, MockModel)
        assert isinstance(instance2, MockModel)
    
    def test_service_not_found(self):
        """Test service not found error."""
        container = DIContainer()
        
        with pytest.raises(ValueError, match="Service not registered"):
            container.get('NonExistentService')
    
    def test_get_optional(self):
        """Test optional service retrieval."""
        container = DIContainer()
        
        # Should return None for non-existent service
        result = container.get_optional('NonExistentService')
        assert result is None
        
        # Should return service if it exists
        container.register_instance('TestService', MockModel())
        result = container.get_optional('TestService')
        assert result is not None
    
    def test_is_registered(self):
        """Test service registration check."""
        container = DIContainer()
        
        assert not container.is_registered('TestService')
        
        container.register_instance('TestService', MockModel())
        assert container.is_registered('TestService')
    
    def test_unregister(self):
        """Test service unregistration."""
        container = DIContainer()
        container.register_instance('TestService', MockModel())
        
        assert container.is_registered('TestService')
        
        container.unregister('TestService')
        assert not container.is_registered('TestService')
    
    def test_clear(self):
        """Test clearing all services."""
        container = DIContainer()
        
        container.register_instance('Service1', MockModel())
        container.register_instance('Service2', MockCache())
        
        assert container.is_registered('Service1')
        assert container.is_registered('Service2')
        
        container.clear()
        
        assert not container.is_registered('Service1')
        assert not container.is_registered('Service2')
    
    def test_get_registered_services(self):
        """Test getting list of registered services."""
        container = DIContainer()
        
        container.register_instance('Service1', MockModel())
        container.register_singleton('Service2', MockCache)
        
        services = container.get_registered_services()
        
        assert 'Service1' in services
        assert 'Service2' in services
        assert 'instance:' in services['Service1']


class TestDependencyInjection:
    """Test cases for dependency injection decorators."""
    
    def test_inject_decorator(self):
        """Test inject decorator."""
        container = DIContainer()
        container.register_instance('ModelInterface', MockModel())
        container.register_instance('CacheInterface', MockCache())
        
        @inject('ModelInterface', 'CacheInterface')
        def test_function(model, cache, other_param=None):
            return model, cache, other_param
        
        # Call with DI container patch
        with patch('ml_service.app.core.dependency_injection.get_container', return_value=container):
            result = test_function(other_param="test")
        
        model, cache, other_param = result
        assert isinstance(model, MockModel)
        assert isinstance(cache, MockCache)
        assert other_param == "test"
    
    def test_autowired_decorator(self):
        """Test autowired decorator."""
        container = DIContainer()
        container.register_instance('ModelInterface', MockModel())
        container.register_instance('CacheInterface', MockCache())
        
        @autowired
        class TestClass:
            def __init__(self, model: ModelInterface, cache: CacheInterface, value: str = "default"):
                self.model = model
                self.cache = cache
                self.value = value
        
        # Create instance with DI container patch
        with patch('ml_service.app.core.dependency_injection.get_container', return_value=container):
            instance = TestClass(value="test")
        
        assert isinstance(instance.model, MockModel)
        assert isinstance(instance.cache, MockCache)
        assert instance.value == "test"


class TestServiceConfiguration:
    """Test cases for service configuration."""
    
    def test_configure_services(self):
        """Test service configuration."""
        container = DIContainer()
        
        # Configure services
        configure_services(container)
        
        # Check that core services are registered
        assert container.is_registered('ConfigurationInterface')
        assert container.is_registered('LoggerInterface')
        assert container.is_registered('CacheInterface')
        assert container.is_registered('ModelInterface')
    
    def test_service_factory(self):
        """Test service factory."""
        factory = ServiceFactory()
        
        # Test model creation
        model = factory.create_model('antenna_selector')
        assert model is not None
        
        # Test cache creation
        cache = factory.create_cache('lru', max_size=100)
        assert cache is not None
        
        # Test unknown service type
        with pytest.raises(ValueError):
            factory.create_model('unknown_type')


class TestPredictionService:
    """Test cases for PredictionService with DI."""
    
    def test_prediction_service_creation(self):
        """Test prediction service creation with DI."""
        model = MockModel()
        cache = MockCache()
        metrics = MockMetrics()
        logger = MockLogger()
        
        service = PredictionService(model, cache, metrics, logger)
        
        assert service is not None
        assert service._model is model
        assert service._cache is cache
    
    def test_single_prediction(self):
        """Test single prediction."""
        model = MockModel()
        cache = MockCache()
        metrics = MockMetrics()
        logger = MockLogger()
        
        service = PredictionService(model, cache, metrics, logger)
        
        ue_data = {
            "latitude": 100,
            "longitude": 200,
            "speed": 10,
            "connected_to": "antenna_1"
        }
        
        result = service.predict_single("ue_001", ue_data)
        
        assert result["ue_id"] == "ue_001"
        assert result["predicted_antenna"] == "antenna_1"
        assert result["confidence"] == 0.8
        assert result["cached"] is False
    
    def test_prediction_caching(self):
        """Test prediction caching."""
        model = MockModel()
        cache = MockCache()
        metrics = MockMetrics()
        logger = MockLogger()
        
        service = PredictionService(model, cache, metrics, logger)
        
        ue_data = {
            "latitude": 100,
            "longitude": 200,
            "speed": 10,
            "connected_to": "antenna_1"
        }
        
        # First prediction - cache miss
        result1 = service.predict_single("ue_001", ue_data, use_cache=True)
        assert result1["cached"] is False
        
        # Second prediction - cache hit
        result2 = service.predict_single("ue_001", ue_data, use_cache=True)
        assert result2["cached"] is True
        
        # Check cache stats
        stats = service.get_prediction_stats()
        assert stats["cache_hits"] == 1
        assert stats["cache_misses"] == 1
    
    @pytest.mark.asyncio
    async def test_async_prediction(self):
        """Test async prediction."""
        model = MockModel()
        cache = MockCache()
        metrics = MockMetrics()
        logger = MockLogger()
        
        service = PredictionService(model, cache, metrics, logger)
        
        ue_data = {
            "latitude": 100,
            "longitude": 200,
            "speed": 10,
            "connected_to": "antenna_1"
        }
        
        result = await service.predict_single_async("ue_001", ue_data)
        
        assert result["ue_id"] == "ue_001"
        assert result["predicted_antenna"] == "antenna_1"
        assert result["confidence"] == 0.8
        assert result["async"] is True
    
    def test_batch_prediction(self):
        """Test batch prediction."""
        model = MockModel()
        cache = MockCache()
        metrics = MockMetrics()
        logger = MockLogger()
        
        service = PredictionService(model, cache, metrics, logger)
        
        ue_data_batch = [
            {"ue_id": "ue_001", "latitude": 100, "longitude": 200},
            {"ue_id": "ue_002", "latitude": 150, "longitude": 250},
            {"ue_id": "ue_003", "latitude": 200, "longitude": 300}
        ]
        
        results = service.predict_batch(ue_data_batch)
        
        assert len(results) == 3
        for result in results:
            assert "ue_id" in result
            assert "predicted_antenna" in result
            assert "confidence" in result


class TestTrainingService:
    """Test cases for TrainingService with DI."""
    
    def test_training_service_creation(self):
        """Test training service creation with DI."""
        model = MockModel()
        metrics = MockMetrics()
        logger = MockLogger()
        
        service = TrainingService(model, metrics, logger)
        
        assert service is not None
        assert service._model is model
        assert service._metrics is metrics
    
    def test_model_training(self):
        """Test model training."""
        model = MockModel()
        metrics = MockMetrics()
        logger = MockLogger()
        
        service = TrainingService(model, metrics, logger)
        
        training_data = [
            {"latitude": 100, "longitude": 200, "optimal_antenna": "antenna_1"},
            {"latitude": 150, "longitude": 250, "optimal_antenna": "antenna_2"}
        ]
        
        result = service.train_model(training_data, validate_data=False)
        
        assert result["samples"] == 2
        assert result["accuracy"] == 0.95
        assert "training_duration" in result
        assert "training_session" in result
    
    @pytest.mark.asyncio
    async def test_async_training(self):
        """Test async model training."""
        model = MockModel()
        metrics = MockMetrics()
        logger = MockLogger()
        
        service = TrainingService(model, metrics, logger)
        
        training_data = [
            {"latitude": 100, "longitude": 200, "optimal_antenna": "antenna_1"},
            {"latitude": 150, "longitude": 250, "optimal_antenna": "antenna_2"}
        ]
        
        result = await service.train_model_async(training_data, validate_data=False)
        
        assert result["samples"] == 2
        assert result["accuracy"] == 0.95
        assert result["async"] is True
        assert "training_duration" in result


class TestServiceFactoryFunctions:
    """Test cases for service factory functions."""
    
    def test_create_prediction_service(self):
        """Test prediction service factory function."""
        container = DIContainer()
        container.register_instance('ModelInterface', MockModel())
        container.register_instance('CacheInterface', MockCache())
        container.register_instance('MetricsCollectorInterface', MockMetrics())
        container.register_instance('LoggerInterface', MockLogger())
        
        with patch('ml_service.app.core.dependency_injection.get_container', return_value=container):
            service = create_prediction_service()
        
        assert isinstance(service, PredictionService)
    
    def test_create_training_service(self):
        """Test training service factory function."""
        container = DIContainer()
        container.register_instance('ModelInterface', MockModel())
        container.register_instance('MetricsCollectorInterface', MockMetrics())
        container.register_instance('LoggerInterface', MockLogger())
        
        with patch('ml_service.app.core.dependency_injection.get_container', return_value=container):
            service = create_training_service()
        
        assert isinstance(service, TrainingService)


if __name__ == "__main__":
    pytest.main([__file__])