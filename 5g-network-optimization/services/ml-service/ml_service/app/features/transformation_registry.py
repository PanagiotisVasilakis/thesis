"""Feature transformation registry for dynamic registration and management of transformations."""

import logging
import threading
import inspect
from typing import Any, Dict, List, Optional, Callable, Union, Type, get_type_hints
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
import numpy as np
from datetime import datetime

from ..utils.exception_handler import safe_execute, ModelError
from ..utils.resource_manager import global_resource_manager, ResourceType
from ..config.constants import env_constants

logger = logging.getLogger(__name__)


class TransformationCategory(Enum):
    """Categories of feature transformations."""
    SPATIAL = "spatial"           # Geographic/position transformations
    TEMPORAL = "temporal"         # Time-based transformations
    SIGNAL = "signal"            # RF signal processing
    MOBILITY = "mobility"        # Movement and velocity transformations
    NETWORK = "network"          # Network topology transformations
    STATISTICAL = "statistical"  # Statistical aggregations
    CUSTOM = "custom"            # User-defined transformations


class TransformationPriority(Enum):
    """Priority levels for transformation execution."""
    CRITICAL = 1    # Must execute first (e.g., data validation)
    HIGH = 2        # High priority (e.g., core features)
    NORMAL = 3      # Normal priority (default)
    LOW = 4         # Low priority (e.g., derived features)
    OPTIONAL = 5    # Optional (e.g., experimental features)


@dataclass
class TransformationMetadata:
    """Metadata for feature transformations."""
    name: str
    description: str
    category: TransformationCategory
    priority: TransformationPriority = TransformationPriority.NORMAL
    input_features: List[str] = field(default_factory=list)
    output_features: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    version: str = "1.0.0"
    author: str = "system"
    created_at: datetime = field(default_factory=datetime.now)
    tags: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert metadata to dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category.value,
            "priority": self.priority.value,
            "input_features": self.input_features,
            "output_features": self.output_features,
            "dependencies": self.dependencies,
            "version": self.version,
            "author": self.author,
            "created_at": self.created_at.isoformat(),
            "tags": self.tags
        }


