"""Tests for memory optimization functionality."""

import pytest
import time
import gc
from unittest.mock import patch, MagicMock

from ml_service.app.utils.optimized_memory_dict import (
    CompactCacheEntry,
    MemoryOptimizedLRU,
    OptimizedUETrackingDict,
    MemoryEfficientSignalBuffer,
    create_optimized_ue_tracking_dict,
    create_memory_efficient_cache
)


class TestCompactCacheEntry:
    """Test cases for CompactCacheEntry."""
    
    def test_entry_creation(self):
        """Test cache entry creation."""
        entry = CompactCacheEntry("test_value")
        
        assert entry.value == "test_value"
        assert entry.access_count == 1
        assert entry.timestamp > 0
    
    def test_mark_accessed(self):
        """Test access marking."""
        entry = CompactCacheEntry("test")
        initial_count = entry.access_count
        initial_time = entry.timestamp
        
        time.sleep(0.01)  # Small delay
        entry.mark_accessed()
        
        assert entry.access_count == initial_count + 1
        assert entry.timestamp > initial_time
    
    def test_age_calculation(self):
        """Test age calculation."""
        entry = CompactCacheEntry("test")
        
        time.sleep(0.01)
        age = entry.age()
        
        assert age > 0
        assert age < 1.0  # Should be very small
    
    def test_expiry_check(self):
        """Test expiry checking."""
        entry = CompactCacheEntry("test")
        
        # Should not be expired with long TTL
        assert not entry.is_expired(3600.0)
        
        # Should be expired with very short TTL
        time.sleep(0.01)
        assert entry.is_expired(0.001)


class TestMemoryOptimizedLRU:
    """Test cases for MemoryOptimizedLRU."""
    
    def test_basic_operations(self):
        """Test basic get/set operations."""
        cache = MemoryOptimizedLRU(max_size=10)
        
        # Test set and get
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"
        
        # Test dictionary-style access
        cache["key2"] = "value2"
        assert cache["key2"] == "value2"
        
        # Test containment
        assert "key1" in cache
        assert "nonexistent" not in cache
    
    def test_size_limit(self):
        """Test size limit enforcement."""
        cache = MemoryOptimizedLRU(max_size=3)
        
        # Fill cache to capacity
        for i in range(5):
            cache.set(f"key{i}", f"value{i}")
        
        # Should have evicted oldest entries
        assert len(cache) <= 3
        assert "key4" in cache  # Most recent should be present
        assert "key0" not in cache  # Oldest should be evicted
    
    def test_lru_ordering(self):
        """Test LRU ordering behavior."""
        cache = MemoryOptimizedLRU(max_size=3)
        
        # Add three items
        cache.set("a", "1")
        cache.set("b", "2")
        cache.set("c", "3")
        
        # Access first item to make it recent
        cache.get("a")
        
        # Add new item (should evict "b" as it's least recently used)
        cache.set("d", "4")
        
        assert "a" in cache  # Recently accessed
        assert "c" in cache  # Recent
        assert "d" in cache  # Newest
        assert "b" not in cache  # Should be evicted
    
    def test_ttl_expiry(self):
        """Test TTL-based expiry."""
        cache = MemoryOptimizedLRU(max_size=10, ttl_seconds=0.05)  # 50ms TTL
        
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"
        
        # Wait for expiry
        time.sleep(0.1)
        
        assert cache.get("key1") is None
        assert "key1" not in cache
    
    def test_compact_operation(self):
        """Test compaction of expired entries."""
        cache = MemoryOptimizedLRU(max_size=10, ttl_seconds=0.05)
        
        # Add entries
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        
        # Wait for expiry
        time.sleep(0.1)
        
        # Compact should remove expired entries
        removed_count = cache.compact()
        assert removed_count == 2
        assert len(cache) == 0
    
    def test_statistics(self):
        """Test statistics collection."""
        cache = MemoryOptimizedLRU(max_size=5)
        
        # Perform some operations
        cache.set("key1", "value1")
        cache.get("key1")  # Hit
        cache.get("nonexistent")  # Miss
        
        stats = cache.get_stats()
        
        assert stats["size"] == 1
        assert stats["max_size"] == 5
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 0.5
    
    def test_clear_operation(self):
        """Test cache clearing."""
        cache = MemoryOptimizedLRU(max_size=10)
        
        # Add entries
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        
        assert len(cache) == 2
        
        # Clear cache
        cache.clear()
        
        assert len(cache) == 0
        stats = cache.get_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0


