"""Circuit breaker pattern implementation for external service resilience."""

import time
import threading
import logging
from enum import Enum
from typing import Callable, Any, Optional, Dict
from functools import wraps


class CircuitState(Enum):
    """States of the circuit breaker."""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Circuit is open, rejecting calls
    HALF_OPEN = "half_open"  # Testing if service has recovered


class CircuitBreakerError(Exception):
    """Raised when circuit breaker is open."""
    pass


class CircuitBreaker:
    """Circuit breaker implementation for external service calls.
    
    Provides automatic failure detection and recovery for external services.
    When failures exceed the threshold, the circuit opens and rejects calls
    for a cooldown period. After cooldown, it enters half-open state to test
    if the service has recovered.
    """
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        expected_exception: type = Exception,
        name: str = "CircuitBreaker"
    ):
        """Initialize circuit breaker.
        
        Args:
            failure_threshold: Number of failures before opening circuit
            recovery_timeout: Seconds to wait before attempting recovery
            expected_exception: Exception type that counts as failure
            name: Name for logging and identification
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        self.name = name
        
        self._lock = threading.RLock()
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = None
        self._success_count = 0
        
        self.logger = logging.getLogger(f"{__name__}.{name}")
        
    @property
    def state(self) -> CircuitState:
        """Get current circuit state."""
        with self._lock:
            return self._state
    
    @property
    def failure_count(self) -> int:
        """Get current failure count."""
        with self._lock:
            return self._failure_count
            
    def _should_attempt_reset(self) -> bool:
        """Check if we should attempt to reset the circuit."""
        if self._last_failure_time is None:
            return False
        return time.time() - self._last_failure_time >= self.recovery_timeout
    
    def _record_success(self):
        """Record a successful call."""
        with self._lock:
            self._failure_count = 0
            self._success_count += 1
            
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.CLOSED
                self.logger.info(
                    "Circuit breaker %s recovered - state changed to CLOSED",
                    self.name
                )
    
    def _record_failure(self):
        """Record a failed call."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            
            if self._state == CircuitState.HALF_OPEN:
                # Failed during recovery attempt - go back to OPEN
                self._state = CircuitState.OPEN
                self.logger.warning(
                    "Circuit breaker %s failed during recovery - state changed to OPEN",
                    self.name
                )
            elif (self._state == CircuitState.CLOSED and 
                  self._failure_count >= self.failure_threshold):
                # Too many failures - open the circuit
                self._state = CircuitState.OPEN
                self.logger.error(
                    "Circuit breaker %s opened after %d failures - state changed to OPEN",
                    self.name, self._failure_count
                )
    
    def call(self, func: Callable[..., Any], *args, **kwargs) -> Any:
        """Execute function with circuit breaker protection.
        
        Args:
            func: Function to call
            *args: Positional arguments for function
            **kwargs: Keyword arguments for function
            
        Returns:
            Function result
            
        Raises:
            CircuitBreakerError: When circuit is open
            Exception: When function raises unexpected exception
        """
        with self._lock:
            current_state = self._state
            
            # Check if circuit should transition from OPEN to HALF_OPEN
            if (current_state == CircuitState.OPEN and 
                self._should_attempt_reset()):
                self._state = CircuitState.HALF_OPEN
                current_state = CircuitState.HALF_OPEN
                self.logger.info(
                    "Circuit breaker %s attempting recovery - state changed to HALF_OPEN",
                    self.name
                )
            
            # Reject calls when circuit is open
            if current_state == CircuitState.OPEN:
                raise CircuitBreakerError(
                    f"Circuit breaker {self.name} is OPEN. "
                    f"Last failure: {self._last_failure_time}, "
                    f"Failures: {self._failure_count}/{self.failure_threshold}"
                )
        
        # Execute the function
        try:
            result = func(*args, **kwargs)
            self._record_success()
            return result
        except self.expected_exception as e:
            self._record_failure()
            raise e
        except Exception as e:
            # Unexpected exception - don't count as failure but still raise
            self.logger.warning(
                "Circuit breaker %s: unexpected exception type %s: %s",
                self.name, type(e).__name__, str(e)
            )
            raise e
    
    def get_stats(self) -> Dict[str, Any]:
        """Get circuit breaker statistics."""
        with self._lock:
            return {
                "name": self.name,
                "state": self._state.value,
                "failure_count": self._failure_count,
                "success_count": self._success_count,
                "failure_threshold": self.failure_threshold,
                "recovery_timeout": self.recovery_timeout,
                "last_failure_time": self._last_failure_time,
                "time_since_last_failure": (
                    time.time() - self._last_failure_time 
                    if self._last_failure_time else None
                )
            }
    
    def reset(self):
        """Manually reset the circuit breaker to CLOSED state."""
        with self._lock:
            old_state = self._state
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._last_failure_time = None
            
            if old_state != CircuitState.CLOSED:
                self.logger.info(
                    "Circuit breaker %s manually reset to CLOSED state",
                    self.name
                )


def circuit_breaker(
    failure_threshold: int = 5,
    recovery_timeout: float = 60.0,
    expected_exception: type = Exception,
    name: Optional[str] = None
):
    """Decorator to apply circuit breaker pattern to a function.
    
    Args:
        failure_threshold: Number of failures before opening circuit
        recovery_timeout: Seconds to wait before attempting recovery
        expected_exception: Exception type that counts as failure
        name: Name for circuit breaker (defaults to function name)
    
    Example:
        @circuit_breaker(failure_threshold=3, recovery_timeout=30.0)
        def call_external_service():
            # Function that might fail
            pass
    """
    def decorator(func: Callable) -> Callable:
        breaker_name = name or f"{func.__module__}.{func.__name__}"
        breaker = CircuitBreaker(
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
            expected_exception=expected_exception,
            name=breaker_name
        )
        
        @wraps(func)
        def wrapper(*args, **kwargs):
            return breaker.call(func, *args, **kwargs)
        
        # Attach circuit breaker to function for access to stats/reset
        wrapper.circuit_breaker = breaker
        return wrapper
    
    return decorator


class CircuitBreakerRegistry:
    """Registry to manage multiple circuit breakers."""
    
    def __init__(self):
        self._breakers: Dict[str, CircuitBreaker] = {}
        self._lock = threading.RLock()
        self.logger = logging.getLogger(__name__)
    
    def register(self, breaker: CircuitBreaker) -> None:
        """Register a circuit breaker."""
        with self._lock:
            self._breakers[breaker.name] = breaker
            self.logger.debug("Registered circuit breaker: %s", breaker.name)
    
    def get(self, name: str) -> Optional[CircuitBreaker]:
        """Get a circuit breaker by name."""
        with self._lock:
            return self._breakers.get(name)
    
    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get statistics for all registered circuit breakers."""
        with self._lock:
            return {name: breaker.get_stats() 
                   for name, breaker in self._breakers.items()}
    
    def reset_all(self) -> None:
        """Reset all circuit breakers to CLOSED state."""
        with self._lock:
            for breaker in self._breakers.values():
                breaker.reset()
            self.logger.info("Reset all circuit breakers")
    
    def get_open_circuits(self) -> Dict[str, CircuitBreaker]:
        """Get all circuit breakers that are currently open."""
        with self._lock:
            return {name: breaker for name, breaker in self._breakers.items()
                   if breaker.state == CircuitState.OPEN}


# Global registry instance
circuit_registry = CircuitBreakerRegistry()