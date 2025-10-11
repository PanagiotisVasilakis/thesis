"""Dependency injection container for loose coupling."""

import logging
import re
import threading
from typing import Any, Dict, Type, TypeVar, Callable, Optional, Union, get_type_hints
from abc import ABC
from functools import wraps
import inspect

from .interfaces import (
    ModelInterface,
    NEFClientInterface,
    DataCollectorInterface,
    CacheInterface,
    MetricsCollectorInterface,
    ValidatorInterface,
    ExceptionHandlerInterface,
    ResourceManagerInterface,
    AuthenticationInterface,
    ConfigurationInterface,
    LoggerInterface,
    EventBusInterface,
    ServiceFactoryInterface
)

T = TypeVar('T')

logger = logging.getLogger(__name__)


class DIContainer:
    """Dependency injection container for managing service dependencies."""
    
    def __init__(self):
        """Initialize the DI container."""
        self._services: Dict[str, Any] = {}
        self._singletons: Dict[str, Any] = {}
        self._factories: Dict[str, Callable] = {}
        self._interfaces: Dict[str, Type] = {}
        self._dependencies: Dict[str, Dict[str, Any]] = {}
        self._singleton_factories: set[str] = set()
        self._lock = threading.RLock()
        
        # Register core interfaces
        self._register_core_interfaces()
        
    def _register_core_interfaces(self) -> None:
        """Register core interfaces for type checking."""
        self._interfaces.update({
            'ModelInterface': ModelInterface,
            'NEFClientInterface': NEFClientInterface,
            'DataCollectorInterface': DataCollectorInterface,
            'CacheInterface': CacheInterface,
            'MetricsCollectorInterface': MetricsCollectorInterface,
            'ValidatorInterface': ValidatorInterface,
            'ExceptionHandlerInterface': ExceptionHandlerInterface,
            'ResourceManagerInterface': ResourceManagerInterface,
            'AuthenticationInterface': AuthenticationInterface,
            'ConfigurationInterface': ConfigurationInterface,
            'LoggerInterface': LoggerInterface,
            'EventBusInterface': EventBusInterface,
            'ServiceFactoryInterface': ServiceFactoryInterface,
        })
    
    def register_singleton(self, interface: Union[str, Type], implementation: Union[Type, Any], **kwargs) -> None:
        """Register a singleton service."""
        interface_name = self._get_interface_name(interface)
        
        with self._lock:
            if inspect.isclass(implementation):
                # Store factory for lazy initialization
                def _factory() -> Any:
                    instance = implementation(**kwargs)
                    self._singletons[interface_name] = instance
                    return instance

                self._factories[interface_name] = _factory
                self._singleton_factories.add(interface_name)
            else:
                # Store instance directly
                self._singletons[interface_name] = implementation
            
            if kwargs:
                self._dependencies[interface_name] = kwargs
            
            logger.debug(f"Registered singleton: {interface_name}")
    
    def register_transient(self, interface: Union[str, Type], implementation: Type, **kwargs) -> None:
        """Register a transient service (new instance each time)."""
        interface_name = self._get_interface_name(interface)
        
        with self._lock:
            if not inspect.isclass(implementation):
                raise ValueError(f"Transient services must be classes, got {type(implementation)}")
            
            self._factories[interface_name] = lambda: implementation(**kwargs)
            
            if kwargs:
                self._dependencies[interface_name] = kwargs
            
            logger.debug(f"Registered transient: {interface_name}")
    
    def register_instance(self, interface: Union[str, Type], instance: Any) -> None:
        """Register a specific instance."""
        interface_name = self._get_interface_name(interface)
        
        with self._lock:
            self._services[interface_name] = instance
            logger.debug(f"Registered instance: {interface_name}")
    
    def register_factory(self, interface: Union[str, Type], factory: Callable, **kwargs) -> None:
        """Register a factory function."""
        interface_name = self._get_interface_name(interface)
        
        with self._lock:
            if kwargs:
                self._factories[interface_name] = lambda: factory(**kwargs)
                self._dependencies[interface_name] = kwargs
            else:
                self._factories[interface_name] = factory
            
            logger.debug(f"Registered factory: {interface_name}")
    
    def get(self, interface: Union[str, Type]) -> Any:
        """Get service instance by interface."""
        interface_name = self._get_interface_name(interface)
        
        with self._lock:
            # Check if instance is already cached
            if interface_name in self._services:
                return self._services[interface_name]
            
            # Check if singleton exists
            if interface_name in self._singletons:
                return self._singletons[interface_name]
            
            # Check if factory exists for lazy singleton
            if interface_name in self._factories:
                instance = self._factories[interface_name]()
                
                # For singletons, cache the instance
                if (
                    interface_name in self._singleton_factories
                    or interface_name in self._dependencies
                    or interface_name.endswith('Singleton')
                ):
                    self._singletons[interface_name] = instance
                
                return instance
            
            raise ValueError(f"Service not registered: {interface_name}")
    
    def get_optional(self, interface: Union[str, Type]) -> Optional[Any]:
        """Get service instance, returning None if not found."""
        try:
            return self.get(interface)
        except ValueError:
            return None
    
    def is_registered(self, interface: Union[str, Type]) -> bool:
        """Check if interface is registered."""
        interface_name = self._get_interface_name(interface)
        
        with self._lock:
            return (interface_name in self._services or 
                   interface_name in self._singletons or 
                   interface_name in self._factories)
    
    def unregister(self, interface: Union[str, Type]) -> None:
        """Unregister a service."""
        interface_name = self._get_interface_name(interface)
        
        with self._lock:
            self._services.pop(interface_name, None)
            self._singletons.pop(interface_name, None)
            self._factories.pop(interface_name, None)
            self._dependencies.pop(interface_name, None)
            
            logger.debug(f"Unregistered: {interface_name}")
    
    def clear(self) -> None:
        """Clear all registered services."""
        with self._lock:
            self._services.clear()
            self._singletons.clear()
            self._factories.clear()
            self._dependencies.clear()
            
            logger.debug("Cleared all services")
    
    def get_registered_services(self) -> Dict[str, str]:
        """Get list of all registered services."""
        with self._lock:
            services = {}
            
            for name in self._services:
                services[name] = f"instance: {type(self._services[name]).__name__}"
            
            for name in self._singletons:
                services[name] = f"singleton: {type(self._singletons[name]).__name__}"
            
            for name in self._factories:
                services[name] = "factory"
            
            return services
    
    def resolve_dependencies(self, target_class: Type) -> Dict[str, Any]:
        """Resolve dependencies for a class constructor."""
        dependencies = {}
        
        # Get constructor signature
        try:
            sig = inspect.signature(target_class.__init__)
            type_hints = get_type_hints(target_class.__init__)
        except (ValueError, NameError):
            return dependencies
        
        for param_name, param in sig.parameters.items():
            if param_name == 'self':
                continue
            
            # Try to get type hint
            param_type = type_hints.get(param_name)
            if param_type and self.is_registered(param_type):
                dependencies[param_name] = self.get(param_type)
            elif param.annotation and param.annotation != inspect.Parameter.empty:
                if self.is_registered(param.annotation):
                    dependencies[param_name] = self.get(param.annotation)
        
        return dependencies
    
    def create_with_dependencies(self, target_class: Type, **kwargs) -> Any:
        """Create instance with auto-resolved dependencies."""
        dependencies = self.resolve_dependencies(target_class)
        dependencies.update(kwargs)  # Override with explicit kwargs
        
        return target_class(**dependencies)
    
    def get_interface_class(self, interface: Union[str, Type]) -> Optional[Type]:
        """Return the concrete class registered for an interface name, if any."""
        interface_name = self._get_interface_name(interface)
        return self._interfaces.get(interface_name)

    def _get_interface_name(self, interface: Union[str, Type]) -> str:
        """Get standardized interface name."""
        if isinstance(interface, str):
            return interface
        elif hasattr(interface, '__name__'):
            return interface.__name__
        else:
            return str(interface)


