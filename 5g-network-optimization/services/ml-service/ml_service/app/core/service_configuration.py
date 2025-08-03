"""Service configuration for dependency injection."""

import logging
from typing import Dict, Any, Optional

from .dependency_injection import get_container, DIContainer
from .interfaces import *
from ..models.antenna_selector import AntennaSelector
from ..clients.nef_client import NEFClient
from ..clients.async_nef_client import AsyncNEFClient
from ..data.nef_collector import NEFDataCollector, AsyncNEFDataCollector
from ..utils.optimized_memory_dict import MemoryOptimizedLRU, create_memory_efficient_cache
from ..utils.exception_handler import ExceptionHandler
from ..utils.resource_manager import global_resource_manager
from ..config.constants import env_constants

logger = logging.getLogger(__name__)


class DefaultModelService:
    """Default implementation of ModelInterface using AntennaSelector."""
    
    def __init__(self, model_path: Optional[str] = None, neighbor_count: Optional[int] = None):
        self._antenna_selector = AntennaSelector(model_path, neighbor_count)
    
    def predict(self, features: Dict[str, Any]) -> Dict[str, Any]:
        return self._antenna_selector.predict(features)
    
    def train(self, training_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        return self._antenna_selector.train(training_data)
    
    def extract_features(self, data: Dict[str, Any], include_neighbors: bool = True) -> Dict[str, Any]:
        return self._antenna_selector.extract_features(data, include_neighbors)
    
    def save(self, path: Optional[str] = None, **kwargs) -> bool:
        return self._antenna_selector.save(path, **kwargs)
    
    def load(self, path: Optional[str] = None) -> bool:
        return self._antenna_selector.load(path)
    
    async def predict_async(self, features: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        return await self._antenna_selector.predict_async(features, **kwargs)
    
    async def train_async(self, training_data: List[Dict[str, Any]], **kwargs) -> Dict[str, Any]:
        return await self._antenna_selector.train_async(training_data, **kwargs)
    
    async def evaluate_async(self, test_data: List[Dict[str, Any]], **kwargs) -> Dict[str, Any]:
        return await self._antenna_selector.evaluate_async(test_data, **kwargs)


class DefaultNEFClientService:
    """Default implementation of NEFClientInterface."""
    
    def __init__(self, nef_url: str, username: Optional[str] = None, password: Optional[str] = None):
        self._client = NEFClient(nef_url, username=username, password=password)
    
    def get_status(self) -> Any:
        return self._client.get_status()
    
    def close(self) -> None:
        if hasattr(self._client, 'close'):
            self._client.close()
    
    def login(self) -> bool:
        return self._client.login()
    
    def get_ue_movement_state(self) -> Dict[str, Any]:
        return self._client.get_ue_movement_state()
    
    def get_feature_vector(self, ue_id: str) -> Dict[str, Any]:
        return self._client.get_feature_vector(ue_id)


class DefaultAsyncNEFClientService:
    """Default implementation of AsyncNEFClientInterface."""
    
    def __init__(self, base_url: str, username: Optional[str] = None, password: Optional[str] = None):
        self._client = AsyncNEFClient(
            base_url=base_url,
            username=username,
            password=password,
            timeout=env_constants.NEF_TIMEOUT,
            max_retries=env_constants.NEF_MAX_RETRIES
        )
    
    def get_status(self) -> Any:
        # For async client, we need to handle this differently
        return {"status": "async_client"}
    
    def close(self) -> None:
        # Async close would need to be handled in async context
        pass
    
    async def close_async(self) -> None:
        await self._client.close()
    
    def login(self) -> bool:
        # Sync version not available for async client
        raise NotImplementedError("Use login_async for AsyncNEFClient")
    
    async def login_async(self) -> bool:
        return await self._client.login()
    
    def get_ue_movement_state(self) -> Dict[str, Any]:
        # Sync version not available for async client
        raise NotImplementedError("Use get_ue_movement_state_async for AsyncNEFClient")
    
    async def get_ue_movement_state_async(self) -> Dict[str, Any]:
        return await self._client.get_ue_movement_state()
    
    def get_feature_vector(self, ue_id: str) -> Dict[str, Any]:
        # Sync version not available for async client
        raise NotImplementedError("Use batch_get_feature_vectors for AsyncNEFClient")
    
    async def batch_get_feature_vectors(self, ue_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        return await self._client.batch_get_feature_vectors(ue_ids)


class DefaultDataCollectorService:
    """Default implementation of DataCollectorInterface."""
    
    def __init__(self, nef_url: str, username: Optional[str] = None, password: Optional[str] = None):
        self._collector = NEFDataCollector(nef_url, username, password)
    
    def login(self) -> bool:
        return self._collector.login()
    
    def get_ue_movement_state(self) -> Dict[str, Any]:
        return self._collector.get_ue_movement_state()
    
    async def collect_training_data(self, duration: float, interval: float) -> List[Dict[str, Any]]:
        return await self._collector.collect_training_data(duration, interval)
    
    def cleanup_resources(self) -> None:
        self._collector.cleanup_resources()


class DefaultCacheService:
    """Default implementation of CacheInterface."""
    
    def __init__(self, max_size: int = 1000, ttl_seconds: Optional[float] = None):
        self._cache = create_memory_efficient_cache(max_size=max_size, ttl_seconds=ttl_seconds)
    
    def get(self, key: str) -> Any:
        return self._cache.get(key)
    
    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        self._cache.set(key, value)
    
    def delete(self, key: str) -> None:
        if key in self._cache:
            del self._cache[key]
    
    def clear(self) -> None:
        self._cache.clear()
    
    def get_stats(self) -> Dict[str, Any]:
        return self._cache.get_stats()


class DefaultMetricsCollectorService:
    """Default implementation of MetricsCollectorInterface."""
    
    def __init__(self):
        self._metrics = {
            'predictions': [],
            'training_sessions': [],
            'requests': []
        }
    
    def track_prediction(self, antenna_id: str, confidence: float) -> None:
        self._metrics['predictions'].append({
            'antenna_id': antenna_id,
            'confidence': confidence,
            'timestamp': time.time()
        })
    
    def track_training(self, duration: float, samples: int, accuracy: Optional[float] = None) -> None:
        self._metrics['training_sessions'].append({
            'duration': duration,
            'samples': samples,
            'accuracy': accuracy,
            'timestamp': time.time()
        })
    
    def track_request(self, endpoint: str, status_code: int, duration: float) -> None:
        self._metrics['requests'].append({
            'endpoint': endpoint,
            'status_code': status_code,
            'duration': duration,
            'timestamp': time.time()
        })
    
    def get_metrics(self) -> Dict[str, Any]:
        return self._metrics.copy()


class DefaultExceptionHandlerService:
    """Default implementation of ExceptionHandlerInterface."""
    
    def __init__(self):
        self._exception_handler = ExceptionHandler()
    
    def handle_exception(self, exc: Exception, context: str = "") -> Any:
        return self._exception_handler.handle_exception(exc, context)
    
    def log_exception(self, exc: Exception, context: str = "") -> None:
        self._exception_handler.log_exception(exc, context)


class DefaultConfigurationService:
    """Default implementation of ConfigurationInterface."""
    
    def __init__(self):
        self._config = env_constants.get_all_constants()
    
    def get(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)
    
    def set(self, key: str, value: Any) -> None:
        self._config[key] = value
    
    def get_all(self) -> Dict[str, Any]:
        return self._config.copy()
    
    def validate_config(self) -> Dict[str, str]:
        return env_constants.validate_constants()


class DefaultLoggerService:
    """Default implementation of LoggerInterface."""
    
    def __init__(self, name: str = __name__):
        self._logger = logging.getLogger(name)
    
    def info(self, message: str, *args, **kwargs) -> None:
        self._logger.info(message, *args, **kwargs)
    
    def warning(self, message: str, *args, **kwargs) -> None:
        self._logger.warning(message, *args, **kwargs)
    
    def error(self, message: str, *args, **kwargs) -> None:
        self._logger.error(message, *args, **kwargs)
    
    def debug(self, message: str, *args, **kwargs) -> None:
        self._logger.debug(message, *args, **kwargs)


def configure_services(container: Optional[DIContainer] = None, **config_overrides) -> DIContainer:
    """Configure all services in the DI container."""
    if container is None:
        container = get_container()
    
    # Clear existing services
    container.clear()
    
    # Configuration service (needed first)
    container.register_singleton(
        'ConfigurationInterface',
        DefaultConfigurationService
    )
    
    # Get configuration
    config = container.get('ConfigurationInterface')
    
    # Override configuration if provided
    for key, value in config_overrides.items():
        config.set(key, value)
    
    # Logger service
    container.register_singleton(
        'LoggerInterface',
        DefaultLoggerService,
        name='ml_service'
    )
    
    # Cache service
    container.register_singleton(
        'CacheInterface',
        DefaultCacheService,
        max_size=config.get('FEATURE_CACHE_SIZE', 1000),
        ttl_seconds=config.get('FEATURE_CACHE_TTL', 30.0)
    )
    
    # Model service
    container.register_singleton(
        'ModelInterface',
        DefaultModelService,
        neighbor_count=config.get('NEIGHBOR_COUNT', 3)
    )
    
    # NEF Client service
    container.register_singleton(
        'NEFClientInterface',
        DefaultNEFClientService,
        nef_url=config.get('NEF_URL', 'http://localhost:8080')
    )
    
    # Async NEF Client service
    container.register_singleton(
        'AsyncNEFClientInterface',
        DefaultAsyncNEFClientService,
        base_url=config.get('NEF_URL', 'http://localhost:8080')
    )
    
    # Data collector service
    container.register_singleton(
        'DataCollectorInterface',
        DefaultDataCollectorService,
        nef_url=config.get('NEF_URL', 'http://localhost:8080')
    )
    
    # Metrics collector service
    container.register_singleton(
        'MetricsCollectorInterface',
        DefaultMetricsCollectorService
    )
    
    # Exception handler service
    container.register_singleton(
        'ExceptionHandlerInterface',
        DefaultExceptionHandlerService
    )
    
    # Resource manager service (use existing global instance)
    container.register_instance(
        'ResourceManagerInterface',
        global_resource_manager
    )
    
    logger.info("Services configured successfully")
    logger.debug(f"Registered services: {list(container.get_registered_services().keys())}")
    
    return container


def get_service_factory() -> 'ServiceFactory':
    """Get service factory for creating services on demand."""
    return ServiceFactory()


class ServiceFactory:
    """Factory for creating service instances."""
    
    def __init__(self):
        self._container = get_container()
    
    def create_model(self, model_type: str = 'antenna_selector', **kwargs) -> ModelInterface:
        """Create a model instance."""
        if model_type == 'antenna_selector':
            return DefaultModelService(**kwargs)
        else:
            raise ValueError(f"Unknown model type: {model_type}")
    
    def create_nef_client(self, client_type: str = 'sync', **kwargs) -> NEFClientInterface:
        """Create a NEF client instance."""
        if client_type == 'sync':
            return DefaultNEFClientService(**kwargs)
        elif client_type == 'async':
            return DefaultAsyncNEFClientService(**kwargs)
        else:
            raise ValueError(f"Unknown NEF client type: {client_type}")
    
    def create_cache(self, cache_type: str = 'lru', **kwargs) -> CacheInterface:
        """Create a cache instance."""
        if cache_type == 'lru':
            return DefaultCacheService(**kwargs)
        else:
            raise ValueError(f"Unknown cache type: {cache_type}")
    
    def create_data_collector(self, collector_type: str = 'nef', **kwargs) -> DataCollectorInterface:
        """Create a data collector instance."""
        if collector_type == 'nef':
            return DefaultDataCollectorService(**kwargs)
        else:
            raise ValueError(f"Unknown collector type: {collector_type}")


# Import time for metrics
import time