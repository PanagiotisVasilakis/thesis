"""Thread monitoring and failure handling for model operations."""

import logging
import threading
import time
import traceback
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Callable, Any
import queue


class ThreadFailureLevel(Enum):
    """Severity levels for thread failures."""
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class ThreadFailureEvent:
    """Information about a thread failure event."""
    thread_name: str
    failure_level: ThreadFailureLevel
    exception: Exception
    traceback_str: str
    timestamp: datetime
    context: Dict[str, Any]
    retry_count: int = 0


class ThreadFailureHandler(ABC):
    """Abstract base class for handling thread failures."""
    
    @abstractmethod
    def handle_failure(self, event: ThreadFailureEvent) -> bool:
        """Handle a thread failure event.
        
        Returns:
            True if the failure was handled successfully, False otherwise.
        """
        pass


class LoggingFailureHandler(ThreadFailureHandler):
    """Logs thread failures with appropriate severity levels."""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    def handle_failure(self, event: ThreadFailureEvent) -> bool:
        """Log the failure event."""
        message = (
            f"Thread '{event.thread_name}' failed with {event.exception.__class__.__name__}: "
            f"{event.exception}. Context: {event.context}. Retry count: {event.retry_count}"
        )
        
        if event.failure_level == ThreadFailureLevel.WARNING:
            self.logger.warning(message)
        elif event.failure_level == ThreadFailureLevel.ERROR:
            self.logger.error(message, exc_info=event.exception)
        elif event.failure_level == ThreadFailureLevel.CRITICAL:
            self.logger.critical(message, exc_info=event.exception)
            self.logger.critical("Traceback: %s", event.traceback_str)
        
        return True


class AlertingFailureHandler(ThreadFailureHandler):
    """Sends alerts for critical thread failures."""
    
    def __init__(self, alert_callback: Optional[Callable[[ThreadFailureEvent], None]] = None):
        self.alert_callback = alert_callback
        self.logger = logging.getLogger(__name__)
    
    def handle_failure(self, event: ThreadFailureEvent) -> bool:
        """Send alerts for critical failures."""
        if event.failure_level == ThreadFailureLevel.CRITICAL:
            if self.alert_callback:
                try:
                    self.alert_callback(event)
                    return True
                except Exception as e:
                    self.logger.error("Failed to send alert: %s", e)
                    return False
            else:
                # Default critical alert behavior
                self.logger.critical(
                    "CRITICAL THREAD FAILURE - IMMEDIATE ATTENTION REQUIRED: "
                    f"Thread '{event.thread_name}' failed: {event.exception}"
                )
        return True


class RetryFailureHandler(ThreadFailureHandler):
    """Attempts to retry failed operations with exponential backoff."""
    
    def __init__(self, max_retries: int = 3, base_delay: float = 1.0):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.logger = logging.getLogger(__name__)
    
    def handle_failure(self, event: ThreadFailureEvent) -> bool:
        """Attempt to retry the failed operation."""
        if event.retry_count >= self.max_retries:
            self.logger.error(
                "Thread '%s' exceeded maximum retry attempts (%d)",
                event.thread_name, self.max_retries
            )
            return False
        
        # Calculate exponential backoff delay
        delay = self.base_delay * (2 ** event.retry_count)
        self.logger.info(
            "Retrying thread '%s' in %.2f seconds (attempt %d/%d)",
            event.thread_name, delay, event.retry_count + 1, self.max_retries
        )
        
        time.sleep(delay)
        return True