# Global DI container instance
_container: Optional[DIContainer] = None
_container_lock = threading.Lock()


def get_container() -> DIContainer:
    """Get the global DI container instance."""
    global _container
    
    if _container is None:
        with _container_lock:
            if _container is None:
                _container = DIContainer()
    
    return _container


def inject(*dependencies) -> Callable:
    """Decorator for automatic dependency injection."""
    def decorator(func: Callable) -> Callable:
        sig = inspect.signature(func)
        try:
            type_hints = get_type_hints(func)
        except Exception:  # pragma: no cover - defensive; shouldn't occur in tests
            type_hints = {}

        annotation_map: Dict[Any, str] = {}
        for param_name, annotation in type_hints.items():
            annotation_map[annotation] = param_name
            if isinstance(annotation, str):
                annotation_map.setdefault(annotation, param_name)
            elif hasattr(annotation, '__name__'):
                annotation_map.setdefault(annotation.__name__, param_name)

        def _camel_to_snake(name: str) -> str:
            segments = re.findall(
                r"[A-Z]+(?=[A-Z][a-z]|[0-9]|$)|[A-Z]?[a-z]+|[0-9]+",
                name,
            )
            return "_".join(segment.lower() for segment in segments if segment)

        @wraps(func)
        def wrapper(*args, **kwargs):
            container = get_container()
            
            # Resolve dependencies
            for dep in dependencies:
                if isinstance(dep, str):
                    dep_type = dep
                    dep_name_hint = dep
                elif hasattr(dep, '__name__'):
                    dep_type = dep
                    dep_name_hint = dep.__name__
                else:
                    continue

                param_name = None

                # Prefer parameter annotated with dependency type
                interface_class = container.get_interface_class(dep_type)
                if interface_class and interface_class in annotation_map:
                    param_name = annotation_map[interface_class]
                elif dep_type in annotation_map:
                    param_name = annotation_map[dep_type]
                else:
                    normalized = dep_name_hint.replace('Interface', '')
                    candidates = [
                        normalized,
                        _camel_to_snake(normalized),
                        normalized.lower(),
                        _camel_to_snake(dep_name_hint),
                    ]
                    for candidate in candidates:
                        if candidate in sig.parameters:
                            param_name = candidate
                            break

                if not param_name:
                    continue

                if param_name not in kwargs and container.is_registered(dep_type):
                    kwargs[param_name] = container.get(dep_type)
            
            return func(*args, **kwargs)
        
        return wrapper
    return decorator


