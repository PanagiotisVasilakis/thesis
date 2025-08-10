"""Async model operations for non-blocking inference and training."""

import asyncio
import logging
import threading
import time
import concurrent.futures
from typing import Any, Dict, List, Optional, Callable, Union, Tuple
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
import queue
import weakref

import numpy as np

from ..utils.exception_handler import ModelError, safe_execute, ErrorSeverity
from ..utils.resource_manager import global_resource_manager, ResourceType
from ..config.constants import env_constants


logger = logging.getLogger(__name__)


class ModelOperationType(Enum):
    """Types of model operations."""
    PREDICT = "predict"
    TRAIN = "train"
    EVALUATE = "evaluate"
    SAVE = "save"
    LOAD = "load"


class ModelOperationStatus(Enum):
    """Status of model operations."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ModelOperation:
    """Represents a model operation request."""
    operation_id: str
    operation_type: ModelOperationType
    data: Any
    created_at: float
    status: ModelOperationStatus = ModelOperationStatus.PENDING
    result: Optional[Any] = None
    error: Optional[str] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    
    @property
    def duration(self) -> Optional[float]:
        """Get operation duration in seconds."""
        if self.started_at and self.completed_at:
            return self.completed_at - self.started_at
        return None
    
    @property
    def total_time(self) -> float:
        """Get total time since creation."""
        end_time = self.completed_at or time.time()
        return end_time - self.created_at


class AsyncModelInterface(ABC):
    """Abstract interface for async model operations."""
    
    @abstractmethod
    async def predict_async(self, features: Dict[str, Any]) -> Dict[str, Any]:
        """Perform async prediction."""
        pass
    
    @abstractmethod
    async def train_async(self, training_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Perform async training."""
        pass
    
    @abstractmethod
    async def evaluate_async(self, test_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Perform async evaluation."""
        pass


class ModelOperationQueue:
    """Thread-safe queue for model operations with prioritization."""
    
    def __init__(self, max_size: int = 1000):
        self.max_size = max_size
        self._queue = queue.PriorityQueue(maxsize=max_size)
        self._operations: Dict[str, ModelOperation] = {}
        self._lock = threading.RLock()
        self._stats = {
            "total_submitted": 0,
            "total_completed": 0,
            "total_failed": 0,
            "total_cancelled": 0
        }
    
    def submit(self, operation: ModelOperation, priority: int = 5) -> bool:
        """Submit operation to queue with priority (lower = higher priority)."""
        try:
            with self._lock:
                if len(self._operations) >= self.max_size:
                    logger.warning("Operation queue full, rejecting operation %s", operation.operation_id)
                    return False
                
                # Store operation
                self._operations[operation.operation_id] = operation
                self._stats["total_submitted"] += 1
                
                # Add to priority queue
                self._queue.put((priority, operation.created_at, operation.operation_id))
                
                logger.debug("Submitted operation %s with priority %d", operation.operation_id, priority)
                return True
                
        except queue.Full:
            logger.warning("Failed to submit operation %s: queue full", operation.operation_id)
            return False
    
    def get_next(self, timeout: Optional[float] = None) -> Optional[ModelOperation]:
        """Get next operation from queue."""
        try:
            priority, created_at, operation_id = self._queue.get(timeout=timeout)
            
            with self._lock:
                operation = self._operations.get(operation_id)
                if operation and operation.status == ModelOperationStatus.PENDING:
                    operation.status = ModelOperationStatus.RUNNING
                    operation.started_at = time.time()
                    return operation
                else:
                    # Operation was cancelled or doesn't exist
                    return None
                    
        except queue.Empty:
            return None
    
    def complete_operation(self, operation_id: str, result: Any = None, error: str = None) -> None:
        """Mark operation as completed."""
        with self._lock:
            operation = self._operations.get(operation_id)
            if operation:
                operation.completed_at = time.time()
                if error:
                    operation.status = ModelOperationStatus.FAILED
                    operation.error = error
                    self._stats["total_failed"] += 1
                else:
                    operation.status = ModelOperationStatus.COMPLETED
                    operation.result = result
                    self._stats["total_completed"] += 1
    
    def cancel_operation(self, operation_id: str) -> bool:
        """Cancel a pending operation."""
        with self._lock:
            operation = self._operations.get(operation_id)
            if operation and operation.status == ModelOperationStatus.PENDING:
                operation.status = ModelOperationStatus.CANCELLED
                self._stats["total_cancelled"] += 1
                return True
            return False
    
    def get_operation(self, operation_id: str) -> Optional[ModelOperation]:
        """Get operation by ID."""
        with self._lock:
            return self._operations.get(operation_id)
    
    def cleanup_completed(self, max_age_seconds: float = 3600) -> int:
        """Clean up old completed operations."""
        current_time = time.time()
        removed_count = 0
        
        with self._lock:
            completed_ops = []
            for op_id, operation in self._operations.items():
                if (operation.status in (ModelOperationStatus.COMPLETED, ModelOperationStatus.FAILED, ModelOperationStatus.CANCELLED) and
                    current_time - operation.created_at > max_age_seconds):
                    completed_ops.append(op_id)
            
            for op_id in completed_ops:
                del self._operations[op_id]
                removed_count += 1
        
        return removed_count
    
    def get_stats(self) -> Dict[str, Any]:
        """Get queue statistics."""
        with self._lock:
            pending_count = sum(1 for op in self._operations.values() 
                              if op.status == ModelOperationStatus.PENDING)
            running_count = sum(1 for op in self._operations.values() 
                              if op.status == ModelOperationStatus.RUNNING)
            
            return {
                "queue_size": self._queue.qsize(),
                "total_operations": len(self._operations),
                "pending_count": pending_count,
                "running_count": running_count,
                **self._stats
            }


class AsyncModelWorker:
    """Worker thread for processing model operations asynchronously."""
    
    def __init__(self, 
                 worker_id: str,
                 operation_queue: ModelOperationQueue,
                 executor: concurrent.futures.ThreadPoolExecutor):
        self.worker_id = worker_id
        self.operation_queue = operation_queue
        self.executor = executor
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._operations_processed = 0
        self._last_operation_time = 0.0
        
    def start(self) -> None:
        """Start the worker thread."""
        if self._running:
            return
        
        self._running = True
        self._thread = threading.Thread(
            target=self._worker_loop,
            name=f"ModelWorker-{self.worker_id}",
            daemon=True
        )
        self._thread.start()
        logger.info("Started async model worker %s", self.worker_id)
    
    def stop(self, timeout: float = 10.0) -> None:
        """Stop the worker thread."""
        if not self._running:
            return
        
        self._running = False
        if self._thread:
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                logger.warning("Worker %s did not stop within timeout", self.worker_id)
            else:
                logger.info("Stopped async model worker %s", self.worker_id)
    
    def _worker_loop(self) -> None:
        """Main worker loop."""
        logger.info("Model worker %s started", self.worker_id)
        
        while self._running:
            try:
                # Get next operation
                operation = self.operation_queue.get_next(timeout=1.0)
                if not operation:
                    continue
                
                logger.debug("Worker %s processing operation %s", 
                           self.worker_id, operation.operation_id)
                
                # Process operation
                self._process_operation(operation)
                self._operations_processed += 1
                self._last_operation_time = time.time()
                
            except Exception as e:
                logger.error("Error in worker %s: %s", self.worker_id, e)
                time.sleep(1.0)  # Brief pause on error
        
        logger.info("Model worker %s stopped", self.worker_id)
    
    def _process_operation(self, operation: ModelOperation) -> None:
        """Process a single model operation."""
        try:
            if operation.operation_type == ModelOperationType.PREDICT:
                result = self._execute_prediction(operation.data)
            elif operation.operation_type == ModelOperationType.TRAIN:
                result = self._execute_training(operation.data)
            elif operation.operation_type == ModelOperationType.EVALUATE:
                result = self._execute_evaluation(operation.data)
            else:
                raise ValueError(f"Unsupported operation type: {operation.operation_type}")
            
            self.operation_queue.complete_operation(operation.operation_id, result=result)
            
        except Exception as e:
            error_msg = str(e)
            logger.error("Operation %s failed: %s", operation.operation_id, error_msg)
            self.operation_queue.complete_operation(operation.operation_id, error=error_msg)
    
    def _execute_prediction(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute prediction operation."""
        model = data.get("model")
        features = data.get("features")
        
        if not model or not features:
            raise ValueError("Missing model or features for prediction")
        
        # Use executor for CPU-intensive prediction
        future = self.executor.submit(model.predict, features)
        result = future.result(timeout=env_constants.MODEL_PREDICTION_TIMEOUT)
        
        return result
    
    def _execute_training(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute training operation."""
        model = data.get("model")
        training_data = data.get("training_data")
        
        if not model or not training_data:
            raise ValueError("Missing model or training data")
        
        # Use executor for CPU-intensive training
        future = self.executor.submit(model.train, training_data)
        result = future.result(timeout=env_constants.MODEL_TRAINING_TIMEOUT)
        
        return result
    
    def _execute_evaluation(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute evaluation operation."""
        model = data.get("model")
        test_data = data.get("test_data")
        
        if not model or not test_data:
            raise ValueError("Missing model or test data")
        
        # Implement evaluation logic here
        # For now, return basic stats
        return {
            "samples_evaluated": len(test_data),
            "evaluation_time": time.time()
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """Get worker statistics."""
        return {
            "worker_id": self.worker_id,
            "operations_processed": self._operations_processed,
            "last_operation_time": self._last_operation_time,
            "is_running": self._running
        }


class AsyncModelManager:
    """Manager for async model operations with worker pool."""
    
    def __init__(self, 
                 max_workers: int = None,
                 max_queue_size: int = 1000,
                 operation_timeout: float = 300.0):
        """Initialize async model manager.
        
        Args:
            max_workers: Maximum number of worker threads
            max_queue_size: Maximum size of operation queue
            operation_timeout: Default timeout for operations
        """
        if max_workers is None:
            max_workers = env_constants.ASYNC_MODEL_WORKERS
        
        self.max_workers = max_workers
        self.operation_timeout = operation_timeout
        
        # Initialize components
        self.operation_queue = ModelOperationQueue(max_size=max_queue_size)
        self.executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="AsyncModel"
        )
        
        # Worker management
        self.workers: List[AsyncModelWorker] = []
        self._next_operation_id = 0
        self._operation_id_lock = threading.Lock()
        
        # Register with resource manager
        self._resource_id = global_resource_manager.register_resource(
            self,
            ResourceType.OTHER,
            cleanup_method=self.shutdown,
            metadata={
                "component": "AsyncModelManager",
                "max_workers": max_workers,
                "queue_size": max_queue_size
            }
        )
        
        # Start workers
        self._start_workers()
        
        logger.info("Initialized AsyncModelManager with %d workers", max_workers)
    
    def _start_workers(self) -> None:
        """Start worker threads."""
        for i in range(self.max_workers):
            worker = AsyncModelWorker(
                worker_id=f"worker-{i}",
                operation_queue=self.operation_queue,
                executor=self.executor
            )
            worker.start()
            self.workers.append(worker)
    
    def _generate_operation_id(self) -> str:
        """Generate unique operation ID."""
        with self._operation_id_lock:
            self._next_operation_id += 1
            return f"op_{self._next_operation_id}_{int(time.time() * 1000)}"
    
    async def predict_async(self, 
                           model: Any, 
                           features: Dict[str, Any],
                           priority: int = 5,
                           timeout: Optional[float] = None) -> Dict[str, Any]:
        """Submit async prediction request."""
        operation_id = self._generate_operation_id()
        operation = ModelOperation(
            operation_id=operation_id,
            operation_type=ModelOperationType.PREDICT,
            data={"model": model, "features": features},
            created_at=time.time()
        )
        
        if not self.operation_queue.submit(operation, priority):
            raise ModelError("Failed to submit prediction operation: queue full")
        
        # Wait for completion
        return await self._wait_for_operation(operation_id, timeout or self.operation_timeout)
    
    async def train_async(self,
                         model: Any,
                         training_data: List[Dict[str, Any]],
                         priority: int = 3,  # Higher priority for training
                         timeout: Optional[float] = None) -> Dict[str, Any]:
        """Submit async training request."""
        operation_id = self._generate_operation_id()
        operation = ModelOperation(
            operation_id=operation_id,
            operation_type=ModelOperationType.TRAIN,
            data={"model": model, "training_data": training_data},
            created_at=time.time()
        )
        
        if not self.operation_queue.submit(operation, priority):
            raise ModelError("Failed to submit training operation: queue full")
        
        # Wait for completion
        return await self._wait_for_operation(operation_id, timeout or self.operation_timeout)
    
    async def evaluate_async(self,
                            model: Any,
                            test_data: List[Dict[str, Any]],
                            priority: int = 7,  # Lower priority for evaluation
                            timeout: Optional[float] = None) -> Dict[str, Any]:
        """Submit async evaluation request."""
        operation_id = self._generate_operation_id()
        operation = ModelOperation(
            operation_id=operation_id,
            operation_type=ModelOperationType.EVALUATE,
            data={"model": model, "test_data": test_data},
            created_at=time.time()
        )
        
        if not self.operation_queue.submit(operation, priority):
            raise ModelError("Failed to submit evaluation operation: queue full")
        
        # Wait for completion
        return await self._wait_for_operation(operation_id, timeout or self.operation_timeout)
    
    async def _wait_for_operation(self, operation_id: str, timeout: float) -> Dict[str, Any]:
        """Wait for operation to complete and return result."""
        start_time = time.time()
        poll_interval = 0.1  # Poll every 100ms
        
        while time.time() - start_time < timeout:
            operation = self.operation_queue.get_operation(operation_id)
            if not operation:
                raise ModelError(f"Operation {operation_id} not found")
            
            if operation.status == ModelOperationStatus.COMPLETED:
                return operation.result
            elif operation.status == ModelOperationStatus.FAILED:
                raise ModelError(f"Operation {operation_id} failed: {operation.error}")
            elif operation.status == ModelOperationStatus.CANCELLED:
                raise ModelError(f"Operation {operation_id} was cancelled")
            
            # Wait before next poll
            await asyncio.sleep(poll_interval)
        
        # Timeout - cancel operation
        self.operation_queue.cancel_operation(operation_id)
        raise ModelError(f"Operation {operation_id} timed out after {timeout} seconds")
    
    def submit_operation_sync(self,
                             operation_type: ModelOperationType,
                             data: Dict[str, Any],
                             priority: int = 5) -> str:
        """Submit operation synchronously and return operation ID."""
        operation_id = self._generate_operation_id()
        operation = ModelOperation(
            operation_id=operation_id,
            operation_type=operation_type,
            data=data,
            created_at=time.time()
        )
        
        if not self.operation_queue.submit(operation, priority):
            raise ModelError("Failed to submit operation: queue full")
        
        return operation_id
    
    def get_operation_status(self, operation_id: str) -> Optional[Dict[str, Any]]:
        """Get status of operation."""
        operation = self.operation_queue.get_operation(operation_id)
        if not operation:
            return None
        
        return {
            "operation_id": operation.operation_id,
            "operation_type": operation.operation_type.value,
            "status": operation.status.value,
            "created_at": operation.created_at,
            "started_at": operation.started_at,
            "completed_at": operation.completed_at,
            "duration": operation.duration,
            "total_time": operation.total_time,
            "error": operation.error
        }
    
    def cleanup_operations(self, max_age_seconds: float = 3600) -> int:
        """Clean up old completed operations."""
        return self.operation_queue.cleanup_completed(max_age_seconds)
    
    def get_comprehensive_stats(self) -> Dict[str, Any]:
        """Get comprehensive statistics."""
        queue_stats = self.operation_queue.get_stats()
        worker_stats = [worker.get_stats() for worker in self.workers]
        
        return {
            "manager": {
                "max_workers": self.max_workers,
                "operation_timeout": self.operation_timeout,
                "active_workers": len([w for w in self.workers if w._running])
            },
            "queue": queue_stats,
            "workers": worker_stats,
            "executor": {
                "max_workers": self.executor._max_workers,
                "threads": len(self.executor._threads)
            }
        }
    
    def shutdown(self, timeout: float = 30.0) -> None:
        """Shutdown the async model manager."""
        logger.info("Shutting down AsyncModelManager...")
        
        # Stop workers
        for worker in self.workers:
            worker.stop(timeout=timeout / len(self.workers))
        
        # Shutdown executor
        self.executor.shutdown(wait=True, timeout=timeout)
        
        # Unregister from resource manager
        if hasattr(self, '_resource_id') and self._resource_id:
            global_resource_manager.unregister_resource(self._resource_id, force_cleanup=False)
        
        logger.info("AsyncModelManager shutdown complete")


# Global async model manager instance
_global_async_model_manager: Optional[AsyncModelManager] = None


def get_async_model_manager() -> AsyncModelManager:
    """Get or create the global async model manager."""
    global _global_async_model_manager
    
    if _global_async_model_manager is None:
        _global_async_model_manager = AsyncModelManager()
    
    return _global_async_model_manager


# Convenience functions for async operations
async def predict_async(model: Any, features: Dict[str, Any], **kwargs) -> Dict[str, Any]:
    """Convenience function for async prediction."""
    manager = get_async_model_manager()
    return await manager.predict_async(model, features, **kwargs)


async def train_async(model: Any, training_data: List[Dict[str, Any]], **kwargs) -> Dict[str, Any]:
    """Convenience function for async training."""
    manager = get_async_model_manager()
    return await manager.train_async(model, training_data, **kwargs)


async def evaluate_async(model: Any, test_data: List[Dict[str, Any]], **kwargs) -> Dict[str, Any]:
    """Convenience function for async evaluation."""
    manager = get_async_model_manager()
    return await manager.evaluate_async(model, test_data, **kwargs)