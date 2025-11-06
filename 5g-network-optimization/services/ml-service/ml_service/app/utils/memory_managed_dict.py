"""Memory-managed dictionary implementations with automatic cleanup."""

import logging
import sys
import threading
import time
from collections import OrderedDict, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Set, Union, Callable, TypeVar, Generic
import weakref

K = TypeVar('K')
V = TypeVar('V')


@dataclass
class CacheEntry(Generic[V]):
    """Entry in a cache with metadata."""
    value: V
    created_at: datetime
    last_accessed: datetime
    access_count: int = 0
    
    def mark_accessed(self):
        """Mark this entry as accessed."""
        self.last_accessed = datetime.now(timezone.utc)
        self.access_count += 1


class LRUDict(Generic[K, V]):
    """LRU (Least Recently Used) dictionary with size limit and TTL support."""
    
    def __init__(
        self, 
        max_size: int = 1000, 
        ttl_seconds: Optional[float] = None,
        cleanup_interval: float = 300.0  # 5 minutes
    ):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self.cleanup_interval = cleanup_interval
        
        self._data: OrderedDict[K, CacheEntry[V]] = OrderedDict()
        self._lock = threading.RLock()
        self._last_cleanup = time.time()
        self.logger = logging.getLogger(__name__)
        
        # Statistics
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self.ttl_expiries = 0
    
    def get(self, key: K, default: Optional[V] = None) -> Optional[V]:
        """Get value by key, updating access time."""
        with self._lock:
            self._maybe_cleanup()
            
            if key not in self._data:
                self.misses += 1
                return default
            
            entry = self._data[key]
            
            # Check TTL expiry
            if self._is_expired(entry):
                del self._data[key]
                self.ttl_expiries += 1
                self.misses += 1
                return default
            
            # Move to end (most recently used)
            self._data.move_to_end(key)
            entry.mark_accessed()
            self.hits += 1
            return entry.value
    
    def set(self, key: K, value: V) -> None:
        """Set key-value pair."""
        with self._lock:
            self._maybe_cleanup()
            
            now = datetime.now(timezone.utc)
            
            if key in self._data:
                # Update existing entry
                entry = self._data[key]
                entry.value = value
                entry.last_accessed = now
                entry.access_count += 1
                self._data.move_to_end(key)
            else:
                # Add new entry
                entry = CacheEntry(
                    value=value,
                    created_at=now,
                    last_accessed=now
                )
                self._data[key] = entry
                
                # Enforce size limit
                if len(self._data) > self.max_size:
                    self._evict_lru()
    
    def __getitem__(self, key: K) -> V:
        """Dictionary-style access."""
        result = self.get(key)
        if result is None:
            raise KeyError(key)
        return result
    
    def __setitem__(self, key: K, value: V) -> None:
        """Dictionary-style assignment."""
        self.set(key, value)
    
    def __contains__(self, key: K) -> bool:
        """Check if key exists and is not expired."""
        with self._lock:
            if key not in self._data:
                return False
            
            entry = self._data[key]
            if self._is_expired(entry):
                del self._data[key]
                self.ttl_expiries += 1
                return False
            
            return True
    
    def __len__(self) -> int:
        """Return number of valid (non-expired) entries."""
        with self._lock:
            self._cleanup_expired()
            return len(self._data)
    
    def setdefault(self, key: K, default: V) -> V:
        """Get value or set and return default."""
        with self._lock:
            if key in self:
                return self.get(key)
            else:
                self.set(key, default)
                return default
    
    def pop(self, key: K, default: Optional[V] = None) -> Optional[V]:
        """Remove and return value."""
        with self._lock:
            if key in self._data:
                entry = self._data.pop(key)
                if not self._is_expired(entry):
                    return entry.value
            return default
    
    def clear(self) -> None:
        """Clear all entries."""
        with self._lock:
            self._data.clear()
            self.hits = 0
            self.misses = 0
            self.evictions = 0
            self.ttl_expiries = 0
    
    def keys(self):
        """Return non-expired keys."""
        with self._lock:
            self._cleanup_expired()
            return self._data.keys()
    
    def values(self):
        """Return non-expired values."""
        with self._lock:
            self._cleanup_expired()
            return [entry.value for entry in self._data.values()]
    
    def items(self):
        """Return non-expired key-value pairs."""
        with self._lock:
            self._cleanup_expired()
            return [(k, entry.value) for k, entry in self._data.items()]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            total_requests = self.hits + self.misses
            hit_rate = self.hits / total_requests if total_requests > 0 else 0.0
            
            return {
                "size": len(self._data),
                "max_size": self.max_size,
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate": hit_rate,
                "evictions": self.evictions,
                "ttl_expiries": self.ttl_expiries,
                "ttl_seconds": self.ttl_seconds
            }

    def get_memory_usage(self) -> Dict[str, Any]:
        """Estimate memory usage for the cache contents."""
        with self._lock:
            approx_bytes = sys.getsizeof(self._data)
            for key, entry in self._data.items():
                try:
                    approx_bytes += sys.getsizeof(key)
                except TypeError:
                    pass
                value = entry.value
                try:
                    approx_bytes += sys.getsizeof(value)
                except TypeError:
                    # Some objects (e.g. numpy arrays) handle their own sizing; ignore.
                    pass

            stats = self.get_stats()
            return {
                "cache_entries": stats["size"],
                "max_size": self.max_size,
                "approx_bytes": approx_bytes,
                "hit_rate": stats["hit_rate"],
                "evictions": stats["evictions"],
                "ttl_expiries": stats["ttl_expiries"],
            }
    
    def _is_expired(self, entry: CacheEntry[V]) -> bool:
        """Check if entry is expired based on TTL."""
        if self.ttl_seconds is None:
            return False
        
        age = (datetime.now(timezone.utc) - entry.created_at).total_seconds()
        return age > self.ttl_seconds
    
    def _evict_lru(self) -> None:
        """Evict least recently used entry."""
        if self._data:
            evicted_key, _ = self._data.popitem(last=False)
            self.evictions += 1
            self.logger.debug("LRU evicted key: %s", evicted_key)
    
    def _cleanup_expired(self) -> None:
        """Clean up expired entries."""
        if self.ttl_seconds is None:
            return
        
        expired_keys = []
        for key, entry in self._data.items():
            if self._is_expired(entry):
                expired_keys.append(key)
        
        for key in expired_keys:
            del self._data[key]
            self.ttl_expiries += 1
    
    def _maybe_cleanup(self) -> None:
        """Perform cleanup if interval has passed."""
        now = time.time()
        if now - self._last_cleanup > self.cleanup_interval:
            self._cleanup_expired()
            self._last_cleanup = now


