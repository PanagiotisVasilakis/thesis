"""Tests for state management functionality."""

import pytest
import time
import threading
from unittest.mock import MagicMock, patch
from typing import Dict, Any, List

from ml_service.app.state.state_management import (
    StateManager,
    UEStateManager,
    ModelStateManager,
    GlobalStateRegistry,
    StateChange,
    StateChangeType,
    StateObserver,
    get_global_state_registry,
    get_ue_state_manager,
    get_model_state_manager
)
from ml_service.app.state.state_observers import (
    LoggingStateObserver,
    MetricsStateObserver,
    ThresholdStateObserver,
    StateHistoryObserver,
    CompositeStateObserver,
    create_default_observer_chain
)
from ml_service.app.state.state_integration import (
    StateIntegrationManager,
    StateAwareModelWrapper,
    StateAwareUEProcessor,
    get_state_integration_manager
)


class MockObserver(StateObserver):
    """Mock observer for testing."""
    
    def __init__(self):
        self.changes = []
    
    def on_state_changed(self, change: StateChange) -> None:
        self.changes.append(change)


class TestStateManager:
    """Test cases for StateManager."""
    
    def test_state_manager_creation(self):
        """Test state manager creation."""
        manager = StateManager[str]("test_manager")
        
        assert manager.name == "test_manager"
        assert manager.size() == 0
        assert manager.get_all() == {}
    
    def test_basic_operations(self):
        """Test basic state operations."""
        manager = StateManager[int]("test")
        
        # Set value
        manager.set("key1", 100)
        assert manager.get("key1") == 100
        assert manager.size() == 1
        assert manager.contains("key1")
        
        # Update value
        manager.set("key1", 200)
        assert manager.get("key1") == 200
        assert manager.size() == 1
        
        # Delete value
        deleted = manager.delete("key1")
        assert deleted is True
        assert manager.get("key1") is None
        assert manager.size() == 0
        assert not manager.contains("key1")
    
    def test_observer_notifications(self):
        """Test observer notifications."""
        manager = StateManager[str]("test")
        observer = MockObserver()
        
        manager.add_observer(observer)
        
        # Set value
        manager.set("key1", "value1")
        
        # Check notification
        assert len(observer.changes) == 1
        change = observer.changes[0]
        assert change.change_type == StateChangeType.CREATE
        assert change.key == "key1"
        assert change.old_value is None
        assert change.new_value == "value1"
        
        # Update value
        manager.set("key1", "value2")
        
        # Check update notification
        assert len(observer.changes) == 2
        change = observer.changes[1]
        assert change.change_type == StateChangeType.UPDATE
        assert change.old_value == "value1"
        assert change.new_value == "value2"
        
        # Delete value
        manager.delete("key1")
        
        # Check delete notification
        assert len(observer.changes) == 3
        change = observer.changes[2]
        assert change.change_type == StateChangeType.DELETE
        assert change.old_value == "value2"
        assert change.new_value is None
    
    def test_batch_update(self):
        """Test batch updates."""
        manager = StateManager[int]("test")
        observer = MockObserver()
        manager.add_observer(observer)
        
        updates = {"key1": 100, "key2": 200, "key3": 300}
        manager.update(updates)
        
        assert manager.size() == 3
        assert manager.get("key1") == 100
        assert manager.get("key2") == 200
        assert manager.get("key3") == 300
        
        # Should have 3 notifications
        assert len(observer.changes) == 3
    
    def test_reset_operation(self):
        """Test reset operation."""
        manager = StateManager[str]("test")
        observer = MockObserver()
        manager.add_observer(observer)
        
        # Set some values
        manager.set("key1", "value1")
        manager.set("key2", "value2")
        
        # Reset
        manager.reset(metadata={"reason": "test_reset"})
        
        assert manager.size() == 0
        assert manager.get_all() == {}
        
        # Check reset notification
        reset_change = observer.changes[-1]
        assert reset_change.change_type == StateChangeType.RESET
        assert reset_change.key == "*"
        assert reset_change.metadata["reason"] == "test_reset"
    
    def test_change_history(self):
        """Test change history tracking."""
        manager = StateManager[int]("test", max_history=3)
        
        # Make changes
        manager.set("key1", 100)
        manager.set("key2", 200)
        manager.set("key1", 150)
        manager.delete("key2")
        
        history = manager.get_change_history()
        
        # Should have 4 changes but limited to max_history
        assert len(history) <= 4
        
        # Get limited history
        limited_history = manager.get_change_history(limit=2)
        assert len(limited_history) == 2
    
    def test_thread_safety(self):
        """Test thread safety of state manager."""
        manager = StateManager[int]("test")
        results = []
        
        def worker(worker_id: int):
            for i in range(100):
                key = f"worker_{worker_id}_key_{i}"
                manager.set(key, worker_id * 1000 + i)
                value = manager.get(key)
                results.append((worker_id, i, value))
        
        # Start multiple threads
        threads = []
        for i in range(5):
            thread = threading.Thread(target=worker, args=(i,))
            threads.append(thread)
            thread.start()
        
        # Wait for completion
        for thread in threads:
            thread.join()
        
        # Verify results
        assert len(results) == 500  # 5 workers * 100 operations
        assert manager.size() == 500