def autowired(target_class: Type) -> Type:
    """Class decorator for automatic dependency injection."""
    original_init = target_class.__init__
    
    @wraps(original_init)
    def new_init(self, *args, **kwargs):
        container = get_container()
        dependencies = container.resolve_dependencies(target_class)
        
        try:
            bound = inspect.signature(original_init).bind_partial(self, *args, **kwargs)
            provided_params = set(bound.arguments.keys()) - {"self"}
        except TypeError:
            provided_params = set()

        for provided in provided_params:
            dependencies.pop(provided, None)

        # Merge resolved dependencies with provided kwargs
        final_kwargs = {**dependencies, **kwargs}
        original_init(self, *args, **final_kwargs)
    
    target_class.__init__ = new_init
    return target_class


class ServiceLocator:
    """Service locator pattern for accessing DI container."""
    
    @staticmethod
    def get_model() -> ModelInterface:
        """Get the model service."""
        return get_container().get('ModelInterface')
    
    @staticmethod
    def get_nef_client() -> NEFClientInterface:
        """Get the NEF client service."""
        return get_container().get('NEFClientInterface')
    
    @staticmethod
    def get_data_collector() -> DataCollectorInterface:
        """Get the data collector service."""
        return get_container().get('DataCollectorInterface')
    
    @staticmethod
    def get_cache() -> CacheInterface:
        """Get the cache service."""
        return get_container().get('CacheInterface')
    
    @staticmethod
    def get_metrics_collector() -> MetricsCollectorInterface:
        """Get the metrics collector service."""
        return get_container().get('MetricsCollectorInterface')
    
    @staticmethod
    def get_validator() -> ValidatorInterface:
        """Get the validator service."""
        return get_container().get('ValidatorInterface')
    
    @staticmethod
    def get_exception_handler() -> ExceptionHandlerInterface:
        """Get the exception handler service."""
        return get_container().get('ExceptionHandlerInterface')
    
    @staticmethod
    def get_resource_manager() -> ResourceManagerInterface:
        """Get the resource manager service."""
        return get_container().get('ResourceManagerInterface')
    
    @staticmethod
    def get_authentication() -> AuthenticationInterface:
        """Get the authentication service."""
        return get_container().get('AuthenticationInterface')
    
    @staticmethod
    def get_configuration() -> ConfigurationInterface:
        """Get the configuration service."""
        return get_container().get('ConfigurationInterface')
    
    @staticmethod
    def get_logger() -> LoggerInterface:
        """Get the logger service."""
        return get_container().get('LoggerInterface')


def configure_container() -> DIContainer:
    """Configure the DI container with default services."""
    container = get_container()
    
    # This would be called during application startup
    # to register all services
    logger.info("DI container configured")
    
    return container


# Convenience functions for common patterns
def singleton(interface: Union[str, Type]):
    """Decorator to register a class as a singleton service."""
    def decorator(cls: Type) -> Type:
        container = get_container()
        container.register_singleton(interface, cls)
        return cls
    return decorator


def transient(interface: Union[str, Type]):
    """Decorator to register a class as a transient service."""
    def decorator(cls: Type) -> Type:
        container = get_container()
        container.register_transient(interface, cls)
        return cls
    return decorator


def factory_method(interface: Union[str, Type], **kwargs):
    """Decorator to register a function as a factory."""
    def decorator(func: Callable) -> Callable:
        container = get_container()
        container.register_factory(interface, func, **kwargs)
        return func
    return decorator