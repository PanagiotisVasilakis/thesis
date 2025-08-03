"""Standardized exception handling framework for the ML service."""

import logging
import traceback
import functools
from typing import Any, Callable, Optional, Type, Union, Dict, List, Tuple
from contextlib import contextmanager
from enum import Enum

from ..utils.common_validators import ValidationError


class ErrorSeverity(Enum):
    """Severity levels for errors."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ServiceError(Exception):
    """Base exception for all ML service errors."""
    
    def __init__(
        self, 
        message: str, 
        cause: Optional[Exception] = None,
        severity: ErrorSeverity = ErrorSeverity.MEDIUM,
        context: Optional[Dict[str, Any]] = None
    ):
        super().__init__(message)
        self.message = message
        self.cause = cause
        self.severity = severity
        self.context = context or {}
    
    def __str__(self) -> str:
        base_msg = self.message
        if self.cause:
            base_msg += f" (caused by: {self.cause})"
        return base_msg


class ConfigurationError(ServiceError):
    """Configuration-related errors."""
    
    def __init__(self, message: str, cause: Optional[Exception] = None, **kwargs):
        super().__init__(message, cause, ErrorSeverity.HIGH, **kwargs)


class NetworkError(ServiceError):
    """Network and communication errors."""
    
    def __init__(self, message: str, cause: Optional[Exception] = None, **kwargs):
        super().__init__(message, cause, ErrorSeverity.MEDIUM, **kwargs)


class ModelError(ServiceError):
    """ML model-related errors."""
    
    def __init__(self, message: str, cause: Optional[Exception] = None, **kwargs):
        super().__init__(message, cause, ErrorSeverity.HIGH, **kwargs)


class DataError(ServiceError):
    """Data processing and validation errors."""
    
    def __init__(self, message: str, cause: Optional[Exception] = None, **kwargs):
        super().__init__(message, cause, ErrorSeverity.MEDIUM, **kwargs)


class ResourceError(ServiceError):
    """Resource management errors (memory, I/O, etc.)."""
    
    def __init__(self, message: str, cause: Optional[Exception] = None, **kwargs):
        super().__init__(message, cause, ErrorSeverity.HIGH, **kwargs)


class SecurityError(ServiceError):
    """Security and authentication errors."""
    
    def __init__(self, message: str, cause: Optional[Exception] = None, **kwargs):
        super().__init__(message, cause, ErrorSeverity.CRITICAL, **kwargs)


class ExceptionHandler:
    """Centralized exception handling with standardized logging and recovery."""
    
    def __init__(self, logger_name: Optional[str] = None):
        """Initialize exception handler.
        
        Args:
            logger_name: Name for the logger (defaults to class name)
        """
        self.logger = logging.getLogger(logger_name or __name__)
        self._error_counts: Dict[str, int] = {}
    
    def log_error(
        self, 
        exception: Exception, 
        context: str = "",
        severity: Optional[ErrorSeverity] = None,
        extra_context: Optional[Dict[str, Any]] = None
    ) -> None:
        """Log an exception with appropriate severity level.
        
        Args:
            exception: Exception to log
            context: Context string describing where the error occurred
            severity: Override severity level
            extra_context: Additional context information
        """
        # Determine severity
        if isinstance(exception, ServiceError):
            severity = severity or exception.severity
        else:
            severity = severity or self._determine_severity(exception)
        
        # Build context message
        context_parts = []
        if context:
            context_parts.append(context)
        
        if isinstance(exception, ServiceError) and exception.context:
            context_parts.extend(f"{k}={v}" for k, v in exception.context.items())
        
        if extra_context:
            context_parts.extend(f"{k}={v}" for k, v in extra_context.items())
        
        context_str = f" [{', '.join(context_parts)}]" if context_parts else ""
        
        # Count errors for monitoring
        error_type = type(exception).__name__
        self._error_counts[error_type] = self._error_counts.get(error_type, 0) + 1
        
        # Log with appropriate level
        message = f"{error_type}: {exception}{context_str}"
        
        if severity == ErrorSeverity.CRITICAL:
            self.logger.critical(message, exc_info=True)
        elif severity == ErrorSeverity.HIGH:
            self.logger.error(message, exc_info=True)
        elif severity == ErrorSeverity.MEDIUM:
            self.logger.warning(message)
        else:  # LOW
            self.logger.info(message)
    
    def _determine_severity(self, exception: Exception) -> ErrorSeverity:
        """Determine severity level for standard exceptions."""
        if isinstance(exception, (SystemExit, KeyboardInterrupt)):
            return ErrorSeverity.CRITICAL
        elif isinstance(exception, (MemoryError, OSError, IOError)):
            return ErrorSeverity.HIGH
        elif isinstance(exception, (ValueError, TypeError, AttributeError)):
            return ErrorSeverity.MEDIUM
        else:
            return ErrorSeverity.MEDIUM
    
    def handle_exception(
        self,
        exception: Exception,
        context: str = "",
        reraise: bool = False,
        default_return: Any = None,
        severity: Optional[ErrorSeverity] = None,
        extra_context: Optional[Dict[str, Any]] = None
    ) -> Any:
        """Handle an exception with logging and optional recovery.
        
        Args:
            exception: Exception to handle
            context: Context string
            reraise: Whether to reraise the exception after logging
            default_return: Default value to return if not reraising
            severity: Override severity level
            extra_context: Additional context information
            
        Returns:
            default_return if not reraising, otherwise raises
            
        Raises:
            Exception: If reraise is True
        """
        self.log_error(exception, context, severity, extra_context)
        
        if reraise:
            raise exception
        
        return default_return
    
    def get_error_stats(self) -> Dict[str, int]:
        """Get error count statistics."""
        return self._error_counts.copy()
    
    def reset_error_stats(self) -> None:
        """Reset error count statistics."""
        self._error_counts.clear()


# Global exception handler instance
global_exception_handler = ExceptionHandler()


def handle_exceptions(
    exceptions: Union[Type[Exception], Tuple[Type[Exception], ...]] = Exception,
    context: str = "",
    reraise: bool = False,
    default_return: Any = None,
    severity: Optional[ErrorSeverity] = None,
    logger_name: Optional[str] = None
):
    """Decorator for standardized exception handling.
    
    Args:
        exceptions: Exception type(s) to catch
        context: Context string for logging
        reraise: Whether to reraise exceptions after logging
        default_return: Default return value for non-reraised exceptions
        severity: Override severity level
        logger_name: Logger name (uses function's module if not provided)
    
    Returns:
        Decorated function
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            handler = ExceptionHandler(logger_name or func.__module__)
            func_context = context or f"{func.__module__}.{func.__name__}"
            
            try:
                return func(*args, **kwargs)
            except exceptions as e:
                return handler.handle_exception(
                    e, func_context, reraise, default_return, severity
                )
        
        return wrapper
    return decorator


@contextmanager
def exception_context(
    context: str,
    exceptions: Union[Type[Exception], Tuple[Type[Exception], ...]] = Exception,
    reraise: bool = True,
    default_return: Any = None,
    severity: Optional[ErrorSeverity] = None,
    logger_name: Optional[str] = None
):
    """Context manager for standardized exception handling.
    
    Args:
        context: Context string for logging
        exceptions: Exception type(s) to catch
        reraise: Whether to reraise exceptions after logging
        default_return: Default return value for non-reraised exceptions
        severity: Override severity level  
        logger_name: Logger name
        
    Yields:
        ExceptionHandler instance
        
    Example:
        with exception_context("Processing UE data", (ValueError, TypeError)) as handler:
            # Code that might raise exceptions
            process_ue_data(data)
    """
    handler = ExceptionHandler(logger_name)
    
    try:
        yield handler
    except exceptions as e:
        result = handler.handle_exception(
            e, context, reraise, default_return, severity
        )
        if not reraise:
            return result


def convert_standard_exceptions(
    value_error_class: Type[ServiceError] = DataError,
    type_error_class: Type[ServiceError] = DataError,
    key_error_class: Type[ServiceError] = DataError,
    attribute_error_class: Type[ServiceError] = DataError,
    io_error_class: Type[ServiceError] = ResourceError,
    network_error_class: Type[ServiceError] = NetworkError
):
    """Decorator to convert standard exceptions to service exceptions.
    
    Args:
        value_error_class: Service exception class for ValueError
        type_error_class: Service exception class for TypeError
        key_error_class: Service exception class for KeyError
        attribute_error_class: Service exception class for AttributeError
        io_error_class: Service exception class for IOError/OSError
        network_error_class: Service exception class for network errors
    
    Returns:
        Decorated function
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except ValueError as e:
                raise value_error_class(str(e), cause=e) from e
            except TypeError as e:
                raise type_error_class(str(e), cause=e) from e
            except KeyError as e:
                raise key_error_class(f"Missing key: {e}", cause=e) from e
            except AttributeError as e:
                raise attribute_error_class(str(e), cause=e) from e
            except (IOError, OSError) as e:
                raise io_error_class(str(e), cause=e) from e
            except (ConnectionError, TimeoutError) as e:
                raise network_error_class(str(e), cause=e) from e
            except ValidationError as e:
                raise DataError(str(e), cause=e) from e
        
        return wrapper
    return decorator


def safe_execute(
    func: Callable,
    *args,
    context: str = "",
    default_return: Any = None,
    exceptions: Union[Type[Exception], Tuple[Type[Exception], ...]] = Exception,
    severity: Optional[ErrorSeverity] = None,
    logger_name: Optional[str] = None,
    **kwargs
) -> Any:
    """Safely execute a function with exception handling.
    
    Args:
        func: Function to execute
        *args: Positional arguments for function
        context: Context string for logging
        default_return: Default return value on exception
        exceptions: Exception type(s) to catch
        severity: Override severity level
        logger_name: Logger name
        **kwargs: Keyword arguments for function
        
    Returns:
        Function result or default_return on exception
    """
    handler = ExceptionHandler(logger_name)
    func_context = context or f"{func.__module__}.{func.__name__}"
    
    try:
        return func(*args, **kwargs)
    except exceptions as e:
        return handler.handle_exception(
            e, func_context, False, default_return, severity
        )


class RetryableError(ServiceError):
    """Base class for errors that can be retried."""
    
    def __init__(self, message: str, cause: Optional[Exception] = None, **kwargs):
        super().__init__(message, cause, **kwargs)


def with_retry(
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff_factor: float = 2.0,
    retryable_exceptions: Tuple[Type[Exception], ...] = (RetryableError, NetworkError),
    context: str = ""
):
    """Decorator to add retry logic with exponential backoff.
    
    Args:
        max_attempts: Maximum number of attempts
        delay: Initial delay between attempts in seconds
        backoff_factor: Factor to multiply delay by after each attempt
        retryable_exceptions: Exception types that should trigger a retry
        context: Context string for logging
    
    Returns:
        Decorated function
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            handler = ExceptionHandler(func.__module__)
            func_context = context or f"{func.__module__}.{func.__name__}"
            
            last_exception = None
            current_delay = delay
            
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except retryable_exceptions as e:
                    last_exception = e
                    
                    if attempt < max_attempts - 1:  # Not the last attempt
                        handler.log_error(
                            e, 
                            f"{func_context} (attempt {attempt + 1}/{max_attempts})",
                            ErrorSeverity.LOW,
                            {"retry_delay": current_delay}
                        )
                        
                        import time
                        time.sleep(current_delay)
                        current_delay *= backoff_factor
                    else:  # Last attempt
                        handler.log_error(
                            e,
                            f"{func_context} (final attempt {attempt + 1}/{max_attempts})",
                            ErrorSeverity.HIGH
                        )
                        raise e
                except Exception as e:
                    # Non-retryable exception
                    handler.log_error(
                        e,
                        f"{func_context} (non-retryable error)",
                        ErrorSeverity.HIGH
                    )
                    raise e
            
            # This shouldn't be reached, but just in case
            if last_exception:
                raise last_exception
        
        return wrapper
    return decorator


# Convenience functions for common patterns
def log_and_ignore(exception: Exception, context: str = "", logger_name: Optional[str] = None) -> None:
    """Log an exception and ignore it (don't reraise)."""
    handler = ExceptionHandler(logger_name)
    handler.handle_exception(exception, context, reraise=False)


def log_and_reraise(exception: Exception, context: str = "", logger_name: Optional[str] = None) -> None:
    """Log an exception and reraise it."""
    handler = ExceptionHandler(logger_name)
    handler.handle_exception(exception, context, reraise=True)


def create_service_error(
    exception: Exception,
    message: Optional[str] = None,
    error_class: Type[ServiceError] = ServiceError,
    context: Optional[Dict[str, Any]] = None
) -> ServiceError:
    """Convert a standard exception to a service exception.
    
    Args:
        exception: Original exception
        message: Override message (uses original message if not provided)
        error_class: Service exception class to use
        context: Additional context information
        
    Returns:
        Service exception instance
    """
    msg = message or str(exception)
    return error_class(msg, cause=exception, context=context)


def handle_validation_error(
    func: Callable,
    *args,
    context: str = "",
    default_return: Any = None,
    **kwargs
) -> Any:
    """Handle validation errors specifically.
    
    Args:
        func: Function that might raise ValidationError
        *args: Function arguments
        context: Context for logging
        default_return: Default return value on validation error
        **kwargs: Function keyword arguments
        
    Returns:
        Function result or default_return on ValidationError
    """
    try:
        return func(*args, **kwargs)
    except ValidationError as e:
        handler = ExceptionHandler()
        return handler.handle_exception(
            DataError(str(e), cause=e),
            context,
            reraise=False,
            default_return=default_return,
            severity=ErrorSeverity.MEDIUM
        )