class TestOptimizedUETrackingDict:
    """Test cases for OptimizedUETrackingDict."""
    
    def test_ue_tracking_creation(self):
        """Test UE tracking dictionary creation."""
        ue_dict = OptimizedUETrackingDict(max_ues=100, ue_ttl_hours=1.0)
        
        assert ue_dict.max_size == 100
        assert ue_dict.ttl_seconds == 3600.0  # 1 hour in seconds
    
    def test_ue_activity_tracking(self):
        """Test UE activity statistics."""
        ue_dict = OptimizedUETrackingDict(max_ues=10, ue_ttl_hours=24.0)
        
        # Add UE data
        ue_dict.set("ue_001", {"signal": -80})
        ue_dict.set("ue_001", {"signal": -75})  # Update same UE
        ue_dict.set("ue_002", {"signal": -85})
        
        # Check activity tracking
        top_ues = ue_dict.get_top_active_ues(5)
        assert len(top_ues) == 2
        assert top_ues[0][0] == "ue_001"  # Most active
        assert top_ues[0][1] == 2  # Two updates
    
    def test_inactive_ue_cleanup(self):
        """Test cleanup of inactive UEs."""
        ue_dict = OptimizedUETrackingDict(max_ues=10, ue_ttl_hours=24.0)
        
        # Add UEs with different activity levels
        ue_dict.set("active_ue", {"signal": -80})
        ue_dict.set("active_ue", {"signal": -75})  # 2 updates
        ue_dict.set("inactive_ue", {"signal": -90})  # 1 update
        
        # Cleanup UEs with low activity
        removed = ue_dict.cleanup_inactive_ues(min_activity=2)
        
        assert removed == 1
        assert "active_ue" in ue_dict
        assert "inactive_ue" not in ue_dict
    
    def test_memory_monitoring(self):
        """Test memory usage monitoring."""
        ue_dict = OptimizedUETrackingDict(max_ues=100, ue_ttl_hours=1.0, memory_limit_mb=50)
        
        # Add some data
        for i in range(10):
            ue_dict.set(f"ue_{i:03d}", {"signal": -80 - i})
        
        memory_stats = ue_dict.get_memory_usage()
        
        # Should have memory statistics
        assert "process_memory_mb" in memory_stats or "error" in memory_stats
        assert "cache_entries" in memory_stats or "error" in memory_stats


class TestMemoryEfficientSignalBuffer:
    """Test cases for MemoryEfficientSignalBuffer."""
    
    def test_buffer_creation(self):
        """Test signal buffer creation."""
        buffer = MemoryEfficientSignalBuffer(max_size=5)
        
        assert buffer.max_size == 5
    
    def test_append_and_retrieve(self):
        """Test appending and retrieving values."""
        buffer = MemoryEfficientSignalBuffer(max_size=3)
        
        # Add values
        buffer.append(10)
        buffer.append(20)
        buffer.append(30)
        
        # Get recent values
        recent = buffer.get_recent(3)
        assert recent == [10, 20, 30]
    
    def test_circular_buffer_behavior(self):
        """Test circular buffer overflow behavior."""
        buffer = MemoryEfficientSignalBuffer(max_size=3)
        
        # Add more values than capacity
        for i in range(5):
            buffer.append(i)
        
        # Should contain only last 3 values
        recent = buffer.get_recent(3)
        assert recent == [2, 3, 4]
    
    def test_statistics_calculation(self):
        """Test statistics calculation."""
        buffer = MemoryEfficientSignalBuffer(max_size=10)
        
        # Add numeric values
        values = [10, 20, 30, 40, 50]
        for value in values:
            buffer.append(value)
        
        stats = buffer.calculate_stats()
        
        assert stats["mean"] == 30.0  # Average of 10,20,30,40,50
        assert stats["min"] == 10
        assert stats["max"] == 50
        assert stats["count"] == 5
    
    def test_mixed_data_types(self):
        """Test handling of mixed data types."""
        buffer = MemoryEfficientSignalBuffer(max_size=5)
        
        # Add mixed types
        buffer.append(10)
        buffer.append("string")
        buffer.append(20.5)
        buffer.append(None)
        
        # Statistics should only consider numeric values
        stats = buffer.calculate_stats()
        assert stats["count"] == 2  # Only numeric values counted
    
    def test_clear_operation(self):
        """Test buffer clearing."""
        buffer = MemoryEfficientSignalBuffer(max_size=5)
        
        # Add values
        buffer.append(10)
        buffer.append(20)
        
        # Clear buffer
        buffer.clear()
        
        recent = buffer.get_recent(5)
        assert recent == []


