"""Feature extraction caching layer for performance optimization."""

import time
import threading
from typing import Dict, Any, Optional, Tuple
from functools import lru_cache
from dataclasses import dataclass
from ..config.constants import (
    DEFAULT_FEATURE_CACHE_SIZE,
    DEFAULT_FEATURE_CACHE_TTL,
    DEFAULT_FALLBACK_RSRP,
    DEFAULT_FALLBACK_SINR,
    DEFAULT_FALLBACK_RSRQ
)


@dataclass
class CachedFeatures:
    """Container for cached feature extraction results."""
    features: Dict[str, Any]
    timestamp: float
    ue_id: str
    data_hash: int


class FeatureExtractionCache:
    """Thread-safe cache for feature extraction results."""
    
    def __init__(self, max_size: int = DEFAULT_FEATURE_CACHE_SIZE, ttl_seconds: float = DEFAULT_FEATURE_CACHE_TTL):
        """Initialize the feature cache.
        
        Args:
            max_size: Maximum number of cached entries
            ttl_seconds: Time-to-live for cached entries
        """
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._cache: Dict[str, CachedFeatures] = {}
        self._access_times: Dict[str, float] = {}
        self._lock = threading.RLock()
        
        # Performance counters
        self._hits = 0
        self._misses = 0
        self._evictions = 0
    
    def _generate_cache_key(self, ue_id: str, data: Dict[str, Any]) -> Tuple[str, int]:
        """Generate cache key and data hash for UE data."""
        # Create a stable hash of the relevant data fields
        relevant_fields = [
            'latitude', 'longitude', 'speed', 'velocity', 'acceleration',
            'Cell_id', 'altitude', 'direction', 'rf_metrics'
        ]
        
        hash_data = []
        for field in relevant_fields:
            value = data.get(field)
            if isinstance(value, dict):
                # Sort dict items for consistent hashing
                hash_data.append(tuple(sorted(value.items())))
            elif isinstance(value, list):
                hash_data.append(tuple(value))
            else:
                hash_data.append(value)
        
        data_hash = hash(tuple(hash_data))
        cache_key = f"{ue_id}:{data_hash}"
        
        return cache_key, data_hash
    
    def get(self, ue_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Get cached features if available and not expired."""
        cache_key, data_hash = self._generate_cache_key(ue_id, data)
        current_time = time.time()
        
        with self._lock:
            cached = self._cache.get(cache_key)
            
            if cached is None:
                self._misses += 1
                return None
            
            # Check if cache entry is expired
            if current_time - cached.timestamp > self.ttl_seconds:
                del self._cache[cache_key]
                del self._access_times[cache_key]
                self._misses += 1
                return None
            
            # Update access time
            self._access_times[cache_key] = current_time
            self._hits += 1
            return cached.features.copy()  # Return copy to prevent modification
    
    def put(self, ue_id: str, data: Dict[str, Any], features: Dict[str, Any]) -> None:
        """Cache extracted features."""
        cache_key, data_hash = self._generate_cache_key(ue_id, data)
        current_time = time.time()
        
        with self._lock:
            # Evict expired entries if we're at capacity
            if len(self._cache) >= self.max_size:
                self._evict_expired()
                
                # If still at capacity, evict LRU entry
                if len(self._cache) >= self.max_size:
                    self._evict_lru()
            
            cached_features = CachedFeatures(
                features=features.copy(),
                timestamp=current_time,
                ue_id=ue_id,
                data_hash=data_hash
            )
            
            self._cache[cache_key] = cached_features
            self._access_times[cache_key] = current_time
    
    def _evict_expired(self) -> None:
        """Remove expired cache entries."""
        current_time = time.time()
        expired_keys = []
        
        for key, cached in self._cache.items():
            if current_time - cached.timestamp > self.ttl_seconds:
                expired_keys.append(key)
        
        for key in expired_keys:
            del self._cache[key]
            del self._access_times[key]
            self._evictions += 1
    
    def _evict_lru(self) -> None:
        """Remove least recently used cache entry."""
        if not self._access_times:
            return
        
        # Find the least recently accessed key
        lru_key = min(self._access_times.keys(), key=lambda k: self._access_times[k])
        
        del self._cache[lru_key]
        del self._access_times[lru_key]
        self._evictions += 1
    
    def clear(self) -> None:
        """Clear all cached entries."""
        with self._lock:
            self._cache.clear()
            self._access_times.clear()
            self._hits = 0
            self._misses = 0
            self._evictions = 0
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache performance statistics."""
        with self._lock:
            total_requests = self._hits + self._misses
            hit_rate = self._hits / total_requests if total_requests > 0 else 0.0
            
            return {
                "cache_size": len(self._cache),
                "max_size": self.max_size,
                "ttl_seconds": self.ttl_seconds,
                "hits": self._hits,
                "misses": self._misses,
                "evictions": self._evictions,
                "hit_rate": hit_rate,
                "utilization": len(self._cache) / self.max_size
            }


# Global cache instance
feature_cache = FeatureExtractionCache()


# Optimized helper functions
@lru_cache(maxsize=256)
def _cached_direction_to_unit(direction_tuple: Tuple[float, float, float]) -> Tuple[float, float]:
    """Cached version of direction to unit vector conversion."""
    if len(direction_tuple) >= 2:
        magnitude = (direction_tuple[0] ** 2 + direction_tuple[1] ** 2) ** 0.5
        if magnitude > 0:
            return direction_tuple[0] / magnitude, direction_tuple[1] / magnitude
    return 0.0, 0.0


@lru_cache(maxsize=512)
def _cached_signal_extraction(rsrp: Optional[float], sinr: Optional[float], rsrq: Optional[float]) -> Tuple[float, float, float]:
    """Cached signal value extraction with defaults."""
    return (
        rsrp if rsrp is not None else DEFAULT_FALLBACK_RSRP,
        sinr if sinr is not None else DEFAULT_FALLBACK_SINR,
        rsrq if rsrq is not None else DEFAULT_FALLBACK_RSRQ
    )


def clear_feature_caches():
    """Clear all feature extraction caches."""
    feature_cache.clear()
    _cached_direction_to_unit.cache_clear()
    _cached_signal_extraction.cache_clear()


def get_cache_stats() -> Dict[str, Any]:
    """Get comprehensive cache statistics."""
    return {
        "feature_cache": feature_cache.get_stats(),
        "direction_cache": {
            "hits": _cached_direction_to_unit.cache_info().hits,
            "misses": _cached_direction_to_unit.cache_info().misses,
            "maxsize": _cached_direction_to_unit.cache_info().maxsize,
            "currsize": _cached_direction_to_unit.cache_info().currsize
        },
        "signal_cache": {
            "hits": _cached_signal_extraction.cache_info().hits,
            "misses": _cached_signal_extraction.cache_info().misses,
            "maxsize": _cached_signal_extraction.cache_info().maxsize,
            "currsize": _cached_signal_extraction.cache_info().currsize
        }
    }