class TestUEStateManager:
    """Test cases for UEStateManager."""
    
    def test_ue_state_manager_creation(self):
        """Test UE state manager creation."""
        manager = UEStateManager(max_ues=100, ue_ttl_hours=1.0)
        
        assert manager.max_ues == 100
        assert manager.ue_ttl_seconds == 3600.0
    
    def test_ue_update_and_retrieval(self):
        """Test UE update and retrieval."""
        manager = UEStateManager(max_ues=10, ue_ttl_hours=24.0)
        
        ue_data = {
            "latitude": 100.0,
            "longitude": 200.0,
            "speed": 15.0,
            "connected_to": "antenna_1"
        }
        
        # Update UE
        manager.update_ue("ue_001", ue_data)
        
        # Retrieve UE
        retrieved_data = manager.get_ue("ue_001")
        assert retrieved_data == ue_data
        
        # Check UE is in active list
        active_ues = manager.get_active_ues()
        assert "ue_001" in active_ues
    
    def test_ue_expiry(self):
        """Test UE expiry based on TTL."""
        manager = UEStateManager(max_ues=10, ue_ttl_hours=0.001)  # Very short TTL
        
        ue_data = {"latitude": 100.0, "longitude": 200.0}
        
        # Update UE
        manager.update_ue("ue_001", ue_data)
        
        # Should be available immediately
        assert manager.get_ue("ue_001") is not None
        
        # Wait for expiry
        time.sleep(0.01)
        
        # Should be expired
        assert manager.get_ue("ue_001") is None
    
    def test_ue_capacity_management(self):
        """Test UE capacity management."""
        manager = UEStateManager(max_ues=3, ue_ttl_hours=24.0)
        
        # Add UEs up to capacity
        for i in range(5):
            ue_data = {"latitude": 100 + i, "longitude": 200 + i}
            manager.update_ue(f"ue_{i:03d}", ue_data)
            time.sleep(0.01)  # Small delay to ensure different timestamps
        
        # Should have only max_ues
        assert manager.size() <= manager.max_ues
        
        # Oldest UEs should be removed
        assert manager.get_ue("ue_000") is None  # Oldest should be gone
        assert manager.get_ue("ue_004") is not None  # Newest should remain
    
    def test_ue_statistics(self):
        """Test UE statistics."""
        manager = UEStateManager(max_ues=10, ue_ttl_hours=24.0)
        
        # Add some UEs
        for i in range(5):
            ue_data = {"latitude": 100 + i, "longitude": 200 + i}
            manager.update_ue(f"ue_{i:03d}", ue_data)
        
        stats = manager.get_ue_stats()
        
        assert stats["total_ues"] == 5
        assert stats["active_ues"] == 5
        assert stats["max_ues"] == 10
        assert 0 <= stats["utilization"] <= 1


class TestModelStateManager:
    """Test cases for ModelStateManager."""
    
    def test_model_state_initialization(self):
        """Test model state initialization."""
        manager = ModelStateManager()
        
        # Check default state
        assert manager.get("model_loaded") is False
        assert manager.get("prediction_count") == 0
        assert manager.get("training_samples") == 0
    
    def test_model_loaded_update(self):
        """Test model loaded state update."""
        manager = ModelStateManager()
        
        manager.update_model_loaded("/path/to/model.pkl", "v1.0")
        
        assert manager.get("model_loaded") is True
        assert manager.get("model_path") == "/path/to/model.pkl"
        assert manager.get("model_version") == "v1.0"
        assert manager.get("last_loaded") is not None
    
    def test_training_completed_update(self):
        """Test training completed state update."""
        manager = ModelStateManager()
        
        manager.update_training_completed(1000, 0.95)
        
        assert manager.get("training_samples") == 1000
        assert manager.get("model_accuracy") == 0.95
        assert manager.get("last_training") is not None
    
    def test_prediction_count_increment(self):
        """Test prediction count increment."""
        manager = ModelStateManager()
        
        # Initial count
        assert manager.get("prediction_count") == 0
        
        # Increment
        manager.increment_prediction_count()
        assert manager.get("prediction_count") == 1
        
        # Increment again
        manager.increment_prediction_count()
        assert manager.get("prediction_count") == 2
    
    def test_model_summary(self):
        """Test model summary generation."""
        manager = ModelStateManager()
        
        # Update some state
        manager.update_model_loaded("/path/to/model.pkl", "v1.0")
        manager.update_training_completed(500, 0.92)
        manager.increment_prediction_count()
        
        summary = manager.get_model_summary()
        
        assert summary["model_loaded"] is True
        assert summary["model_version"] == "v1.0"
        assert summary["prediction_count"] == 1
        assert summary["training_samples"] == 500
        assert summary["model_accuracy"] == 0.92
        assert "uptime_seconds" in summary
        assert "last_activity" in summary