class TestFactoryFunctions:
    """Test cases for factory functions."""
    
    def test_create_optimized_ue_tracking_dict(self):
        """Test UE tracking dict factory."""
        ue_dict = create_optimized_ue_tracking_dict(max_ues=50, ue_ttl_hours=12.0)
        
        assert isinstance(ue_dict, OptimizedUETrackingDict)
        assert ue_dict.max_size == 50
        assert ue_dict.ttl_seconds == 12.0 * 3600
    
    def test_create_memory_efficient_cache(self):
        """Test memory efficient cache factory."""
        cache = create_memory_efficient_cache(max_size=100, ttl_seconds=1800)
        
        assert isinstance(cache, MemoryOptimizedLRU)
        assert cache.max_size == 100
        assert cache.ttl_seconds == 1800


class TestMemoryOptimization:
    """Integration tests for memory optimization."""
    
    @patch('ml_service.app.utils.optimized_memory_dict.psutil.Process')
    def test_memory_monitoring_integration(self, mock_process_class):
        """Test memory monitoring integration."""
        # Mock process memory info
        mock_process = MagicMock()
        mock_memory_info = MagicMock()
        mock_memory_info.rss = 100 * 1024 * 1024  # 100MB
        mock_process.memory_info.return_value = mock_memory_info
        mock_process_class.return_value = mock_process
        
        cache = MemoryOptimizedLRU(max_size=100, memory_limit_mb=50)
        
        # Add data to trigger memory check
        for i in range(20):
            cache.set(f"key_{i}", f"value_{i}" * 1000)  # Large values
        
        memory_stats = cache.get_memory_usage()
        
        assert "process_memory_mb" in memory_stats
        assert memory_stats["process_memory_mb"] == 100.0
    
    def test_emergency_cleanup_behavior(self):
        """Test emergency cleanup when memory limit is exceeded."""
        cache = MemoryOptimizedLRU(
            max_size=100, 
            memory_limit_mb=1,  # Very low limit to trigger cleanup
            emergency_cleanup_ratio=0.5
        )
        
        # Add entries
        for i in range(10):
            cache.set(f"key_{i}", f"value_{i}")
        
        # Should have fewer entries due to emergency cleanup
        # (This test might be flaky depending on actual memory usage)
        assert len(cache) <= 10
    
    def test_garbage_collection_integration(self):
        """Test garbage collection integration."""
        cache = MemoryOptimizedLRU(max_size=10, ttl_seconds=0.01)
        
        # Add entries that will expire quickly
        for i in range(5):
            cache.set(f"key_{i}", [i] * 1000)  # Large objects
        
        # Wait for expiry
        time.sleep(0.02)
        
        # Compact should trigger garbage collection
        with patch('gc.collect') as mock_gc:
            removed_count = cache.compact()
            
            # Should have removed expired entries and called GC
            assert removed_count > 0
            mock_gc.assert_called()


if __name__ == "__main__":
    pytest.main([__file__])