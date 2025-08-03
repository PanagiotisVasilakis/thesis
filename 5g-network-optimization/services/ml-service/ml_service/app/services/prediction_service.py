"""Prediction service using dependency injection for loose coupling."""

from typing import Dict, Any, List, Optional
import time
from datetime import datetime

from ..core.dependency_injection import autowired, inject
from ..core.interfaces import (
    ModelInterface,
    CacheInterface,
    MetricsCollectorInterface,
    LoggerInterface,
    ValidatorInterface
)


@autowired
class PredictionService:
    """Service for handling predictions with dependency injection."""
    
    def __init__(self, 
                 model: ModelInterface,
                 cache: CacheInterface,
                 metrics: MetricsCollectorInterface,
                 logger: LoggerInterface,
                 validator: Optional[ValidatorInterface] = None):
        """Initialize prediction service with injected dependencies."""
        self._model = model
        self._cache = cache
        self._metrics = metrics
        self._logger = logger
        self._validator = validator
        
        self._prediction_count = 0
        self._cache_hits = 0
        self._cache_misses = 0
        
        self._logger.info("PredictionService initialized with DI")
    
    def predict_single(self, ue_id: str, ue_data: Dict[str, Any], use_cache: bool = True) -> Dict[str, Any]:
        """Make a single prediction with caching support."""
        start_time = time.time()
        
        try:
            # Validate input if validator is available
            if self._validator:
                ue_data = self._validator.validate(ue_data, f"UE data for {ue_id}")
            
            # Check cache first if enabled
            cache_key = self._generate_cache_key(ue_id, ue_data)
            cached_result = None
            
            if use_cache:
                cached_result = self._cache.get(cache_key)
                if cached_result:
                    self._cache_hits += 1
                    self._logger.debug(f"Cache hit for UE {ue_id}")
                    
                    # Track cached prediction
                    self._metrics.track_prediction(
                        cached_result["antenna_id"],
                        cached_result["confidence"]
                    )
                    
                    return {
                        **cached_result,
                        "ue_id": ue_id,
                        "cached": True,
                        "processing_time": time.time() - start_time
                    }
            
            # Cache miss - perform prediction
            self._cache_misses += 1
            self._logger.debug(f"Cache miss for UE {ue_id}, performing prediction")
            
            # Extract features and predict
            features = self._model.extract_features(ue_data)
            result = self._model.predict(features)
            
            # Cache the result
            if use_cache:
                cache_value = {
                    "antenna_id": result["antenna_id"],
                    "confidence": result["confidence"],
                    "features_used": list(features.keys()),
                    "timestamp": datetime.now().isoformat()
                }
                self._cache.set(cache_key, cache_value, ttl=30.0)  # 30 second TTL
            
            # Track metrics
            self._metrics.track_prediction(result["antenna_id"], result["confidence"])
            self._prediction_count += 1
            
            processing_time = time.time() - start_time
            
            self._logger.info(
                f"Prediction for UE {ue_id}: {result['antenna_id']} "
                f"(confidence: {result['confidence']:.3f}, time: {processing_time:.3f}s)"
            )
            
            return {
                "ue_id": ue_id,
                "predicted_antenna": result["antenna_id"],
                "confidence": result["confidence"],
                "features_used": list(features.keys()),
                "cached": False,
                "processing_time": processing_time
            }
            
        except Exception as exc:
            self._logger.error(f"Prediction failed for UE {ue_id}: {exc}")
            raise
    
    async def predict_single_async(self, ue_id: str, ue_data: Dict[str, Any], 
                                  priority: int = 5, timeout: Optional[float] = None) -> Dict[str, Any]:
        """Make a single async prediction."""
        start_time = time.time()
        
        try:
            # Validate input if validator is available
            if self._validator:
                ue_data = self._validator.validate(ue_data, f"UE data for {ue_id}")
            
            # Extract features and predict asynchronously
            features = self._model.extract_features(ue_data)
            result = await self._model.predict_async(features, priority=priority, timeout=timeout)
            
            # Track metrics
            self._metrics.track_prediction(result["antenna_id"], result["confidence"])
            self._prediction_count += 1
            
            processing_time = time.time() - start_time
            
            self._logger.info(
                f"Async prediction for UE {ue_id}: {result['antenna_id']} "
                f"(confidence: {result['confidence']:.3f}, time: {processing_time:.3f}s)"
            )
            
            return {
                "ue_id": ue_id,
                "predicted_antenna": result["antenna_id"],
                "confidence": result["confidence"],
                "features_used": list(features.keys()),
                "async": True,
                "processing_time": processing_time
            }
            
        except Exception as exc:
            self._logger.error(f"Async prediction failed for UE {ue_id}: {exc}")
            raise
    
    def predict_batch(self, ue_data_batch: List[Dict[str, Any]], use_cache: bool = True) -> List[Dict[str, Any]]:
        """Make predictions for a batch of UEs."""
        start_time = time.time()
        results = []
        
        self._logger.info(f"Starting batch prediction for {len(ue_data_batch)} UEs")
        
        for ue_data in ue_data_batch:
            ue_id = ue_data.get("ue_id", f"unknown_{len(results)}")
            
            try:
                result = self.predict_single(ue_id, ue_data, use_cache=use_cache)
                results.append(result)
            except Exception as exc:
                self._logger.error(f"Batch prediction failed for UE {ue_id}: {exc}")
                # Add error result to maintain batch consistency
                results.append({
                    "ue_id": ue_id,
                    "error": str(exc),
                    "predicted_antenna": None,
                    "confidence": 0.0
                })
        
        total_time = time.time() - start_time
        self._logger.info(
            f"Batch prediction completed: {len(results)} results in {total_time:.3f}s "
            f"({total_time/len(results):.3f}s per prediction)"
        )
        
        return results
    
    def get_prediction_stats(self) -> Dict[str, Any]:
        """Get prediction service statistics."""
        cache_stats = self._cache.get_stats()
        
        return {
            "prediction_count": self._prediction_count,
            "cache_hits": self._cache_hits,
            "cache_misses": self._cache_misses,
            "cache_hit_rate": self._cache_hits / max(1, self._cache_hits + self._cache_misses),
            "cache_stats": cache_stats
        }
    
    def clear_cache(self) -> None:
        """Clear prediction cache."""
        self._cache.clear()
        self._logger.info("Prediction cache cleared")
    
    def _generate_cache_key(self, ue_id: str, ue_data: Dict[str, Any]) -> str:
        """Generate cache key for UE data."""
        # Create a simple hash-based cache key
        # In production, you might want a more sophisticated key generation
        key_data = {
            "ue_id": ue_id,
            "latitude": ue_data.get("latitude"),
            "longitude": ue_data.get("longitude"),
            "speed": ue_data.get("speed"),
            "connected_to": ue_data.get("connected_to")
        }
        
        # Simple hash-based key (in production, use a proper hash function)
        key_str = "|".join(str(v) for v in key_data.values() if v is not None)
        return f"prediction:{hash(key_str)}"