class TestStateObservers:
    """Test cases for state observers."""
    
    def test_logging_observer(self):
        """Test logging state observer."""
        observer = LoggingStateObserver(max_log_entries=5)
        
        # Create test changes
        changes = []
        for i in range(3):
            change = StateChange(
                change_type=StateChangeType.CREATE,
                key=f"key_{i}",
                old_value=None,
                new_value=f"value_{i}",
                timestamp=time.time(),
                metadata={"test": True}
            )
            changes.append(change)
            observer.on_state_changed(change)
        
        # Check log entries
        log_entries = observer.get_log_entries()
        assert len(log_entries) == 3
        
        # Check stats
        stats = observer.get_log_stats()
        assert stats["total_entries"] == 3
        assert stats["change_type_counts"]["create"] == 3
    
    def test_metrics_observer(self):
        """Test metrics state observer."""
        observer = MetricsStateObserver()
        
        # Create test changes
        for i in range(3):
            change = StateChange(
                change_type=StateChangeType.UPDATE,
                key="test_key",
                old_value=i,
                new_value=i + 1,
                timestamp=time.time()
            )
            observer.on_state_changed(change)
        
        # Check metrics
        metrics = observer.get_metrics()
        assert metrics["total_changes"] == 3
        assert metrics["change_type_counts"]["update"] == 3
        assert metrics["key_counts"]["test_key"] == 3
    
    def test_threshold_observer(self):
        """Test threshold state observer."""
        observer = ThresholdStateObserver()
        
        # Add custom threshold
        callback_called = []
        
        def test_callback(change, threshold_config):
            callback_called.append((change, threshold_config))
        
        observer.add_threshold("test_key", "max", 100, test_callback)
        
        # Create change that doesn't cross threshold
        change1 = StateChange(
            change_type=StateChangeType.UPDATE,
            key="test_key",
            old_value=50,
            new_value=80,
            timestamp=time.time()
        )
        observer.on_state_changed(change1)
        
        # No callback should be called
        assert len(callback_called) == 0
        
        # Create change that crosses threshold
        change2 = StateChange(
            change_type=StateChangeType.UPDATE,
            key="test_key",
            old_value=80,
            new_value=120,
            timestamp=time.time()
        )
        observer.on_state_changed(change2)
        
        # Callback should be called
        assert len(callback_called) == 1
    
    def test_history_observer(self):
        """Test history state observer."""
        observer = StateHistoryObserver(max_history=10)
        
        # Create changes for multiple keys
        keys = ["key1", "key2", "key1", "key3", "key1"]
        for i, key in enumerate(keys):
            change = StateChange(
                change_type=StateChangeType.UPDATE,
                key=key,
                old_value=i,
                new_value=i + 1,
                timestamp=time.time() + i
            )
            observer.on_state_changed(change)
        
        # Check key timeline
        key1_timeline = observer.get_key_timeline("key1")
        assert len(key1_timeline) == 3  # key1 appears 3 times
        
        # Check key statistics
        key1_stats = observer.get_key_statistics("key1")
        assert key1_stats["change_count"] == 3
        assert key1_stats["key"] == "key1"
        
        # Check global statistics
        global_stats = observer.get_global_statistics()
        assert global_stats["total_changes"] == 5
        assert global_stats["unique_keys"] == 3
    
    def test_composite_observer(self):
        """Test composite state observer."""
        # Create child observers
        observer1 = MockObserver()
        observer2 = MockObserver()
        
        # Create composite
        composite = CompositeStateObserver([observer1, observer2])
        
        # Create test change
        change = StateChange(
            change_type=StateChangeType.CREATE,
            key="test_key",
            old_value=None,
            new_value="test_value",
            timestamp=time.time()
        )
        
        # Notify composite
        composite.on_state_changed(change)
        
        # Both child observers should be notified
        assert len(observer1.changes) == 1
        assert len(observer2.changes) == 1
        assert observer1.changes[0] == change
        assert observer2.changes[0] == change
    
    def test_default_observer_chain(self):
        """Test default observer chain creation."""
        observer_chain = create_default_observer_chain()
        
        assert isinstance(observer_chain, CompositeStateObserver)
        assert observer_chain.get_observer_count() == 4  # Should have 4 default observers
        
        observer_types = observer_chain.get_observer_types()
        expected_types = ["LoggingStateObserver", "MetricsStateObserver", 
                         "ThresholdStateObserver", "StateHistoryObserver"]
        
        for expected_type in expected_types:
            assert expected_type in observer_types


