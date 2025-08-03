"""Memory-optimized dictionary implementations with reduced overhead."""

import logging
import threading
import time
import gc
import weakref
from collections import OrderedDict
from typing import Any, Dict, Optional, Set, Union, Callable, TypeVar, Generic, Tuple
import psutil
import os

from ..config.constants import env_constants


K = TypeVar('K')
V = TypeVar('V')

logger = logging.getLogger(__name__)


class CompactCacheEntry(Generic[V]):
    """Memory-optimized cache entry using __slots__ for reduced overhead."""
    
    __slots__ = ('value', 'timestamp', 'access_count')
    
    def __init__(self, value: V):
        self.value = value
        self.timestamp = time.time()
        self.access_count = 1
    
    def mark_accessed(self) -> None:
        """Mark entry as accessed and update timestamp."""
        self.timestamp = time.time()
        self.access_count += 1
    
    def age(self) -> float:
        """Get age of entry in seconds."""
        return time.time() - self.timestamp
    
    def is_expired(self, ttl_seconds: float) -> bool:
        """Check if entry is expired."""
        return self.age() > ttl_seconds


class MemoryOptimizedLRU(Generic[K, V]):
    """Highly memory-optimized LRU cache with automatic memory management."""
    
    def __init__(self,
                 max_size: int = 1000,
                 ttl_seconds: Optional[float] = None,
                 memory_limit_mb: Optional[int] = None,
                 cleanup_interval: float = 60.0,
                 emergency_cleanup_ratio: float = 0.1):
        """Initialize memory-optimized LRU cache.
        
        Args:
            max_size: Maximum number of entries
            ttl_seconds: Time-to-live for entries
            memory_limit_mb: Memory limit in MB (triggers cleanup)
            cleanup_interval: Cleanup interval in seconds
            emergency_cleanup_ratio: Fraction to clean during emergency
        """
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self.memory_limit_mb = memory_limit_mb
        self.cleanup_interval = cleanup_interval
        self.emergency_cleanup_ratio = emergency_cleanup_ratio
        
        # Use OrderedDict for O(1) move operations
        self._data: OrderedDict[K, CompactCacheEntry[V]] = OrderedDict()
        self._lock = threading.RLock()
        self._last_cleanup = time.time()
        self._last_memory_check = time.time()
        
        # Optimized statistics (use integers for speed)
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._ttl_expiries = 0
        self._memory_cleanups = 0
        
        # Process monitoring for memory usage
        self._process = psutil.Process(os.getpid()) if memory_limit_mb else None
    
    def get(self, key: K, default: Optional[V] = None) -> Optional[V]:
        """Get value with optimized access pattern."""
        with self._lock:
            # Fast path - check existence without cleanup
            if key not in self._data:
                self._misses += 1
                return default
            
            entry = self._data[key]
            
            # Fast TTL check without datetime objects
            if self.ttl_seconds and entry.is_expired(self.ttl_seconds):
                del self._data[key]
                self._ttl_expiries += 1
                self._misses += 1
                return default
            
            # Move to end (most recently used) - O(1) operation
            self._data.move_to_end(key)
            entry.mark_accessed()
            self._hits += 1
            
            # Deferred cleanup check
            self._maybe_cleanup_deferred()
            
            return entry.value
    
    def set(self, key: K, value: V) -> None:
        """Set value with memory-optimized storage."""
        with self._lock:
            if key in self._data:
                # Update existing entry
                entry = self._data[key]
                entry.value = value
                entry.mark_accessed()
                self._data.move_to_end(key)
            else:
                # Create new entry with minimal overhead
                entry = CompactCacheEntry(value)
                self._data[key] = entry
                
                # Check size limit
                if len(self._data) > self.max_size:
                    self._evict_lru_batch()
            
            # Check memory pressure
            self._maybe_memory_cleanup()
    
    def __getitem__(self, key: K) -> V:
        """Dictionary access with KeyError on miss."""
        result = self.get(key)
        if result is None:
            raise KeyError(key)
        return result
    
    def __setitem__(self, key: K, value: V) -> None:
        """Dictionary assignment."""
        self.set(key, value)
    
    def __contains__(self, key: K) -> bool:
        """Fast containment check."""
        with self._lock:
            if key not in self._data:
                return False
            
            entry = self._data[key]
            if self.ttl_seconds and entry.is_expired(self.ttl_seconds):
                del self._data[key]
                self._ttl_expiries += 1
                return False
            
            return True
    
    def __len__(self) -> int:
        """Return current size (may include expired entries)."""
        return len(self._data)
    
    def setdefault(self, key: K, default: V) -> V:
        """Get or set default value."""
        existing = self.get(key)
        if existing is not None:
            return existing
        
        self.set(key, default)
        return default
    
    def pop(self, key: K, default: Optional[V] = None) -> Optional[V]:
        """Remove and return value."""
        with self._lock:
            if key in self._data:
                entry = self._data.pop(key)
                if not (self.ttl_seconds and entry.is_expired(self.ttl_seconds)):
                    return entry.value
            return default
    
    def clear(self) -> None:
        """Clear all entries and reset statistics."""
        with self._lock:
            self._data.clear()
            self._hits = 0
            self._misses = 0
            self._evictions = 0
            self._ttl_expiries = 0
            self._memory_cleanups = 0
            
            # Force garbage collection after clear
            gc.collect()
    
    def compact(self) -> int:
        """Remove expired entries and return count removed."""
        if not self.ttl_seconds:
            return 0
        
        with self._lock:
            expired_keys = []
            for key, entry in self._data.items():
                if entry.is_expired(self.ttl_seconds):
                    expired_keys.append(key)
            
            for key in expired_keys:
                del self._data[key]
            
            self._ttl_expiries += len(expired_keys)
            
            # Trigger garbage collection after compaction
            if expired_keys:
                gc.collect()
            
            return len(expired_keys)
    
    def get_memory_usage(self) -> Dict[str, Any]:
        """Get detailed memory usage statistics."""
        if not self._process:
            return {"error": "Memory monitoring not enabled"}
        
        try:
            memory_info = self._process.memory_info()
            
            # Estimate cache memory usage
            with self._lock:
                estimated_entry_size = 0
                if self._data:
                    # Sample a few entries to estimate size
                    sample_keys = list(self._data.keys())[:min(10, len(self._data))]
                    total_sample_size = 0
                    
                    for key in sample_keys:
                        entry = self._data[key]
                        # Rough estimation of memory usage
                        key_size = len(str(key)) if isinstance(key, str) else 64
                        value_size = len(str(entry.value)) if hasattr(entry.value, '__len__') else 64
                        total_sample_size += key_size + value_size + 96  # Overhead estimate
                    
                    estimated_entry_size = total_sample_size // len(sample_keys) if sample_keys else 0
                
                estimated_cache_size = estimated_entry_size * len(self._data)
            
            return {
                "process_memory_mb": memory_info.rss / 1024 / 1024,
                "estimated_cache_mb": estimated_cache_size / 1024 / 1024,
                "cache_entries": len(self._data),
                "estimated_entry_size_bytes": estimated_entry_size,
                "memory_limit_mb": self.memory_limit_mb
            }
        except Exception as e:
            return {"error": str(e)}
    
    def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive cache statistics."""
        with self._lock:
            total_requests = self._hits + self._misses
            hit_rate = self._hits / total_requests if total_requests > 0 else 0.0
            
            stats = {
                "size": len(self._data),
                "max_size": self.max_size,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": hit_rate,
                "evictions": self._evictions,
                "ttl_expiries": self._ttl_expiries,
                "memory_cleanups": self._memory_cleanups,
                "ttl_seconds": self.ttl_seconds,
                "memory_limit_mb": self.memory_limit_mb
            }
            
            # Add memory statistics if available
            memory_stats = self.get_memory_usage()
            if "error" not in memory_stats:
                stats.update(memory_stats)
            
            return stats
    
    def _evict_lru_batch(self, batch_size: Optional[int] = None) -> None:
        """Evict multiple LRU entries for efficiency."""
        if not self._data:
            return
        
        if batch_size is None:
            # Default to 10% of max size or at least 1
            batch_size = max(1, self.max_size // 10)
        
        # Evict the oldest entries
        evicted = 0
        while self._data and evicted < batch_size and len(self._data) > self.max_size:
            self._data.popitem(last=False)
            evicted += 1
        
        self._evictions += evicted
        
        if evicted > 0:
            logger.debug("Batch evicted %d LRU entries", evicted)
    
    def _maybe_cleanup_deferred(self) -> None:
        """Perform cleanup operations with minimal frequency."""
        now = time.time()
        if now - self._last_cleanup > self.cleanup_interval:
            self._last_cleanup = now
            
            # Quick cleanup of expired entries
            if self.ttl_seconds:
                expired_count = self.compact()
                if expired_count > 0:
                    logger.debug("Cleaned up %d expired entries", expired_count)
    
    def _maybe_memory_cleanup(self) -> None:
        """Check memory usage and perform emergency cleanup if needed."""
        if not self._process or not self.memory_limit_mb:
            return
        
        now = time.time()
        if now - self._last_memory_check < 30.0:  # Check every 30 seconds
            return
        
        self._last_memory_check = now
        
        try:
            memory_mb = self._process.memory_info().rss / 1024 / 1024
            
            if memory_mb > self.memory_limit_mb:
                # Emergency cleanup - remove a fraction of entries
                cleanup_count = int(len(self._data) * self.emergency_cleanup_ratio)
                if cleanup_count > 0:
                    logger.warning(
                        "Memory limit exceeded (%.1f MB > %d MB), performing emergency cleanup of %d entries",
                        memory_mb, self.memory_limit_mb, cleanup_count
                    )
                    
                    with self._lock:
                        for _ in range(cleanup_count):
                            if self._data:
                                self._data.popitem(last=False)
                        
                        self._memory_cleanups += 1
                        
                    # Force garbage collection
                    gc.collect()
                    
        except Exception as e:
            logger.warning("Memory check failed: %s", e)


class OptimizedUETrackingDict(MemoryOptimizedLRU[str, V]):
    """Memory-optimized UE tracking dictionary with monitoring."""
    
    def __init__(self, 
                 max_ues: int = 10000, 
                 ue_ttl_hours: float = 24.0,
                 memory_limit_mb: Optional[int] = None):
        """Initialize optimized UE tracking dict.
        
        Args:
            max_ues: Maximum number of UEs to track
            ue_ttl_hours: TTL for UE entries in hours
            memory_limit_mb: Memory limit in MB
        """
        # Use environment defaults if not provided
        if memory_limit_mb is None:
            memory_limit_mb = env_constants.UE_TRACKING_MEMORY_LIMIT_MB
        
        super().__init__(
            max_size=max_ues,
            ttl_seconds=ue_ttl_hours * 3600,
            memory_limit_mb=memory_limit_mb,
            cleanup_interval=env_constants.UE_TRACKING_CLEANUP_INTERVAL,
            emergency_cleanup_ratio=0.2  # Clean 20% during emergency
        )
        
        self._ue_activity_stats: Dict[str, int] = {}
        self._stats_lock = threading.Lock()
    
    def set(self, key: str, value: V) -> None:
        """Override set to track UE activity."""
        super().set(key, value)
        
        # Track UE activity for analytics
        with self._stats_lock:
            self._ue_activity_stats[key] = self._ue_activity_stats.get(key, 0) + 1
    
    def get_active_ue_count(self) -> int:
        """Get count of active (non-expired) UEs."""
        return len(self)
    
    def get_top_active_ues(self, limit: int = 10) -> List[Tuple[str, int]]:
        """Get most active UEs by access count."""
        with self._stats_lock:
            sorted_ues = sorted(
                self._ue_activity_stats.items(),
                key=lambda x: x[1],
                reverse=True
            )
            return sorted_ues[:limit]
    
    def log_stats(self) -> None:
        """Log comprehensive UE tracking statistics."""
        stats = self.get_stats()
        memory_stats = self.get_memory_usage()
        
        logger.info(
            "UE Tracking Stats - Active UEs: %d/%d, Hit Rate: %.2f%%, "
            "Evictions: %d, Expiries: %d, Memory: %.1f MB",
            stats["size"], stats["max_size"], stats["hit_rate"] * 100,
            stats["evictions"], stats["ttl_expiries"],
            memory_stats.get("process_memory_mb", 0)
        )
        
        # Log top active UEs periodically
        top_ues = self.get_top_active_ues(5)
        if top_ues:
            ue_list = ", ".join(f"{ue}({count})" for ue, count in top_ues)
            logger.debug("Top active UEs: %s", ue_list)
    
    def cleanup_inactive_ues(self, min_activity: int = 1) -> int:
        """Remove UEs with low activity count."""
        removed_count = 0
        
        with self._lock:
            inactive_ues = []
            
            with self._stats_lock:
                for ue_id in list(self._data.keys()):
                    activity = self._ue_activity_stats.get(ue_id, 0)
                    if activity < min_activity:
                        inactive_ues.append(ue_id)
            
            # Remove inactive UEs
            for ue_id in inactive_ues:
                if ue_id in self._data:
                    del self._data[ue_id]
                    removed_count += 1
                
                with self._stats_lock:
                    self._ue_activity_stats.pop(ue_id, None)
        
        if removed_count > 0:
            logger.info("Cleaned up %d inactive UEs", removed_count)
        
        return removed_count


class MemoryEfficientSignalBuffer:
    """Memory-efficient circular buffer for signal data."""
    
    def __init__(self, max_size: int = 100):
        self.max_size = max_size
        self._buffer = [None] * max_size
        self._head = 0
        self._size = 0
        self._lock = threading.Lock()
    
    def append(self, value: Any) -> None:
        """Add value to buffer."""
        with self._lock:
            self._buffer[self._head] = value
            self._head = (self._head + 1) % self.max_size
            if self._size < self.max_size:
                self._size += 1
    
    def get_recent(self, count: int) -> List[Any]:
        """Get most recent N values."""
        with self._lock:
            if count >= self._size:
                # Return all values in order
                if self._size == self.max_size:
                    return self._buffer[self._head:] + self._buffer[:self._head]
                else:
                    return [x for x in self._buffer[:self._size] if x is not None]
            else:
                # Return last N values
                result = []
                for i in range(count):
                    idx = (self._head - 1 - i) % self.max_size
                    if idx < self._size:
                        result.append(self._buffer[idx])
                return list(reversed(result))
    
    def calculate_stats(self) -> Dict[str, float]:
        """Calculate statistics for numeric values."""
        recent_values = [v for v in self.get_recent(self._size) if isinstance(v, (int, float))]
        
        if not recent_values:
            return {"mean": 0.0, "std": 0.0, "min": 0.0, "max": 0.0}
        
        mean = sum(recent_values) / len(recent_values)
        variance = sum((x - mean) ** 2 for x in recent_values) / len(recent_values)
        std = variance ** 0.5
        
        return {
            "mean": mean,
            "std": std,
            "min": min(recent_values),
            "max": max(recent_values),
            "count": len(recent_values)
        }
    
    def clear(self) -> None:
        """Clear the buffer."""
        with self._lock:
            self._buffer = [None] * self.max_size
            self._head = 0
            self._size = 0


# Factory functions for easy migration
def create_optimized_ue_tracking_dict(max_ues: int = 10000, 
                                     ue_ttl_hours: float = 24.0) -> OptimizedUETrackingDict:
    """Create an optimized UE tracking dictionary."""
    return OptimizedUETrackingDict(
        max_ues=max_ues,
        ue_ttl_hours=ue_ttl_hours,
        memory_limit_mb=env_constants.UE_TRACKING_MEMORY_LIMIT_MB
    )


def create_memory_efficient_cache(max_size: int = 1000,
                                 ttl_seconds: Optional[float] = None) -> MemoryOptimizedLRU:
    """Create a memory-efficient cache."""
    return MemoryOptimizedLRU(
        max_size=max_size,
        ttl_seconds=ttl_seconds,
        memory_limit_mb=env_constants.CACHE_MEMORY_LIMIT_MB
    )