class TrainingService:
    """Service for handling model training with dependency injection."""
    
    def __init__(self, 
                 model: ModelInterface,
                 metrics: MetricsCollectorInterface,
                 logger: LoggerInterface,
                 validator: Optional[ValidatorInterface] = None):
        """Initialize training service with injected dependencies."""
        self._model = model
        self._metrics = metrics
        self._logger = logger
        self._validator = validator
        
        self._training_sessions = 0
        
        self._logger.info("TrainingService initialized with DI")
    
    def train_model(self, training_data: List[Dict[str, Any]], 
                   validate_data: bool = True) -> Dict[str, Any]:
        """Train model with given data."""
        start_time = time.time()
        
        try:
            self._logger.info(f"Starting training with {len(training_data)} samples")
            
            # Validate training data if validator is available
            if validate_data and self._validator:
                validated_data = []
                for i, sample in enumerate(training_data):
                    try:
                        validated_sample = self._validator.validate(sample, f"Training sample {i}")
                        validated_data.append(validated_sample)
                    except Exception as exc:
                        self._logger.warning(f"Skipping invalid training sample {i}: {exc}")
                
                training_data = validated_data
                self._logger.info(f"Validation complete: {len(training_data)} valid samples")
            
            # Perform training
            metrics = self._model.train(training_data)
            duration = time.time() - start_time
            
            # Track training metrics
            self._metrics.track_training(
                duration,
                metrics.get("samples", len(training_data)),
                metrics.get("accuracy")
            )
            
            self._training_sessions += 1
            
            self._logger.info(
                f"Training completed in {duration:.2f}s: {metrics.get('samples', 0)} samples, "
                f"{metrics.get('classes', 0)} classes"
            )
            
            return {
                **metrics,
                "training_duration": duration,
                "training_session": self._training_sessions
            }
            
        except Exception as exc:
            self._logger.error(f"Training failed: {exc}")
            raise
    
    async def train_model_async(self, training_data: List[Dict[str, Any]], 
                               priority: int = 3, timeout: Optional[float] = None,
                               validate_data: bool = True) -> Dict[str, Any]:
        """Train model asynchronously with given data."""
        start_time = time.time()
        
        try:
            self._logger.info(f"Starting async training with {len(training_data)} samples")
            
            # Validate training data if validator is available
            if validate_data and self._validator:
                validated_data = []
                for i, sample in enumerate(training_data):
                    try:
                        validated_sample = self._validator.validate(sample, f"Training sample {i}")
                        validated_data.append(validated_sample)
                    except Exception as exc:
                        self._logger.warning(f"Skipping invalid training sample {i}: {exc}")
                
                training_data = validated_data
                self._logger.info(f"Validation complete: {len(training_data)} valid samples")
            
            # Perform async training
            metrics = await self._model.train_async(training_data, priority=priority, timeout=timeout)
            duration = time.time() - start_time
            
            # Track training metrics
            self._metrics.track_training(
                duration,
                metrics.get("samples", len(training_data)),
                metrics.get("accuracy")
            )
            
            self._training_sessions += 1
            
            self._logger.info(
                f"Async training completed in {duration:.2f}s: {metrics.get('samples', 0)} samples"
            )
            
            return {
                **metrics,
                "training_duration": duration,
                "training_session": self._training_sessions,
                "async": True
            }
            
        except Exception as exc:
            self._logger.error(f"Async training failed: {exc}")
            raise
    
    def get_training_stats(self) -> Dict[str, Any]:
        """Get training service statistics."""
        return {
            "training_sessions": self._training_sessions
        }


# Factory functions for creating services with DI
@inject(ModelInterface, CacheInterface, MetricsCollectorInterface, LoggerInterface)
def create_prediction_service(model: ModelInterface, 
                             cache: CacheInterface,
                             metrics: MetricsCollectorInterface,
                             logger: LoggerInterface,
                             validator: Optional[ValidatorInterface] = None) -> PredictionService:
    """Factory function to create prediction service with DI."""
    return PredictionService(model, cache, metrics, logger, validator)


@inject(ModelInterface, MetricsCollectorInterface, LoggerInterface)
def create_training_service(model: ModelInterface,
                           metrics: MetricsCollectorInterface,
                           logger: LoggerInterface,
                           validator: Optional[ValidatorInterface] = None) -> TrainingService:
    """Factory function to create training service with DI."""
    return TrainingService(model, metrics, logger, validator)