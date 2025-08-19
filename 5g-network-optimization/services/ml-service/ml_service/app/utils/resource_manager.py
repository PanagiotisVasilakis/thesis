"""Comprehensive resource management framework for the ML service."""

import asyncio
import logging
import threading
import weakref
import atexit
import gc
import time
import traceback
from typing import Any, Dict, List, Optional, Protocol, Set, Union, Callable
from contextlib import contextmanager, asynccontextmanager
from abc import ABC, abstractmethod
from enum import Enum
from dataclasses import dataclass

from ..utils.exception_handler import (
    ExceptionHandler,
    ResourceError,
    exception_context,
    safe_execute,
    ErrorSeverity
)


class ResourceType(Enum):
    """Types of resources that can be managed."""
    HTTP_SESSION = "http_session"
    DATABASE_CONNECTION = "database_connection"
    FILE_HANDLE = "file_handle"
    THREAD = "thread"
    MEMORY_BUFFER = "memory_buffer"
    CACHE = "cache"
    MODEL = "model"
    CLIENT = "client"
    OTHER = "other"


class ResourceState(Enum):
    """Resource lifecycle states."""
    CREATED = "created"
    ACTIVE = "active"
    IDLE = "idle"
    CLOSING = "closing"
    CLOSED = "closed"
    ERROR = "error"


@dataclass
class ResourceStats:
    """Statistics for tracked resources."""
    total_created: int = 0
    active_count: int = 0
    closed_count: int = 0
    error_count: int = 0
    cleanup_failures: int = 0
    memory_usage_bytes: int = 0
    longest_lifetime_seconds: float = 0.0
    average_lifetime_seconds: float = 0.0


class ManagedResource(Protocol):
    """Protocol for resources that can be managed."""
    
    def cleanup(self) -> None:
        """Clean up the resource."""
        ...
    
    def is_active(self) -> bool:
        """Check if the resource is active."""
        ...


class AsyncManagedResource(Protocol):
    """Protocol for async resources that can be managed."""
    
    async def cleanup(self) -> None:
        """Clean up the resource asynchronously."""
        ...
    
    def is_active(self) -> bool:
        """Check if the resource is active."""
        ...


@dataclass
class ResourceTracker:
    """Tracks the lifecycle of a managed resource."""
    resource_id: str
    resource_type: ResourceType
    resource: Union[ManagedResource, AsyncManagedResource, Any]
    created_at: float
    state: ResourceState
    cleanup_method: Optional[Callable] = None
    metadata: Optional[Dict[str, Any]] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
    
    @property
    def lifetime_seconds(self) -> float:
        """Get the current lifetime of the resource in seconds."""
        return time.time() - self.created_at
    
    def update_state(self, new_state: ResourceState) -> None:
        """Update the resource state."""
        self.state = new_state
        self.metadata["last_state_change"] = time.time()