class FeatureTransformation(ABC):
    """Abstract base class for feature transformations."""
    
    def __init__(self, metadata: TransformationMetadata):
        """Initialize transformation with metadata."""
        self.metadata = metadata
        self._validated = False
        self._execution_count = 0
        self._last_execution_time = 0.0
        self._total_execution_time = 0.0
        
    @abstractmethod
    def transform(self, features: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Transform input features to output features.
        
        Args:
            features: Input feature dictionary
            context: Optional context information
            
        Returns:
            Dictionary containing output features
        """
        pass
    
    def validate(self, features: Dict[str, Any]) -> bool:
        """Validate that required input features are present.
        
        Args:
            features: Input feature dictionary
            
        Returns:
            True if validation passes
        """
        if not self.metadata.input_features:
            return True  # No specific requirements
        
        missing_features = []
        for required_feature in self.metadata.input_features:
            if required_feature not in features:
                missing_features.append(required_feature)
        
        if missing_features:
            logger.warning(
                f"Transformation '{self.metadata.name}' missing required features: {missing_features}"
            )
            return False
        
        return True
    
    def execute(self, features: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute transformation with validation and timing.
        
        Args:
            features: Input feature dictionary
            context: Optional context information
            
        Returns:
            Dictionary containing output features
        """
        import time
        start_time = time.time()
        
        try:
            # Validate inputs
            if not self.validate(features):
                logger.warning(f"Transformation '{self.metadata.name}' validation failed")
                return {}
            
            # Execute transformation
            result = self.transform(features, context)
            
            # Update statistics
            execution_time = time.time() - start_time
            self._execution_count += 1
            self._last_execution_time = execution_time
            self._total_execution_time += execution_time
            
            logger.debug(
                f"Transformation '{self.metadata.name}' executed in {execution_time:.4f}s"
            )
            
            return result
            
        except Exception as exc:
            execution_time = time.time() - start_time
            logger.error(
                f"Transformation '{self.metadata.name}' failed after {execution_time:.4f}s: {exc}"
            )
            return {}
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get execution statistics for this transformation."""
        avg_time = (self._total_execution_time / self._execution_count 
                   if self._execution_count > 0 else 0.0)
        
        return {
            "name": self.metadata.name,
            "execution_count": self._execution_count,
            "last_execution_time": self._last_execution_time,
            "total_execution_time": self._total_execution_time,
            "average_execution_time": avg_time,
            "category": self.metadata.category.value,
            "priority": self.metadata.priority.value
        }


class FunctionTransformation(FeatureTransformation):
    """Wrapper for function-based transformations."""
    
    def __init__(self, func: Callable, metadata: TransformationMetadata):
        """Initialize with function and metadata."""
        super().__init__(metadata)
        self.func = func
        
        # Auto-detect function signature if not provided
        if not metadata.input_features:
            self._auto_detect_signature()
    
    def _auto_detect_signature(self) -> None:
        """Auto-detect function signature for input features."""
        try:
            sig = inspect.signature(self.func)
            type_hints = get_type_hints(self.func)
            
            # Extract parameter names (excluding 'features' and 'context')
            param_names = []
            for param_name, param in sig.parameters.items():
                if param_name not in ['features', 'context']:
                    param_names.append(param_name)
            
            if param_names:
                self.metadata.input_features = param_names
                logger.debug(
                    f"Auto-detected input features for {self.metadata.name}: {param_names}"
                )
                
        except Exception as exc:
            logger.warning(f"Could not auto-detect signature for {self.metadata.name}: {exc}")
    
    def transform(self, features: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute the wrapped function."""
        return self.func(features, context)


class TransformationRegistry:
    """Registry for managing feature transformations."""
    
    def __init__(self):
        """Initialize transformation registry."""
        self._transformations: Dict[str, FeatureTransformation] = {}
        self._categories: Dict[TransformationCategory, List[str]] = {}
        self._dependencies: Dict[str, List[str]] = {}
        self._execution_order: List[str] = []
        self._lock = threading.RLock()
        self._statistics = {
            "registrations": 0,
            "executions": 0,
            "failures": 0
        }
        
        # Initialize categories
        for category in TransformationCategory:
            self._categories[category] = []
        
        # Register built-in transformations
        self._register_builtin_transformations()
        
        # Register with resource manager
        self._resource_id = global_resource_manager.register_resource(
            self,
            ResourceType.OTHER,
            cleanup_method=self._cleanup_resources,
            metadata={"component": "TransformationRegistry"}
        )
        
        logger.info("TransformationRegistry initialized")
    
    def register_transformation(self, 
                               name: str, 
                               transformation: Union[FeatureTransformation, Callable],
                               metadata: Optional[TransformationMetadata] = None,
                               **kwargs) -> bool:
        """Register a feature transformation.
        
        Args:
            name: Unique name for the transformation
            transformation: Transformation object or function
            metadata: Transformation metadata (auto-generated if not provided)
            **kwargs: Additional metadata fields
            
        Returns:
            True if registration successful
        """
        with self._lock:
            try:
                # Check if already registered
                if name in self._transformations:
                    logger.warning(f"Transformation '{name}' already registered, replacing")
                
                # Handle different transformation types
                if isinstance(transformation, FeatureTransformation):
                    transform_obj = transformation
                elif callable(transformation):
                    # Create metadata if not provided
                    if metadata is None:
                        metadata = TransformationMetadata(
                            name=name,
                            description=kwargs.get('description', f'Function-based transformation: {name}'),
                            category=TransformationCategory(kwargs.get('category', 'custom')),
                            priority=TransformationPriority(kwargs.get('priority', 3)),
                            input_features=kwargs.get('input_features', []),
                            output_features=kwargs.get('output_features', []),
                            dependencies=kwargs.get('dependencies', []),
                            version=kwargs.get('version', '1.0.0'),
                            author=kwargs.get('author', 'user'),
                            tags=kwargs.get('tags', [])
                        )
                    
                    transform_obj = FunctionTransformation(transformation, metadata)
                else:
                    raise ValueError(f"Invalid transformation type: {type(transformation)}")
                
                # Register transformation
                self._transformations[name] = transform_obj
                
                # Update category index
                category = transform_obj.metadata.category
                if name not in self._categories[category]:
                    self._categories[category].append(name)
                
                # Update dependencies
                self._dependencies[name] = transform_obj.metadata.dependencies
                
                # Rebuild execution order
                self._rebuild_execution_order()
                
                self._statistics["registrations"] += 1
                
                logger.info(f"Registered transformation: {name} ({category.value})")
                return True
                
            except Exception as exc:
                logger.error(f"Failed to register transformation '{name}': {exc}")
                return False
    
    def unregister_transformation(self, name: str) -> bool:
        """Unregister a feature transformation.
        
        Args:
            name: Name of transformation to unregister
            
        Returns:
            True if unregistration successful
        """
        with self._lock:
            if name not in self._transformations:
                logger.warning(f"Transformation '{name}' not found for unregistration")
                return False
            
            try:
                # Get transformation info
                transformation = self._transformations[name]
                category = transformation.metadata.category
                
                # Remove from registry
                del self._transformations[name]
                
                # Remove from category index
                if name in self._categories[category]:
                    self._categories[category].remove(name)
                
                # Remove dependencies
                if name in self._dependencies:
                    del self._dependencies[name]
                
                # Rebuild execution order
                self._rebuild_execution_order()
                
                logger.info(f"Unregistered transformation: {name}")
                return True
                
            except Exception as exc:
                logger.error(f"Failed to unregister transformation '{name}': {exc}")
                return False
    
    def get_transformation(self, name: str) -> Optional[FeatureTransformation]:
        """Get transformation by name.
        
        Args:
            name: Name of transformation
            
        Returns:
            Transformation object or None if not found
        """
        with self._lock:
            return self._transformations.get(name)
    
    def list_transformations(self, 
                           category: Optional[TransformationCategory] = None,
                           priority: Optional[TransformationPriority] = None) -> List[str]:
        """List registered transformations.
        
        Args:
            category: Filter by category
            priority: Filter by priority
            
        Returns:
            List of transformation names
        """
        with self._lock:
            if category is not None:
                names = self._categories[category].copy()
            else:
                names = list(self._transformations.keys())
            
            if priority is not None:
                filtered_names = []
                for name in names:
                    if self._transformations[name].metadata.priority == priority:
                        filtered_names.append(name)
                names = filtered_names
            
            return sorted(names)
    
    def execute_transformation(self, 
                             name: str, 
                             features: Dict[str, Any], 
                             context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute a specific transformation.
        
        Args:
            name: Name of transformation
            features: Input features
            context: Optional context
            
        Returns:
            Output features
        """
        with self._lock:
            if name not in self._transformations:
                logger.error(f"Transformation '{name}' not found")
                return {}
            
            try:
                transformation = self._transformations[name]
                result = transformation.execute(features, context)
                
                self._statistics["executions"] += 1
                return result
                
            except Exception as exc:
                self._statistics["failures"] += 1
                logger.error(f"Failed to execute transformation '{name}': {exc}")
                return {}
    
    def execute_pipeline(self, 
                        features: Dict[str, Any], 
                        context: Optional[Dict[str, Any]] = None,
                        transformations: Optional[List[str]] = None) -> Dict[str, Any]:
        """Execute a pipeline of transformations.
        
        Args:
            features: Input features
            context: Optional context
            transformations: Specific transformations to run (default: all in order)
            
        Returns:
            Final feature dictionary
        """
        with self._lock:
            # Use specified transformations or default execution order
            if transformations is None:
                transformations = self._execution_order.copy()
            
            # Start with input features
            current_features = features.copy()
            execution_log = []
            
            # Execute transformations in order
            for transform_name in transformations:
                if transform_name not in self._transformations:
                    logger.warning(f"Transformation '{transform_name}' not found, skipping")
                    continue
                
                try:
                    transformation = self._transformations[transform_name]
                    
                    # Check dependencies
                    if not self._check_dependencies(transform_name, current_features):
                        logger.warning(f"Dependencies not met for '{transform_name}', skipping")
                        continue
                    
                    # Execute transformation
                    result = transformation.execute(current_features, context)
                    
                    # Merge results
                    current_features.update(result)
                    
                    execution_log.append({
                        "name": transform_name,
                        "status": "success",
                        "output_count": len(result)
                    })
                    
                except Exception as exc:
                    logger.error(f"Pipeline execution failed at '{transform_name}': {exc}")
                    execution_log.append({
                        "name": transform_name,
                        "status": "failed",
                        "error": str(exc)
                    })
            
            # Add execution log to context if provided
            if context is not None:
                context["execution_log"] = execution_log
            
            return current_features
    
    def get_transformation_metadata(self, name: str) -> Optional[Dict[str, Any]]:
        """Get metadata for a transformation.
        
        Args:
            name: Name of transformation
            
        Returns:
            Metadata dictionary or None if not found
        """
        with self._lock:
            if name in self._transformations:
                return self._transformations[name].metadata.to_dict()
            return None
    
    def get_registry_statistics(self) -> Dict[str, Any]:
        """Get registry statistics.
        
        Returns:
            Statistics dictionary
        """
        with self._lock:
            # Get per-transformation statistics
            transform_stats = {}
            for name, transformation in self._transformations.items():
                transform_stats[name] = transformation.get_statistics()
            
            # Get category counts
            category_counts = {}
            for category, names in self._categories.items():
                category_counts[category.value] = len(names)
            
            return {
                "total_transformations": len(self._transformations),
                "category_counts": category_counts,
                "execution_order": self._execution_order.copy(),
                "global_statistics": self._statistics.copy(),
                "transformation_statistics": transform_stats
            }
    
    def _check_dependencies(self, name: str, features: Dict[str, Any]) -> bool:
        """Check if dependencies are satisfied for a transformation.
        
        Args:
            name: Name of transformation
            features: Available features
            
        Returns:
            True if dependencies are satisfied
        """
        dependencies = self._dependencies.get(name, [])
        
        for dep in dependencies:
            if dep not in features:
                return False
        
        return True
    
    def _rebuild_execution_order(self) -> None:
        """Rebuild execution order based on priorities and dependencies."""
        # Sort by priority first, then handle dependencies
        transformations_by_priority = []
        
        for name, transformation in self._transformations.items():
            priority_value = transformation.metadata.priority.value
            transformations_by_priority.append((priority_value, name))
        
        # Sort by priority (lower number = higher priority)
        transformations_by_priority.sort(key=lambda x: x[0])
        
        # Simple topological sort for dependencies
        self._execution_order = []
        remaining = [name for _, name in transformations_by_priority]
        
        while remaining:
            # Find transformations with no unmet dependencies
            ready = []
            for name in remaining:
                dependencies = self._dependencies.get(name, [])
                if all(dep in self._execution_order or dep not in self._transformations 
                       for dep in dependencies):
                    ready.append(name)
            
            if not ready:
                # Circular dependency or unresolvable - add remaining in order
                self._execution_order.extend(remaining)
                break
            
            # Add ready transformations to execution order
            for name in ready:
                self._execution_order.append(name)
                remaining.remove(name)
        
        logger.debug(f"Rebuilt execution order: {self._execution_order}")
    
    def _register_builtin_transformations(self) -> None:
        """Register built-in transformations."""
        # This will be populated with standard transformations
        logger.debug("Built-in transformations registered")
    
    def _cleanup_resources(self) -> None:
        """Clean up registry resources."""
        try:
            with self._lock:
                self._transformations.clear()
                self._categories.clear()
                self._dependencies.clear()
                self._execution_order.clear()
                
                # Unregister from resource manager
                if hasattr(self, '_resource_id') and self._resource_id:
                    global_resource_manager.unregister_resource(self._resource_id, force_cleanup=False)
                
                logger.info("TransformationRegistry resources cleaned up")
                
        except Exception as exc:
            logger.error(f"Error cleaning up TransformationRegistry: {exc}")


# Global registry instance
_global_registry: Optional[TransformationRegistry] = None
_registry_lock = threading.Lock()


def get_transformation_registry() -> TransformationRegistry:
    """Get the global transformation registry."""
    global _global_registry
    
    if _global_registry is None:
        with _registry_lock:
            if _global_registry is None:
                _global_registry = TransformationRegistry()
    
    return _global_registry


# Decorator for easy transformation registration
def register_transformation(name: str, 
                          category: str = "custom",
                          priority: int = 3,
                          description: str = "",
                          input_features: Optional[List[str]] = None,
                          output_features: Optional[List[str]] = None,
                          dependencies: Optional[List[str]] = None,
                          **kwargs):
    """Decorator for registering transformations.
    
    Args:
        name: Unique name for the transformation
        category: Transformation category
        priority: Execution priority (1=highest, 5=lowest)
        description: Human-readable description
        input_features: List of required input features
        output_features: List of produced output features
        dependencies: List of feature dependencies
        **kwargs: Additional metadata fields
    """
    def decorator(func: Callable) -> Callable:
        registry = get_transformation_registry()
        
        metadata = TransformationMetadata(
            name=name,
            description=description or f"Transformation function: {name}",
            category=TransformationCategory(category),
            priority=TransformationPriority(priority),
            input_features=input_features or [],
            output_features=output_features or [],
            dependencies=dependencies or [],
            version=kwargs.get('version', '1.0.0'),
            author=kwargs.get('author', 'user'),
            tags=kwargs.get('tags', [])
        )
        
        registry.register_transformation(name, func, metadata)
        
        return func
    
    return decorator