class ThreadMonitor:
    """Monitors threads and handles failures with configurable strategies."""
    
    def __init__(self):
        self.failure_handlers: List[ThreadFailureHandler] = []
        self.monitored_threads: Dict[str, threading.Thread] = {}
        self.failure_queue = queue.Queue()
        self.monitor_thread: Optional[threading.Thread] = None
        self.shutdown_event = threading.Event()
        self.logger = logging.getLogger(__name__)
        
        # Add default handlers
        self.add_handler(LoggingFailureHandler())
        self.add_handler(AlertingFailureHandler())
        
    def add_handler(self, handler: ThreadFailureHandler):
        """Add a failure handler."""
        self.failure_handlers.append(handler)
    
    def remove_handler(self, handler: ThreadFailureHandler):
        """Remove a failure handler."""
        if handler in self.failure_handlers:
            self.failure_handlers.remove(handler)
    
    def register_thread(self, thread_name: str, thread: threading.Thread):
        """Register a thread for monitoring."""
        self.monitored_threads[thread_name] = thread
        self.logger.info("Registered thread '%s' for monitoring", thread_name)
    
    def unregister_thread(self, thread_name: str):
        """Unregister a thread from monitoring."""
        if thread_name in self.monitored_threads:
            del self.monitored_threads[thread_name]
            self.logger.info("Unregistered thread '%s' from monitoring", thread_name)
    
    def report_failure(
        self,
        thread_name: str,
        exception: Exception,
        level: ThreadFailureLevel = ThreadFailureLevel.ERROR,
        context: Optional[Dict[str, Any]] = None,
        retry_count: int = 0
    ):
        """Report a thread failure event."""
        event = ThreadFailureEvent(
            thread_name=thread_name,
            failure_level=level,
            exception=exception,
            traceback_str=traceback.format_exc(),
            timestamp=datetime.now(timezone.utc),
            context=context or {},
            retry_count=retry_count
        )
        
        self.failure_queue.put(event)
    
    def start_monitoring(self):
        """Start the monitoring thread."""
        if self.monitor_thread is None or not self.monitor_thread.is_alive():
            self.shutdown_event.clear()
            self.monitor_thread = threading.Thread(
                target=self._monitor_loop,
                name="ThreadMonitor",
                daemon=True
            )
            self.monitor_thread.start()
            self.logger.info("Thread monitoring started")
    
    def stop_monitoring(self):
        """Stop the monitoring thread."""
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.shutdown_event.set()
            self.monitor_thread.join(timeout=5.0)
            self.logger.info("Thread monitoring stopped")
    
    def _monitor_loop(self):
        """Main monitoring loop."""
        while not self.shutdown_event.is_set():
            try:
                # Process failure events
                try:
                    event = self.failure_queue.get(timeout=1.0)
                    self._handle_failure_event(event)
                except queue.Empty:
                    continue
                
                # Check thread health
                self._check_thread_health()
                
            except Exception as e:
                self.logger.error("Error in thread monitor loop: %s", e)
                time.sleep(1.0)
    
    def _handle_failure_event(self, event: ThreadFailureEvent):
        """Handle a single failure event using all registered handlers."""
        handled = False
        
        for handler in self.failure_handlers:
            try:
                if handler.handle_failure(event):
                    handled = True
            except Exception as e:
                self.logger.error(
                    "Failure handler %s raised exception: %s",
                    handler.__class__.__name__, e
                )
        
        if not handled:
            self.logger.error(
                "No handler successfully processed failure event for thread '%s'",
                event.thread_name
            )
    
    def _check_thread_health(self):
        """Check the health of monitored threads."""
        dead_threads = []
        
        for thread_name, thread in self.monitored_threads.items():
            if not thread.is_alive():
                dead_threads.append(thread_name)
                self.logger.warning("Monitored thread '%s' is no longer alive", thread_name)
        
        # Clean up dead threads
        for thread_name in dead_threads:
            self.unregister_thread(thread_name)


# Global thread monitor instance
_thread_monitor = ThreadMonitor()


def get_thread_monitor() -> ThreadMonitor:
    """Get the global thread monitor instance."""
    return _thread_monitor


def monitor_thread_execution(
    thread_name: str,
    level: ThreadFailureLevel = ThreadFailureLevel.ERROR,
    context: Optional[Dict[str, Any]] = None
):
    """Decorator to monitor thread execution and report failures."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                _thread_monitor.report_failure(
                    thread_name=thread_name,
                    exception=e,
                    level=level,
                    context=context
                )
                raise
        return wrapper
    return decorator


def safe_thread_execution(
    target_func: Callable,
    thread_name: str,
    args: tuple = (),
    kwargs: Optional[Dict[str, Any]] = None,
    failure_level: ThreadFailureLevel = ThreadFailureLevel.ERROR,
    context: Optional[Dict[str, Any]] = None,
    max_retries: int = 0
) -> threading.Thread:
    """Execute a function in a monitored thread with error handling."""
    kwargs = kwargs or {}
    monitor = get_thread_monitor()
    
    def monitored_target():
        retry_count = 0
        while retry_count <= max_retries:
            try:
                return target_func(*args, **kwargs)
            except Exception as e:
                monitor.report_failure(
                    thread_name=thread_name,
                    exception=e,
                    level=failure_level,
                    context=context,
                    retry_count=retry_count
                )
                
                if retry_count < max_retries:
                    retry_count += 1
                    # Let the retry handler determine the delay
                    continue
                else:
                    raise
    
    thread = threading.Thread(
        target=monitored_target,
        name=thread_name,
        daemon=True
    )
    
    monitor.register_thread(thread_name, thread)
    return thread