class TTLDict(Generic[K, V]):
    """Dictionary with automatic time-to-live expiry."""
    
    def __init__(self, ttl_seconds: float = 3600.0, cleanup_interval: float = 300.0):
        self.ttl_seconds = ttl_seconds
        self.cleanup_interval = cleanup_interval
        
        self._data: Dict[K, CacheEntry[V]] = {}
        self._lock = threading.RLock()
        self._last_cleanup = time.time()
        self.logger = logging.getLogger(__name__)
    
    def get(self, key: K, default: Optional[V] = None) -> Optional[V]:
        """Get value by key if not expired."""
        with self._lock:
            self._maybe_cleanup()
            
            if key not in self._data:
                return default
            
            entry = self._data[key]
            if self._is_expired(entry):
                del self._data[key]
                return default
            
            entry.mark_accessed()
            return entry.value
    
    def set(self, key: K, value: V) -> None:
        """Set key-value pair with current timestamp."""
        with self._lock:
            now = datetime.now(timezone.utc)
            entry = CacheEntry(
                value=value,
                created_at=now,
                last_accessed=now
            )
            self._data[key] = entry
    
    def __getitem__(self, key: K) -> V:
        result = self.get(key)
        if result is None:
            raise KeyError(key)
        return result
    
    def __setitem__(self, key: K, value: V) -> None:
        self.set(key, value)
    
    def __contains__(self, key: K) -> bool:
        return self.get(key) is not None
    
    def __len__(self) -> int:
        with self._lock:
            self._cleanup_expired()
            return len(self._data)
    
    def setdefault(self, key: K, default: V) -> V:
        with self._lock:
            if key in self:
                return self.get(key)
            else:
                self.set(key, default)
                return default
    
    def clear(self) -> None:
        with self._lock:
            self._data.clear()
    
    def _is_expired(self, entry: CacheEntry[V]) -> bool:
        age = (datetime.now(timezone.utc) - entry.created_at).total_seconds()
        return age > self.ttl_seconds
    
    def _cleanup_expired(self) -> None:
        expired_keys = []
        for key, entry in self._data.items():
            if self._is_expired(entry):
                expired_keys.append(key)
        
        for key in expired_keys:
            del self._data[key]
    
    def _maybe_cleanup(self) -> None:
        now = time.time()
        if now - self._last_cleanup > self.cleanup_interval:
            self._cleanup_expired()
            self._last_cleanup = now


class WeakValueDict(Generic[K, V]):
    """Dictionary that automatically removes entries when values are garbage collected."""
    
    def __init__(self):
        self._data: Dict[K, weakref.ref] = {}
        self._lock = threading.RLock()
        self.logger = logging.getLogger(__name__)
    
    def __setitem__(self, key: K, value: V) -> None:
        with self._lock:
            def cleanup(ref):
                with self._lock:
                    if key in self._data and self._data[key] is ref:
                        del self._data[key]
            
            self._data[key] = weakref.ref(value, cleanup)
    
    def __getitem__(self, key: K) -> V:
        with self._lock:
            if key not in self._data:
                raise KeyError(key)
            
            ref = self._data[key]
            value = ref()
            if value is None:
                del self._data[key]
                raise KeyError(key)
            
            return value
    
    def get(self, key: K, default: Optional[V] = None) -> Optional[V]:
        try:
            return self[key]
        except KeyError:
            return default
    
    def __contains__(self, key: K) -> bool:
        with self._lock:
            if key not in self._data:
                return False
            
            ref = self._data[key]
            if ref() is None:
                del self._data[key]
                return False
            
            return True
    
    def __len__(self) -> int:
        with self._lock:
            # Clean up dead references
            dead_keys = []
            for key, ref in self._data.items():
                if ref() is None:
                    dead_keys.append(key)
            
            for key in dead_keys:
                del self._data[key]
            
            return len(self._data)


class UETrackingDict(LRUDict[str, V]):
    """Specialized LRU dict for tracking UE data with reasonable defaults."""
    
    def __init__(self, max_ues: int = 10000, ue_ttl_hours: float = 24.0):
        super().__init__(
            max_size=max_ues,
            ttl_seconds=ue_ttl_hours * 3600,  # Convert hours to seconds
            cleanup_interval=300.0  # Clean up every 5 minutes
        )
        self.logger = logging.getLogger(__name__)
    
    def log_stats(self) -> None:
        """Log cache statistics."""
        stats = self.get_stats()
        self.logger.info(
            "UE Tracking Stats - Size: %d/%d, Hit Rate: %.2f%%, "
            "Evictions: %d, Expiries: %d",
            stats["size"], stats["max_size"], stats["hit_rate"] * 100,
            stats["evictions"], stats["ttl_expiries"]
        )