class ResourceManager:
    """Comprehensive resource management with lifecycle tracking and cleanup."""
    
    def __init__(self, 
                 cleanup_interval: float = 300.0,  # 5 minutes
                 max_idle_time: float = 600.0,     # 10 minutes
                 enable_gc_monitoring: bool = True):
        """Initialize the resource manager.
        
        Args:
            cleanup_interval: Interval between automatic cleanup runs (seconds)
            max_idle_time: Maximum time a resource can remain idle before cleanup
            enable_gc_monitoring: Whether to enable garbage collection monitoring
        """
        self.cleanup_interval = cleanup_interval
        self.max_idle_time = max_idle_time
        self.enable_gc_monitoring = enable_gc_monitoring
        
        # Resource tracking
        self._resources: Dict[str, ResourceTracker] = {}
        self._resources_by_type: Dict[ResourceType, Set[str]] = {}
        self._lock = threading.RLock()
        self._stats = ResourceStats()
        
        # Cleanup management
        self._cleanup_thread: Optional[threading.Thread] = None
        self._shutdown_event = threading.Event()
        self._logger = logging.getLogger(__name__)
        
        # Weak references to track cleanup callbacks
        self._cleanup_callbacks: List[weakref.WeakMethod] = []
        
        # Register exit handler
        atexit.register(self.shutdown)
        
        # Start background cleanup if requested
        if cleanup_interval > 0:
            self.start_background_cleanup()
    
    def register_resource(self,
                         resource: Any,
                         resource_type: ResourceType,
                         resource_id: Optional[str] = None,
                         cleanup_method: Optional[Callable] = None,
                         metadata: Optional[Dict[str, Any]] = None) -> str:
        """Register a resource for management.
        
        Args:
            resource: The resource object to manage
            resource_type: Type of the resource
            resource_id: Unique identifier (auto-generated if not provided)
            cleanup_method: Custom cleanup method
            metadata: Additional metadata about the resource
            
        Returns:
            Resource ID for tracking
        """
        if resource_id is None:
            resource_id = f"{resource_type.value}_{id(resource)}_{time.time()}"
        
        tracker = ResourceTracker(
            resource_id=resource_id,
            resource_type=resource_type,
            resource=resource,
            created_at=time.time(),
            state=ResourceState.CREATED,
            cleanup_method=cleanup_method,
            metadata=metadata or {}
        )
        
        with self._lock:
            self._resources[resource_id] = tracker
            
            if resource_type not in self._resources_by_type:
                self._resources_by_type[resource_type] = set()
            self._resources_by_type[resource_type].add(resource_id)
            
            self._stats.total_created += 1
            self._stats.active_count += 1
            
            tracker.update_state(ResourceState.ACTIVE)
        
        self._logger.debug("Registered resource %s of type %s", resource_id, resource_type.value)
        return resource_id
    
    def unregister_resource(self, resource_id: str, force_cleanup: bool = True) -> bool:
        """Unregister and optionally clean up a resource.
        
        Args:
            resource_id: ID of the resource to unregister
            force_cleanup: Whether to force cleanup if not already cleaned
            
        Returns:
            True if successfully unregistered, False otherwise
        """
        with self._lock:
            if resource_id not in self._resources:
                self._logger.warning("Resource %s not found for unregistration", resource_id)
                return False
            
            tracker = self._resources[resource_id]
            
            # Clean up if needed
            if force_cleanup and tracker.state not in (ResourceState.CLOSED, ResourceState.ERROR):
                self._cleanup_single_resource(tracker)
            
            # Remove from tracking
            del self._resources[resource_id]
            
            if tracker.resource_type in self._resources_by_type:
                self._resources_by_type[tracker.resource_type].discard(resource_id)
                if not self._resources_by_type[tracker.resource_type]:
                    del self._resources_by_type[tracker.resource_type]
            
            # Update stats
            if tracker.state == ResourceState.CLOSED:
                self._stats.closed_count += 1
            elif tracker.state == ResourceState.ERROR:
                self._stats.error_count += 1
            
            self._stats.active_count -= 1
            
            # Update lifetime statistics
            lifetime = tracker.lifetime_seconds
            if lifetime > self._stats.longest_lifetime_seconds:
                self._stats.longest_lifetime_seconds = lifetime
            
            # Update average lifetime (simple moving average)
            if self._stats.closed_count > 0:
                self._stats.average_lifetime_seconds = (
                    (self._stats.average_lifetime_seconds * (self._stats.closed_count - 1) + lifetime) 
                    / self._stats.closed_count
                )
            else:
                self._stats.average_lifetime_seconds = lifetime
        
        self._logger.debug("Unregistered resource %s", resource_id)
        return True
    
    def _cleanup_single_resource(self, tracker: ResourceTracker) -> bool:
        """Clean up a single resource.
        
        Args:
            tracker: Resource tracker for the resource to clean up
            
        Returns:
            True if cleanup was successful, False otherwise
        """
        resource_id = tracker.resource_id
        
        try:
            tracker.update_state(ResourceState.CLOSING)
            
            # Try custom cleanup method first
            if tracker.cleanup_method:
                if asyncio.iscoroutinefunction(tracker.cleanup_method):
                    # Handle async cleanup
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            # Create a task for async cleanup
                            asyncio.create_task(tracker.cleanup_method())
                        else:
                            loop.run_until_complete(tracker.cleanup_method())
                    except Exception as e:
                        self._logger.warning("Async cleanup method failed for %s: %s", resource_id, e)
                else:
                    tracker.cleanup_method()
            
            # Try protocol-based cleanup
            elif hasattr(tracker.resource, 'cleanup'):
                cleanup_method = getattr(tracker.resource, 'cleanup')
                if asyncio.iscoroutinefunction(cleanup_method):
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            asyncio.create_task(cleanup_method())
                        else:
                            loop.run_until_complete(cleanup_method())
                    except Exception as e:
                        self._logger.warning("Async resource cleanup failed for %s: %s", resource_id, e)
                else:
                    cleanup_method()
            
            # Try common cleanup methods
            elif hasattr(tracker.resource, 'close'):
                close_method = getattr(tracker.resource, 'close')
                if asyncio.iscoroutinefunction(close_method):
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            asyncio.create_task(close_method())
                        else:
                            loop.run_until_complete(close_method())
                    except Exception as e:
                        self._logger.warning("Async close failed for %s: %s", resource_id, e)
                else:
                    close_method()
            
            elif hasattr(tracker.resource, '__exit__'):
                # Context manager cleanup
                tracker.resource.__exit__(None, None, None)
            
            tracker.update_state(ResourceState.CLOSED)
            self._logger.debug("Successfully cleaned up resource %s", resource_id)
            return True
            
        except Exception as e:
            tracker.update_state(ResourceState.ERROR)
            self._stats.cleanup_failures += 1
            self._logger.error("Failed to clean up resource %s: %s", resource_id, e)
            return False
    
    def cleanup_by_type(self, resource_type: ResourceType, max_age: Optional[float] = None) -> int:
        """Clean up resources of a specific type.
        
        Args:
            resource_type: Type of resources to clean up
            max_age: Maximum age in seconds (cleanup older resources)
            
        Returns:
            Number of resources cleaned up
        """
        cleaned_count = 0
        current_time = time.time()
        
        with self._lock:
            resource_ids = self._resources_by_type.get(resource_type, set()).copy()
        
        for resource_id in resource_ids:
            with self._lock:
                if resource_id not in self._resources:
                    continue
                    
                tracker = self._resources[resource_id]
                
                # Check age criteria
                if max_age is not None and tracker.lifetime_seconds < max_age:
                    continue
                
                # Skip if already being cleaned up
                if tracker.state in (ResourceState.CLOSING, ResourceState.CLOSED):
                    continue
            
            if self._cleanup_single_resource(tracker):
                cleaned_count += 1
        
        self._logger.info("Cleaned up %d resources of type %s", cleaned_count, resource_type.value)
        return cleaned_count
    
    def cleanup_idle_resources(self) -> int:
        """Clean up resources that have been idle for too long.
        
        Returns:
            Number of resources cleaned up
        """
        cleaned_count = 0
        current_time = time.time()
        
        with self._lock:
            idle_resources = []
            for tracker in self._resources.values():
                if (tracker.state == ResourceState.IDLE and 
                    tracker.lifetime_seconds > self.max_idle_time):
                    idle_resources.append(tracker)
        
        for tracker in idle_resources:
            if self._cleanup_single_resource(tracker):
                cleaned_count += 1
        
        if cleaned_count > 0:
            self._logger.info("Cleaned up %d idle resources", cleaned_count)
        
        return cleaned_count
    
    def force_cleanup_all(self) -> int:
        """Force cleanup of all managed resources.
        
        Returns:
            Number of resources cleaned up
        """
        cleaned_count = 0
        
        with self._lock:
            resource_ids = list(self._resources.keys())
        
        for resource_id in resource_ids:
            if self.unregister_resource(resource_id, force_cleanup=True):
                cleaned_count += 1
        
        self._logger.info("Force cleaned up %d resources", cleaned_count)
        return cleaned_count
    
    def start_background_cleanup(self) -> None:
        """Start background cleanup thread."""
        if self._cleanup_thread is not None and self._cleanup_thread.is_alive():
            self._logger.warning("Background cleanup thread already running")
            return
        
        self._shutdown_event.clear()
        self._cleanup_thread = threading.Thread(
            target=self._background_cleanup_loop,
            name="ResourceManager-Cleanup",
            daemon=True
        )
        self._cleanup_thread.start()
        self._logger.info("Started background resource cleanup thread")
    
    def stop_background_cleanup(self, timeout: float = 10.0) -> None:
        """Stop background cleanup thread.
        
        Args:
            timeout: Maximum time to wait for thread to stop
        """
        if self._cleanup_thread is None or not self._cleanup_thread.is_alive():
            return
        
        self._logger.info("Stopping background cleanup thread...")
        self._shutdown_event.set()
        try:
            self._cleanup_thread.join(timeout=timeout)
        except KeyboardInterrupt:
            # During interpreter shutdown a KeyboardInterrupt may be raised
            # while waiting for the thread to finish. We retry the join once
            # more so the exception doesn't propagate to pytest.
            self._logger.debug("Cleanup thread join interrupted; retrying")
            self._cleanup_thread.join(timeout=timeout)

        if self._cleanup_thread.is_alive():
            self._logger.warning("Background cleanup thread did not stop within timeout")
        else:
            self._logger.info("Background cleanup thread stopped")

        # Clear reference so interpreter doesn't keep the thread object alive
        self._cleanup_thread = None
    
    def _background_cleanup_loop(self) -> None:
        """Background cleanup loop."""
        self._logger.info("Resource manager background cleanup started")
        
        while not self._shutdown_event.is_set():
            try:
                # Clean up idle resources
                safe_execute(
                    self.cleanup_idle_resources,
                    context="Background idle resource cleanup",
                    severity=ErrorSeverity.LOW,
                    logger_name="ResourceManager"
                )
                
                # Trigger garbage collection if enabled
                if self.enable_gc_monitoring:
                    safe_execute(
                        self._run_gc_collection,
                        context="Background garbage collection",
                        severity=ErrorSeverity.LOW,
                        logger_name="ResourceManager"
                    )
                
                # Update memory usage stats
                safe_execute(
                    self._update_memory_stats,
                    context="Memory stats update",
                    severity=ErrorSeverity.LOW,
                    logger_name="ResourceManager"
                )
                
            except Exception as e:
                self._logger.error("Error in background cleanup loop: %s", e)
            
            # Wait for next cleanup cycle
            if self._shutdown_event.wait(self.cleanup_interval):
                break
        
        self._logger.info("Resource manager background cleanup stopped")
    
    def _run_gc_collection(self) -> None:
        """Run garbage collection and log statistics."""
        before_gc = gc.get_count()
        collected = gc.collect()
        after_gc = gc.get_count()
        
        if collected > 0:
            self._logger.debug(
                "Garbage collection: collected %d objects, counts before: %s, after: %s",
                collected, before_gc, after_gc
            )
    
    def _update_memory_stats(self) -> None:
        """Update memory usage statistics."""
        try:
            import psutil
            import os
            
            process = psutil.Process(os.getpid())
            memory_info = process.memory_info()
            self._stats.memory_usage_bytes = memory_info.rss
            
        except (ImportError, Exception) as e:
            self._logger.debug("Could not update memory stats: %s", e)
    
    def get_resource_stats(self) -> Dict[str, Any]:
        """Get comprehensive resource statistics.
        
        Returns:
            Dictionary containing resource statistics
        """
        with self._lock:
            stats = {
                "total_created": self._stats.total_created,
                "active_count": self._stats.active_count,
                "closed_count": self._stats.closed_count,
                "error_count": self._stats.error_count,
                "cleanup_failures": self._stats.cleanup_failures,
                "memory_usage_bytes": self._stats.memory_usage_bytes,
                "longest_lifetime_seconds": self._stats.longest_lifetime_seconds,
                "average_lifetime_seconds": self._stats.average_lifetime_seconds,
                "by_type": {},
                "by_state": {}
            }
            
            # Count by type
            for resource_type, resource_ids in self._resources_by_type.items():
                stats["by_type"][resource_type.value] = len(resource_ids)
            
            # Count by state
            for tracker in self._resources.values():
                state = tracker.state.value
                stats["by_state"][state] = stats["by_state"].get(state, 0) + 1
        
        return stats
    
    def get_resource_info(self, resource_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about a specific resource.
        
        Args:
            resource_id: ID of the resource
            
        Returns:
            Resource information or None if not found
        """
        with self._lock:
            if resource_id not in self._resources:
                return None
            
            tracker = self._resources[resource_id]
            return {
                "resource_id": tracker.resource_id,
                "resource_type": tracker.resource_type.value,
                "created_at": tracker.created_at,
                "lifetime_seconds": tracker.lifetime_seconds,
                "state": tracker.state.value,
                "has_custom_cleanup": tracker.cleanup_method is not None,
                "metadata": tracker.metadata.copy()
            }
    
    def shutdown(self) -> None:
        """Shutdown the resource manager and clean up all resources."""
        self._logger.info("Shutting down resource manager...")
        cleaned_count = 0

        # Stop background cleanup, being tolerant of interrupts
        try:
            self.stop_background_cleanup()
        except KeyboardInterrupt:
            # Avoid bubbling up KeyboardInterrupt during interpreter shutdown
            self._logger.warning("Shutdown interrupted while stopping cleanup thread")
            if self._cleanup_thread and self._cleanup_thread.is_alive():
                self._cleanup_thread.join(timeout=1.0)

        # Clean up all resources
        try:
            cleaned_count = self.force_cleanup_all()
        except KeyboardInterrupt:
            self._logger.warning("Shutdown interrupted during resource cleanup")

        self._logger.info(
            "Resource manager shutdown complete, cleaned up %d resources", cleaned_count
        )


# Global resource manager instance
global_resource_manager = ResourceManager()


@contextmanager
def managed_resource(resource: Any,
                    resource_type: ResourceType,
                    cleanup_method: Optional[Callable] = None,
                    metadata: Optional[Dict[str, Any]] = None):
    """Context manager for automatic resource management.
    
    Args:
        resource: Resource to manage
        resource_type: Type of the resource
        cleanup_method: Custom cleanup method
        metadata: Additional metadata
        
    Yields:
        The managed resource
    """
    resource_id = global_resource_manager.register_resource(
        resource, resource_type, cleanup_method=cleanup_method, metadata=metadata
    )
    
    try:
        yield resource
    finally:
        global_resource_manager.unregister_resource(resource_id)


@asynccontextmanager
async def async_managed_resource(resource: Any,
                                resource_type: ResourceType,
                                cleanup_method: Optional[Callable] = None,
                                metadata: Optional[Dict[str, Any]] = None):
    """Async context manager for automatic resource management.
    
    Args:
        resource: Resource to manage
        resource_type: Type of the resource
        cleanup_method: Custom cleanup method
        metadata: Additional metadata
        
    Yields:
        The managed resource
    """
    resource_id = global_resource_manager.register_resource(
        resource, resource_type, cleanup_method=cleanup_method, metadata=metadata
    )
    
    try:
        yield resource
    finally:
        global_resource_manager.unregister_resource(resource_id)


def register_cleanup_callback(callback: Callable) -> None:
    """Register a callback to be called during shutdown.
    
    Args:
        callback: Function to call during shutdown
    """
    if hasattr(callback, '__self__'):
        # Bound method - use weak reference
        weak_callback = weakref.WeakMethod(callback)
        global_resource_manager._cleanup_callbacks.append(weak_callback)
    else:
        # Regular function - wrap in weak reference
        def wrapper():
            callback()
        weak_callback = weakref.ref(wrapper)
        global_resource_manager._cleanup_callbacks.append(weak_callback)


# Register shutdown handler
def _shutdown_handler():
    """Handle process shutdown by cleaning up resources."""
    try:
        global_resource_manager.shutdown()
    except Exception as e:
        logging.getLogger(__name__).error("Error during resource manager shutdown: %s", e)


atexit.register(_shutdown_handler)