"""Tests for async model operations functionality."""

import pytest
import asyncio
import time
from unittest.mock import MagicMock, patch

from ml_service.app.models.async_model_operations import (
    AsyncModelManager,
    ModelOperation,
    ModelOperationType,
    ModelOperationStatus,
    ModelOperationQueue,
    AsyncModelWorker,
    get_async_model_manager,
    predict_async,
    train_async,
    evaluate_async
)
from ml_service.app.models.antenna_selector import AntennaSelector
from ml_service.app.utils.exception_handler import ModelError


class TestModelOperation:
    """Test cases for ModelOperation."""
    
    def test_operation_creation(self):
        """Test model operation creation."""
        operation = ModelOperation(
            operation_id="test_op_1",
            operation_type=ModelOperationType.PREDICT,
            data={"model": "test", "features": {"x": 1}},
            created_at=time.time()
        )
        
        assert operation.operation_id == "test_op_1"
        assert operation.operation_type == ModelOperationType.PREDICT
        assert operation.status == ModelOperationStatus.PENDING
        assert operation.result is None
        assert operation.error is None
    
    def test_operation_duration(self):
        """Test operation duration calculation."""
        operation = ModelOperation(
            operation_id="test_op_1",
            operation_type=ModelOperationType.PREDICT,
            data={},
            created_at=time.time()
        )
        
        # No duration before completion
        assert operation.duration is None
        
        # Set timing
        operation.started_at = time.time()
        time.sleep(0.01)
        operation.completed_at = time.time()
        
        # Should have positive duration
        assert operation.duration > 0
        assert operation.duration < 1.0
    
    def test_operation_total_time(self):
        """Test total time calculation."""
        start_time = time.time()
        operation = ModelOperation(
            operation_id="test_op_1",
            operation_type=ModelOperationType.PREDICT,
            data={},
            created_at=start_time
        )
        
        time.sleep(0.01)
        total_time = operation.total_time
        
        assert total_time > 0
        assert total_time < 1.0


class TestModelOperationQueue:
    """Test cases for ModelOperationQueue."""
    
    def test_queue_creation(self):
        """Test queue creation."""
        queue = ModelOperationQueue(max_size=10)
        assert queue.max_size == 10
    
    def test_submit_operation(self):
        """Test operation submission."""
        queue = ModelOperationQueue(max_size=10)
        operation = ModelOperation(
            operation_id="test_op_1",
            operation_type=ModelOperationType.PREDICT,
            data={},
            created_at=time.time()
        )
        
        # Submit operation
        success = queue.submit(operation, priority=5)
        assert success is True
        
        # Check stats
        stats = queue.get_stats()
        assert stats["total_submitted"] == 1
        assert stats["pending_count"] == 1
    
    def test_get_next_operation(self):
        """Test getting next operation from queue."""
        queue = ModelOperationQueue(max_size=10)
        operation = ModelOperation(
            operation_id="test_op_1",
            operation_type=ModelOperationType.PREDICT,
            data={},
            created_at=time.time()
        )
        
        # Submit and get operation
        queue.submit(operation, priority=5)
        next_op = queue.get_next(timeout=0.1)
        
        assert next_op is not None
        assert next_op.operation_id == "test_op_1"
        assert next_op.status == ModelOperationStatus.RUNNING
    
    def test_complete_operation(self):
        """Test operation completion."""
        queue = ModelOperationQueue(max_size=10)
        operation = ModelOperation(
            operation_id="test_op_1",
            operation_type=ModelOperationType.PREDICT,
            data={},
            created_at=time.time()
        )
        
        queue.submit(operation, priority=5)
        queue.complete_operation("test_op_1", result={"antenna_id": "antenna_1"})
        
        retrieved_op = queue.get_operation("test_op_1")
        assert retrieved_op.status == ModelOperationStatus.COMPLETED
        assert retrieved_op.result == {"antenna_id": "antenna_1"}
    
    def test_cancel_operation(self):
        """Test operation cancellation."""
        queue = ModelOperationQueue(max_size=10)
        operation = ModelOperation(
            operation_id="test_op_1",
            operation_type=ModelOperationType.PREDICT,
            data={},
            created_at=time.time()
        )
        
        queue.submit(operation, priority=5)
        cancelled = queue.cancel_operation("test_op_1")
        
        assert cancelled is True
        retrieved_op = queue.get_operation("test_op_1")
        assert retrieved_op.status == ModelOperationStatus.CANCELLED
    
    def test_queue_size_limit(self):
        """Test queue size limitation."""
        queue = ModelOperationQueue(max_size=2)
        
        # Fill queue to capacity
        for i in range(3):
            operation = ModelOperation(
                operation_id=f"test_op_{i}",
                operation_type=ModelOperationType.PREDICT,
                data={},
                created_at=time.time()
            )
            success = queue.submit(operation, priority=5)
            if i < 2:
                assert success is True
            else:
                assert success is False  # Should reject third operation


