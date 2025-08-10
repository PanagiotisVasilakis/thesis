"""Unified feature extraction pipeline using the transformation registry."""

import logging
import time
from typing import Dict, Any, List, Optional, Set, Tuple

from .transformation_registry import (
    get_transformation_registry,
    TransformationRegistry,
    TransformationCategory,
    TransformationPriority
)
from .builtin_transformations import register_all_builtin_transformations
from ..utils.exception_handler import safe_execute, ModelError
from ..config.constants import env_constants

logger = logging.getLogger(__name__)


class FeatureExtractionPipeline:
    """Unified feature extraction pipeline using transformation registry."""
    
    def __init__(self, 
                 registry: Optional[TransformationRegistry] = None,
                 enable_caching: bool = True,
                 cache_ttl: float = 30.0,
                 enable_validation: bool = True):
        """Initialize feature extraction pipeline.
        
        Args:
            registry: Transformation registry (uses global if None)
            enable_caching: Whether to enable result caching
            cache_ttl: Cache time-to-live in seconds
            enable_validation: Whether to validate transformation outputs
        """
        self.registry = registry or get_transformation_registry()
        self.enable_caching = enable_caching
        self.cache_ttl = cache_ttl
        self.enable_validation = enable_validation
        
        # Pipeline configuration
        self._enabled_transformations: Set[str] = set()
        self._disabled_transformations: Set[str] = set()
        self._custom_execution_order: Optional[List[str]] = None
        self._category_filters: Set[TransformationCategory] = set()
        self._priority_filters: Set[TransformationPriority] = set()
        
        # Statistics
        self._execution_stats = {
            "total_executions": 0,
            "total_features_produced": 0,
            "total_execution_time": 0.0,
            "cache_hits": 0,
            "cache_misses": 0,
            "validation_failures": 0
        }
        
        # Feature cache
        self._feature_cache: Dict[str, Tuple[Dict[str, Any], float]] = {}
        
        # Initialize with built-in transformations
        self._ensure_builtin_transformations()
        
        logger.info("FeatureExtractionPipeline initialized")
    
    def _ensure_builtin_transformations(self) -> None:
        """Ensure built-in transformations are registered."""
        try:
            register_all_builtin_transformations()
            logger.debug("Built-in transformations ensured")
        except Exception as exc:
            logger.warning(f"Failed to register built-in transformations: {exc}")
    
    def configure_pipeline(self,
                          enabled_transformations: Optional[List[str]] = None,
                          disabled_transformations: Optional[List[str]] = None,
                          execution_order: Optional[List[str]] = None,
                          category_filter: Optional[List[str]] = None,
                          priority_filter: Optional[List[int]] = None) -> None:
        """Configure pipeline execution parameters.
        
        Args:
            enabled_transformations: Specific transformations to enable
            disabled_transformations: Specific transformations to disable  
            execution_order: Custom execution order
            category_filter: Filter by transformation categories
            priority_filter: Filter by priority levels
        """
        if enabled_transformations:
            self._enabled_transformations = set(enabled_transformations)
        
        if disabled_transformations:
            self._disabled_transformations = set(disabled_transformations)
        
        if execution_order:
            self._custom_execution_order = execution_order
        
        if category_filter:
            self._category_filters = {TransformationCategory(cat) for cat in category_filter}
        
        if priority_filter:
            self._priority_filters = {TransformationPriority(pri) for pri in priority_filter}
        
        logger.info("Pipeline configuration updated")
    
    def extract_features(self, 
                        data: Dict[str, Any],
                        context: Optional[Dict[str, Any]] = None,
                        use_cache: bool = True) -> Dict[str, Any]:
        """Extract features using the configured pipeline.
        
        Args:
            data: Input data dictionary
            context: Optional context for transformations
            use_cache: Whether to use cached results
            
        Returns:
            Dictionary containing all extracted features
        """
        start_time = time.time()
        
        try:
            # Generate cache key
            cache_key = self._generate_cache_key(data) if use_cache and self.enable_caching else None
            
            # Check cache
            if cache_key and self._check_cache(cache_key):
                cached_result, _ = self._feature_cache[cache_key]
                self._execution_stats["cache_hits"] += 1
                logger.debug("Using cached feature extraction result")
                return cached_result.copy()
            
            # Track cache miss
            if cache_key:
                self._execution_stats["cache_misses"] += 1
            
            # Determine transformations to execute
            transformations_to_run = self._get_transformations_to_execute()
            
            # Create execution context
            execution_context = context or {}
            execution_context.update({
                "pipeline_start_time": start_time,
                "input_data_keys": list(data.keys()),
                "transformations_planned": len(transformations_to_run)
            })
            
            # Execute pipeline
            result = self.registry.execute_pipeline(
                data, 
                execution_context, 
                transformations_to_run
            )
            
            # Validate results if enabled
            if self.enable_validation:
                validation_errors = self._validate_pipeline_output(result, data)
                if validation_errors:
                    self._execution_stats["validation_failures"] += 1
                    logger.warning(f"Pipeline validation warnings: {validation_errors}")
            
            # Cache results
            if cache_key:
                self._cache_result(cache_key, result)
            
            # Update statistics
            execution_time = time.time() - start_time
            self._execution_stats["total_executions"] += 1
            self._execution_stats["total_features_produced"] += len(result)
            self._execution_stats["total_execution_time"] += execution_time
            
            logger.debug(
                f"Feature extraction completed: {len(result)} features in {execution_time:.4f}s"
            )
            
            return result
            
        except Exception as exc:
            execution_time = time.time() - start_time
            logger.error(f"Feature extraction failed after {execution_time:.4f}s: {exc}")
            
            # Return input data as fallback
            return data.copy()
    
    async def extract_features_async(self,
                                   data: Dict[str, Any],
                                   context: Optional[Dict[str, Any]] = None,
                                   use_cache: bool = True) -> Dict[str, Any]:
        """Async version of feature extraction.
        
        Args:
            data: Input data dictionary
            context: Optional context for transformations
            use_cache: Whether to use cached results
            
        Returns:
            Dictionary containing all extracted features
        """
        import asyncio
        
        # Run feature extraction in thread pool for CPU-bound work
        loop = asyncio.get_event_loop()
        
        result = await loop.run_in_executor(
            None,  # Use default executor
            self.extract_features,
            data,
            context,
            use_cache
        )
        
        return result
    
    def extract_features_batch(self,
                              data_batch: List[Dict[str, Any]],
                              context: Optional[Dict[str, Any]] = None,
                              parallel: bool = True) -> List[Dict[str, Any]]:
        """Extract features for a batch of data.
        
        Args:
            data_batch: List of input data dictionaries
            context: Optional context for transformations
            parallel: Whether to process in parallel
            
        Returns:
            List of feature dictionaries
        """
        start_time = time.time()
        
        if not parallel or len(data_batch) == 1:
            # Sequential processing
            results = []
            for data in data_batch:
                result = self.extract_features(data, context)
                results.append(result)
        else:
            # Parallel processing
            import concurrent.futures
            import threading
            
            max_workers = min(len(data_batch), env_constants.WORKER_THREADS)
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = []
                for data in data_batch:
                    future = executor.submit(self.extract_features, data, context)
                    futures.append(future)
                
                results = []
                for future in concurrent.futures.as_completed(futures):
                    try:
                        result = future.result()
                        results.append(result)
                    except Exception as exc:
                        logger.error(f"Batch feature extraction failed: {exc}")
                        results.append({})
        
        execution_time = time.time() - start_time
        logger.info(
            f"Batch feature extraction completed: {len(results)} items in {execution_time:.4f}s"
        )
        
        return results
    
    def _get_transformations_to_execute(self) -> List[str]:
        """Determine which transformations to execute based on configuration."""
        # Get all registered transformations
        all_transformations = self.registry.list_transformations()
        
        # Apply enabled/disabled filters
        if self._enabled_transformations:
            transformations = [t for t in all_transformations if t in self._enabled_transformations]
        else:
            transformations = [t for t in all_transformations if t not in self._disabled_transformations]
        
        # Apply category filters
        if self._category_filters:
            filtered_transformations = []
            for name in transformations:
                transformation = self.registry.get_transformation(name)
                if transformation and transformation.metadata.category in self._category_filters:
                    filtered_transformations.append(name)
            transformations = filtered_transformations
        
        # Apply priority filters
        if self._priority_filters:
            filtered_transformations = []
            for name in transformations:
                transformation = self.registry.get_transformation(name)
                if transformation and transformation.metadata.priority in self._priority_filters:
                    filtered_transformations.append(name)
            transformations = filtered_transformations
        
        # Apply custom execution order
        if self._custom_execution_order:
            # Use custom order, but only include enabled transformations
            ordered_transformations = []
            for name in self._custom_execution_order:
                if name in transformations:
                    ordered_transformations.append(name)
            
            # Add any remaining transformations not in custom order
            for name in transformations:
                if name not in ordered_transformations:
                    ordered_transformations.append(name)
            
            transformations = ordered_transformations
        
        return transformations
    
    def _generate_cache_key(self, data: Dict[str, Any]) -> str:
        """Generate cache key for input data."""
        # Create a deterministic key based on data content
        key_parts = []
        
        # Sort keys for consistency
        for key in sorted(data.keys()):
            value = data[key]
            if isinstance(value, (str, int, float, bool)):
                key_parts.append(f"{key}:{value}")
            elif isinstance(value, (list, tuple)):
                key_parts.append(f"{key}:{len(value)}")
            elif isinstance(value, dict):
                key_parts.append(f"{key}:{len(value)}")
            else:
                key_parts.append(f"{key}:{type(value).__name__}")
        
        cache_key = "|".join(key_parts)
        return str(hash(cache_key))
    
    def _check_cache(self, cache_key: str) -> bool:
        """Check if cached result is valid."""
        if cache_key not in self._feature_cache:
            return False
        
        _, cached_time = self._feature_cache[cache_key]
        current_time = time.time()
        
        if current_time - cached_time > self.cache_ttl:
            # Cache expired
            del self._feature_cache[cache_key]
            return False
        
        return True
    
    def _cache_result(self, cache_key: str, result: Dict[str, Any]) -> None:
        """Cache extraction result."""
        current_time = time.time()
        self._feature_cache[cache_key] = (result.copy(), current_time)
        
        # Cleanup old cache entries (simple LRU)
        max_cache_size = 1000  # Could be configurable
        if len(self._feature_cache) > max_cache_size:
            # Remove oldest 20% of entries
            sorted_entries = sorted(
                self._feature_cache.items(), 
                key=lambda x: x[1][1]  # Sort by timestamp
            )
            
            entries_to_remove = len(sorted_entries) // 5
            for cache_key_to_remove, _ in sorted_entries[:entries_to_remove]:
                del self._feature_cache[cache_key_to_remove]
    
    def _validate_pipeline_output(self, 
                                 result: Dict[str, Any], 
                                 input_data: Dict[str, Any]) -> List[str]:
        """Validate pipeline output for common issues."""
        errors = []
        
        # Check for NaN or infinite values
        for key, value in result.items():
            if isinstance(value, float):
                if np.isnan(value):
                    errors.append(f"NaN value in feature: {key}")
                elif np.isinf(value):
                    errors.append(f"Infinite value in feature: {key}")
        
        # Check that we have more features than input
        if len(result) <= len(input_data):
            errors.append("Pipeline did not add any new features")
        
        # Check for expected feature categories
        expected_categories = ["spatial", "signal", "mobility"]
        found_categories = set()
        
        for transformation_name in self.registry.list_transformations():
            transformation = self.registry.get_transformation(transformation_name)
            if transformation:
                found_categories.add(transformation.metadata.category.value)
        
        for expected_cat in expected_categories:
            if expected_cat not in found_categories:
                errors.append(f"Missing transformations from category: {expected_cat}")
        
        return errors
    
    def clear_cache(self) -> None:
        """Clear the feature cache."""
        self._feature_cache.clear()
        logger.info("Feature extraction cache cleared")
    
    def get_pipeline_statistics(self) -> Dict[str, Any]:
        """Get pipeline execution statistics."""
        avg_execution_time = (
            self._execution_stats["total_execution_time"] / 
            max(1, self._execution_stats["total_executions"])
        )
        
        avg_features_per_execution = (
            self._execution_stats["total_features_produced"] / 
            max(1, self._execution_stats["total_executions"])
        )
        
        cache_hit_rate = (
            self._execution_stats["cache_hits"] / 
            max(1, self._execution_stats["cache_hits"] + self._execution_stats["cache_misses"])
        )
        
        return {
            "execution_statistics": self._execution_stats.copy(),
            "average_execution_time": avg_execution_time,
            "average_features_per_execution": avg_features_per_execution,
            "cache_hit_rate": cache_hit_rate,
            "cache_size": len(self._feature_cache),
            "enabled_transformations": len(self._get_transformations_to_execute()),
            "total_registered_transformations": len(self.registry.list_transformations())
        }
    
    def get_pipeline_configuration(self) -> Dict[str, Any]:
        """Get current pipeline configuration."""
        return {
            "enable_caching": self.enable_caching,
            "cache_ttl": self.cache_ttl,
            "enable_validation": self.enable_validation,
            "enabled_transformations": list(self._enabled_transformations),
            "disabled_transformations": list(self._disabled_transformations),
            "custom_execution_order": self._custom_execution_order,
            "category_filters": [cat.value for cat in self._category_filters],
            "priority_filters": [pri.value for pri in self._priority_filters]
        }
    
    def reset_statistics(self) -> None:
        """Reset pipeline statistics."""
        self._execution_stats = {
            "total_executions": 0,
            "total_features_produced": 0,
            "total_execution_time": 0.0,
            "cache_hits": 0,
            "cache_misses": 0,
            "validation_failures": 0
        }
        logger.info("Pipeline statistics reset")