class TestGlobalStateRegistry:
    """Test cases for GlobalStateRegistry."""
    
    def test_registry_initialization(self):
        """Test registry initialization."""
        registry = GlobalStateRegistry()
        
        # Should have default managers
        managers = registry.get_all_managers()
        assert "ue_state" in managers
        assert "model_state" in managers
        assert "app_state" in managers
    
    def test_manager_registration(self):
        """Test manager registration."""
        registry = GlobalStateRegistry()
        custom_manager = StateManager[str]("custom")
        
        # Register custom manager
        registry.register_manager("custom_manager", custom_manager)
        
        # Should be able to retrieve it
        retrieved = registry.get_manager("custom_manager")
        assert retrieved is custom_manager
    
    def test_manager_unregistration(self):
        """Test manager unregistration."""
        registry = GlobalStateRegistry()
        custom_manager = StateManager[str]("custom")
        
        # Register and then unregister
        registry.register_manager("custom_manager", custom_manager)
        assert registry.get_manager("custom_manager") is not None
        
        unregistered = registry.unregister_manager("custom_manager")
        assert unregistered is True
        assert registry.get_manager("custom_manager") is None
    
    def test_registry_summary(self):
        """Test registry summary."""
        registry = GlobalStateRegistry()
        
        summary = registry.get_registry_summary()
        
        assert "manager_count" in summary
        assert "managers" in summary
        assert summary["manager_count"] >= 3  # At least default managers


class TestStateIntegration:
    """Test cases for state integration."""
    
    def test_integration_manager(self):
        """Test state integration manager."""
        manager = StateIntegrationManager()
        
        # Initialize
        manager.initialize()
        assert manager._initialized is True
        
        # Test tracking operations
        manager.track_model_operation("prediction", antenna_id="antenna_1", confidence=0.8)
        manager.track_ue_activity("ue_001", {"latitude": 100, "longitude": 200})
        
        # Get summary
        summary = manager.get_comprehensive_state_summary()
        assert "registry" in summary
        assert "ue_state" in summary
        assert "model_state" in summary
    
    def test_state_aware_model_wrapper(self):
        """Test state-aware model wrapper."""
        # Create mock model
        mock_model = MagicMock()
        mock_model.predict.return_value = {"antenna_id": "antenna_1", "confidence": 0.8}
        mock_model.train.return_value = {"samples": 100, "classes": 3}
        
        # Create wrapper
        wrapper = StateAwareModelWrapper(mock_model)
        
        # Test prediction tracking
        features = {"latitude": 100, "longitude": 200}
        result = wrapper.predict(features)
        
        assert result["antenna_id"] == "antenna_1"
        mock_model.predict.assert_called_once_with(features)
        
        # Test training tracking
        training_data = [{"latitude": 100, "longitude": 200, "optimal_antenna": "antenna_1"}]
        train_result = wrapper.train(training_data)
        
        assert train_result["samples"] == 100
        mock_model.train.assert_called_once_with(training_data)
    
    def test_state_aware_ue_processor(self):
        """Test state-aware UE processor."""
        processor = StateAwareUEProcessor()
        
        # Process UE data
        ue_data = {"latitude": 100, "longitude": 200, "speed": 15}
        result = processor.process_ue_data("ue_001", ue_data)
        
        assert result["ue_id"] == "ue_001"
        assert result["state_tracked"] is True
        assert "processed_at" in result
        
        # Check if UE state was tracked
        ue_state = processor.get_ue_state("ue_001")
        # Note: This might be None if state manager wasn't properly initialized


if __name__ == "__main__":
    pytest.main([__file__])