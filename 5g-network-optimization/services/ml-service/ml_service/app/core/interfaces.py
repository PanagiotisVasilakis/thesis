"""Core interfaces for dependency injection and loose coupling."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Protocol


class ModelInterface(Protocol):
    """Protocol for ML models."""
    
    def predict(self, features: Dict[str, Any]) -> Dict[str, Any]:
        """Make a prediction based on features."""
        ...
    
    def train(self, training_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Train the model with provided data."""
        ...
    
    def extract_features(self, data: Dict[str, Any], include_neighbors: bool = True) -> Dict[str, Any]:
        """Extract features from raw data."""
        ...
    
    def save(self, path: Optional[str] = None, **kwargs) -> bool:
        """Save the model to disk."""
        ...
    
    def load(self, path: Optional[str] = None) -> bool:
        """Load the model from disk."""
        ...


class AsyncModelInterface(Protocol):
    """Protocol for async ML models."""
    
    async def predict_async(self, features: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """Make async prediction."""
        ...
    
    async def train_async(self, training_data: List[Dict[str, Any]], **kwargs) -> Dict[str, Any]:
        """Train model asynchronously."""
        ...
    
    async def evaluate_async(self, test_data: List[Dict[str, Any]], **kwargs) -> Dict[str, Any]:
        """Evaluate model asynchronously."""
        ...


class ClientInterface(ABC):
    """Abstract interface for external service clients."""
    
    @abstractmethod
    def get_status(self) -> Any:
        """Get service status."""
    
    @abstractmethod
    def close(self) -> None:
        """Close client connections."""


class NEFClientInterface(ClientInterface):
    """Interface for NEF (Network Exposure Function) clients."""
    
    @abstractmethod
    def login(self) -> bool:
        """Authenticate with NEF service."""
    
    @abstractmethod
    def get_ue_movement_state(self) -> Dict[str, Any]:
        """Get UE movement state."""
    
    @abstractmethod
    def get_feature_vector(self, ue_id: str) -> Dict[str, Any]:
        """Get feature vector for UE."""


class AsyncNEFClientInterface(NEFClientInterface):
    """Interface for async NEF clients."""
    
    @abstractmethod
    async def login_async(self) -> bool:
        """Async authentication with NEF service."""
    
    @abstractmethod
    async def get_ue_movement_state_async(self) -> Dict[str, Any]:
        """Get UE movement state asynchronously."""
    
    @abstractmethod
    async def batch_get_feature_vectors(self, ue_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """Get feature vectors for multiple UEs."""


class DataCollectorInterface(ABC):
    """Abstract interface for data collectors."""
    
    @abstractmethod
    def login(self) -> bool:
        """Authenticate with data source."""
    
    @abstractmethod
    def get_ue_movement_state(self) -> Dict[str, Any]:
        """Get current UE movement state."""
    
    @abstractmethod
    async def collect_training_data(self, duration: float, interval: float) -> List[Dict[str, Any]]:
        """Collect training data."""
    
    @abstractmethod
    def cleanup_resources(self) -> None:
        """Clean up collector resources."""


class CacheInterface(ABC):
    """Abstract interface for caching systems."""
    
    @abstractmethod
    def get(self, key: str) -> Any:
        """Get value from cache."""
    
    @abstractmethod
    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        """Set value in cache."""
    
    @abstractmethod
    def delete(self, key: str) -> None:
        """Delete value from cache."""
    
    @abstractmethod
    def clear(self) -> None:
        """Clear all cache entries."""
    
    @abstractmethod
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""


class MetricsCollectorInterface(ABC):
    """Abstract interface for metrics collection."""
    
    @abstractmethod
    def track_prediction(self, antenna_id: str, confidence: float) -> None:
        """Track prediction metrics."""
    
    @abstractmethod
    def track_training(self, duration: float, samples: int, accuracy: Optional[float] = None) -> None:
        """Track training metrics."""
    
    @abstractmethod
    def track_request(self, endpoint: str, status_code: int, duration: float) -> None:
        """Track request metrics."""
    
    @abstractmethod
    def get_metrics(self) -> Dict[str, Any]:
        """Get collected metrics."""


class ValidatorInterface(ABC):
    """Abstract interface for data validation."""
    
    @abstractmethod
    def validate(self, data: Any, context: str = "") -> Any:
        """Validate data and return sanitized version."""
    
    @abstractmethod
    def is_valid(self, data: Any) -> bool:
        """Check if data is valid."""


class ExceptionHandlerInterface(ABC):
    """Abstract interface for exception handling."""
    
    @abstractmethod
    def handle_exception(self, exc: Exception, context: str = "") -> Any:
        """Handle exception and return appropriate response."""
    
    @abstractmethod
    def log_exception(self, exc: Exception, context: str = "") -> None:
        """Log exception details."""


class ResourceManagerInterface(ABC):
    """Abstract interface for resource management."""
    
    @abstractmethod
    def register_resource(self, resource: Any, resource_type: str, **kwargs) -> str:
        """Register a resource for management."""
    
    @abstractmethod
    def unregister_resource(self, resource_id: str, force_cleanup: bool = False) -> None:
        """Unregister a resource."""
    
    @abstractmethod
    def cleanup_all_resources(self) -> None:
        """Clean up all registered resources."""
    
    @abstractmethod
    def get_resource_stats(self) -> Dict[str, Any]:
        """Get resource management statistics."""


class AuthenticationInterface(ABC):
    """Abstract interface for authentication services."""
    
    @abstractmethod
    def authenticate(self, username: str, password: str) -> bool:
        """Authenticate user credentials."""
    
    @abstractmethod
    def create_token(self, username: str) -> str:
        """Create authentication token."""
    
    @abstractmethod
    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Verify authentication token."""


class ConfigurationInterface(ABC):
    """Abstract interface for configuration management."""
    
    @abstractmethod
    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value."""
    
    @abstractmethod
    def set(self, key: str, value: Any) -> None:
        """Set configuration value."""
    
    @abstractmethod
    def get_all(self) -> Dict[str, Any]:
        """Get all configuration values."""
    
    @abstractmethod
    def validate_config(self) -> Dict[str, str]:
        """Validate configuration and return errors."""


class LoggerInterface(ABC):
    """Abstract interface for logging services."""
    
    @abstractmethod
    def info(self, message: str, *args, **kwargs) -> None:
        """Log info message."""
    
    @abstractmethod
    def warning(self, message: str, *args, **kwargs) -> None:
        """Log warning message."""
    
    @abstractmethod
    def error(self, message: str, *args, **kwargs) -> None:
        """Log error message."""
    
    @abstractmethod
    def debug(self, message: str, *args, **kwargs) -> None:
        """Log debug message."""


class EventBusInterface(ABC):
    """Abstract interface for event bus systems."""
    
    @abstractmethod
    def publish(self, event_type: str, data: Dict[str, Any]) -> None:
        """Publish an event."""
    
    @abstractmethod
    def subscribe(self, event_type: str, handler: callable) -> str:
        """Subscribe to an event type."""
    
    @abstractmethod
    def unsubscribe(self, subscription_id: str) -> None:
        """Unsubscribe from events."""


class ServiceFactoryInterface(ABC):
    """Abstract interface for service factories."""
    
    @abstractmethod
    def create_model(self, model_type: str, **kwargs) -> ModelInterface:
        """Create a model instance."""
    
    @abstractmethod
    def create_client(self, client_type: str, **kwargs) -> ClientInterface:
        """Create a client instance."""
    
    @abstractmethod
    def create_cache(self, cache_type: str, **kwargs) -> CacheInterface:
        """Create a cache instance."""