class TestAsyncModelManager:
    """Test cases for AsyncModelManager."""
    
    @pytest.fixture
    def manager(self):
        """Create test async model manager."""
        return AsyncModelManager(max_workers=2, max_queue_size=10, operation_timeout=5.0)
    
    def test_manager_creation(self, manager):
        """Test manager creation."""
        assert manager.max_workers == 2
        assert manager.operation_timeout == 5.0
        assert len(manager.workers) == 2
    
    @pytest.mark.asyncio
    async def test_async_prediction(self, manager):
        """Test async prediction."""
        # Create mock model
        mock_model = MagicMock()
        mock_model.predict.return_value = {"antenna_id": "antenna_1", "confidence": 0.8}
        
        features = {"latitude": 100, "longitude": 200}
        
        # Perform async prediction
        result = await manager.predict_async(mock_model, features, timeout=1.0)
        
        assert result["antenna_id"] == "antenna_1"
        assert result["confidence"] == 0.8
    
    @pytest.mark.asyncio
    async def test_async_training(self, manager):
        """Test async training."""
        # Create mock model
        mock_model = MagicMock()
        mock_model.train.return_value = {"samples": 100, "accuracy": 0.95}
        
        training_data = [{"latitude": 100, "longitude": 200, "optimal_antenna": "antenna_1"}]
        
        # Perform async training
        result = await manager.train_async(mock_model, training_data, timeout=1.0)
        
        assert result["samples"] == 100
        assert result["accuracy"] == 0.95
    
    @pytest.mark.asyncio
    async def test_operation_timeout(self, manager):
        """Test operation timeout handling."""
        # Create mock model that takes too long
        mock_model = MagicMock()
        def slow_predict(features):
            time.sleep(2.0)  # Longer than timeout
            return {"antenna_id": "antenna_1"}
        mock_model.predict = slow_predict
        
        features = {"latitude": 100, "longitude": 200}
        
        # Should timeout
        with pytest.raises(ModelError, match="timed out"):
            await manager.predict_async(mock_model, features, timeout=0.1)
    
    def test_operation_status_tracking(self, manager):
        """Test operation status tracking."""
        operation_id = manager.submit_operation_sync(
            ModelOperationType.PREDICT,
            {"model": MagicMock(), "features": {"x": 1}},
            priority=5
        )
        
        status = manager.get_operation_status(operation_id)
        assert status is not None
        assert status["operation_type"] == "predict"
        assert status["status"] == "pending"
    
    def test_comprehensive_stats(self, manager):
        """Test comprehensive statistics."""
        stats = manager.get_comprehensive_stats()
        
        assert "manager" in stats
        assert "queue" in stats
        assert "workers" in stats
        assert "executor" in stats
        
        assert stats["manager"]["max_workers"] == 2
        assert len(stats["workers"]) == 2
    
    def test_cleanup_operations(self, manager):
        """Test operation cleanup."""
        # Submit and complete some operations
        for i in range(3):
            operation_id = manager.submit_operation_sync(
                ModelOperationType.PREDICT,
                {"model": MagicMock(), "features": {"x": i}},
                priority=5
            )
            manager.operation_queue.complete_operation(operation_id, result={"antenna_id": f"antenna_{i}"})
        
        # Clean up old operations
        removed_count = manager.cleanup_operations(max_age_seconds=0.0)  # Remove all
        assert removed_count == 3


class TestAsyncModelIntegration:
    """Integration tests for async model operations."""
    
    @pytest.mark.asyncio
    async def test_antenna_selector_async_prediction(self):
        """Test AntennaSelector async prediction."""
        # Create antenna selector with mock model
        selector = AntennaSelector()
        selector.model = MagicMock()
        selector.model.predict_proba.return_value = [[0.2, 0.8]]
        selector.model.classes_ = ["antenna_1", "antenna_2"]
        
        features = {
            "latitude": 100,
            "longitude": 200,
            "speed": 10,
            "direction_x": 0.7,
            "direction_y": 0.7,
            "heading_change_rate": 0.0,
            "path_curvature": 0.0,
            "velocity": 10.0,
            "acceleration": 0.0,
            "cell_load": 0.5,
            "handover_count": 1,
            "time_since_handover": 60.0,
            "signal_trend": 0.1,
            "environment": 0.0,
            "rsrp_stddev": 5.0,
            "sinr_stddev": 2.0,
            "rsrp_current": -80,
            "sinr_current": 15,
            "rsrq_current": -8,
            "best_rsrp_diff": 5.0,
            "best_sinr_diff": 3.0,
            "best_rsrq_diff": 2.0,
            "altitude": 100.0,
        }
        
        # Perform async prediction
        result = await selector.predict_async(features, timeout=1.0)
        
        assert "antenna_id" in result
        assert "confidence" in result
        assert result["antenna_id"] == "antenna_2"  # Higher probability
        assert result["confidence"] == 0.8
    
    @pytest.mark.asyncio
    async def test_convenience_functions(self):
        """Test convenience functions for async operations."""
        # Create mock model
        mock_model = MagicMock()
        mock_model.predict.return_value = {"antenna_id": "antenna_1", "confidence": 0.8}
        
        features = {"latitude": 100, "longitude": 200}
        
        # Test convenience function
        result = await predict_async(mock_model, features)
        
        assert result["antenna_id"] == "antenna_1"
        assert result["confidence"] == 0.8
    
    def test_global_manager_singleton(self):
        """Test global manager singleton behavior."""
        manager1 = get_async_model_manager()
        manager2 = get_async_model_manager()
        
        # Should be the same instance
        assert manager1 is manager2


class TestAsyncModelWorker:
    """Test cases for AsyncModelWorker."""
    
    def test_worker_creation(self):
        """Test worker creation."""
        queue = ModelOperationQueue(max_size=10)
        executor = MagicMock()
        
        worker = AsyncModelWorker("worker-1", queue, executor)
        
        assert worker.worker_id == "worker-1"
        assert worker.operation_queue is queue
        assert worker.executor is executor
        assert not worker._running
    
    def test_worker_stats(self):
        """Test worker statistics."""
        queue = ModelOperationQueue(max_size=10)
        executor = MagicMock()
        
        worker = AsyncModelWorker("worker-1", queue, executor)
        stats = worker.get_stats()
        
        assert stats["worker_id"] == "worker-1"
        assert stats["operations_processed"] == 0
        assert stats["is_running"] is False


if __name__ == "__main__":
    pytest.main([__file__])