# Global pipeline instance
_global_pipeline: Optional[FeatureExtractionPipeline] = None


def get_feature_pipeline() -> FeatureExtractionPipeline:
    """Get the global feature extraction pipeline."""
    global _global_pipeline
    
    if _global_pipeline is None:
        _global_pipeline = FeatureExtractionPipeline()
    
    return _global_pipeline


def extract_features(data: Dict[str, Any], 
                    context: Optional[Dict[str, Any]] = None,
                    use_cache: bool = True) -> Dict[str, Any]:
    """Convenience function for feature extraction."""
    pipeline = get_feature_pipeline()
    return pipeline.extract_features(data, context, use_cache)


async def extract_features_async(data: Dict[str, Any],
                                context: Optional[Dict[str, Any]] = None,
                                use_cache: bool = True) -> Dict[str, Any]:
    """Convenience function for async feature extraction."""
    pipeline = get_feature_pipeline()
    return await pipeline.extract_features_async(data, context, use_cache)


def extract_features_batch(data_batch: List[Dict[str, Any]],
                          context: Optional[Dict[str, Any]] = None,
                          parallel: bool = True) -> List[Dict[str, Any]]:
    """Convenience function for batch feature extraction."""
    pipeline = get_feature_pipeline()
    return pipeline.extract_features_batch(data_batch, context, parallel)