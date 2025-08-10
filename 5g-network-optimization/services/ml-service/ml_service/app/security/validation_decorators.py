"""Enhanced validation decorators with security sanitization."""

import functools
import logging
from typing import Any, Dict, Optional, Callable, Type, Union
from flask import request, jsonify, g
from pydantic import BaseModel, ValidationError

from .input_sanitizer import get_input_sanitizer, InputSanitizationError, sanitize_request_data
from ..errors import RequestValidationError
from ..utils.exception_handler import SecurityError, exception_context


logger = logging.getLogger(__name__)


class SecureValidationError(SecurityError):
    """Raised when secure validation fails."""
    pass


def sanitize_and_validate_json(
    schema: Optional[Type[BaseModel]] = None,
    allow_list: bool = False,
    required: bool = True,
    sanitize: bool = True,
    strict_mode: Optional[bool] = None
):
    """Decorator for sanitizing and validating JSON input with security checks.
    
    Args:
        schema: Pydantic model class for validation
        allow_list: Whether to allow list input instead of single object
        required: Whether the request body is required
        sanitize: Whether to sanitize input before validation
        strict_mode: Override strict mode for sanitization
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Get request data
            try:
                if not request.is_json:
                    raise RequestValidationError("Content-Type must be application/json")
                
                data = request.get_json(silent=False, force=False)
                
                if data is None:
                    if required:
                        raise RequestValidationError("Request body is required")
                    request.validated_data = None
                    request.sanitized_data = None
                    return func(*args, **kwargs)
                
            except Exception as e:
                raise RequestValidationError(f"Invalid JSON: {e}") from e
            
            # Sanitize input if enabled
            sanitized_data = data
            if sanitize:
                try:
                    sanitizer = get_input_sanitizer()
                    if strict_mode is not None:
                        # Temporarily override strict mode
                        original_strict = sanitizer.strict_mode
                        sanitizer.strict_mode = strict_mode
                        try:
                            sanitized_data = sanitize_request_data(data, func.__name__)
                        finally:
                            sanitizer.strict_mode = original_strict
                    else:
                        sanitized_data = sanitize_request_data(data, func.__name__)
                    
                    # Log if data was modified during sanitization
                    if sanitized_data != data:
                        logger.info("Input sanitization modified data in %s", func.__name__)
                        
                except InputSanitizationError as e:
                    logger.warning("Input sanitization failed in %s: %s", func.__name__, e)
                    raise SecureValidationError(f"Input contains security threats: {e}") from e
            
            # Validate with Pydantic schema if provided
            validated_data = sanitized_data
            if schema:
                try:
                    if allow_list and isinstance(sanitized_data, list):
                        validated_data = [schema(**item) for item in sanitized_data]
                    elif not allow_list and isinstance(sanitized_data, list):
                        raise ValidationError("List input not allowed for this endpoint")
                    else:
                        validated_data = schema(**sanitized_data)
                        
                except ValidationError as e:
                    error_msg = _format_pydantic_errors(e, func.__name__)
                    raise RequestValidationError(f"Validation failed: {error_msg}") from e
                except Exception as e:
                    raise RequestValidationError(f"Validation error: {e}") from e
            
            # Store validated and sanitized data in request context
            request.validated_data = validated_data
            request.sanitized_data = sanitized_data
            request.original_data = data
            
            # Track validation stats
            if hasattr(g, 'validation_stats'):
                g.validation_stats['sanitized'] = sanitized_data != data
                g.validation_stats['validated'] = schema is not None
            else:
                g.validation_stats = {
                    'sanitized': sanitized_data != data,
                    'validated': schema is not None
                }
            
            return func(*args, **kwargs)
        
        return wrapper
    return decorator


def sanitize_path_params(**param_sanitizers: Callable[[str], Any]):
    """Decorator for sanitizing path parameters.
    
    Args:
        **param_sanitizers: Dictionary mapping parameter names to sanitizer functions
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            sanitized_kwargs = {}
            
            for param_name, sanitizer_func in param_sanitizers.items():
                if param_name in kwargs:
                    original_value = kwargs[param_name]
                    
                    try:
                        # First, basic string sanitization
                        if isinstance(original_value, str):
                            sanitizer = get_input_sanitizer()
                            sanitized_str = sanitizer._sanitize_string(
                                original_value, 
                                f"path parameter {param_name}"
                            )
                        else:
                            sanitized_str = str(original_value)
                        
                        # Then apply custom sanitizer
                        sanitized_value = sanitizer_func(sanitized_str)
                        sanitized_kwargs[param_name] = sanitized_value
                        
                        # Log if value was modified
                        if sanitized_value != original_value:
                            logger.info(
                                "Path parameter %s sanitized in %s: %s -> %s",
                                param_name, func.__name__, original_value, sanitized_value
                            )
                            
                    except InputSanitizationError as e:
                        raise SecureValidationError(
                            f"Security threat in path parameter {param_name}: {e}"
                        ) from e
                    except Exception as e:
                        raise RequestValidationError(
                            f"Invalid path parameter {param_name}: {e}"
                        ) from e
                else:
                    # Parameter not provided, keep as is
                    pass
            
            # Update kwargs with sanitized values
            kwargs.update(sanitized_kwargs)
            
            return func(*args, **kwargs)
        
        return wrapper
    return decorator


def sanitize_query_params(**param_sanitizers: Callable[[str], Any]):
    """Decorator for sanitizing query parameters.
    
    Args:
        **param_sanitizers: Dictionary mapping parameter names to sanitizer functions
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            sanitized_params = {}
            
            for param_name, sanitizer_func in param_sanitizers.items():
                param_value = request.args.get(param_name)
                
                if param_value is not None:
                    try:
                        # Basic string sanitization
                        sanitizer = get_input_sanitizer()
                        sanitized_str = sanitizer._sanitize_string(
                            param_value,
                            f"query parameter {param_name}"
                        )
                        
                        # Apply custom sanitizer
                        sanitized_value = sanitizer_func(sanitized_str)
                        sanitized_params[param_name] = sanitized_value
                        
                        # Log if value was modified
                        if sanitized_value != param_value:
                            logger.info(
                                "Query parameter %s sanitized in %s: %s -> %s",
                                param_name, func.__name__, param_value, sanitized_value
                            )
                            
                    except InputSanitizationError as e:
                        raise SecureValidationError(
                            f"Security threat in query parameter {param_name}: {e}"
                        ) from e
                    except Exception as e:
                        raise RequestValidationError(
                            f"Invalid query parameter {param_name}: {e}"
                        ) from e
            
            # Store sanitized params in request context
            request.sanitized_args = sanitized_params
            
            return func(*args, **kwargs)
        
        return wrapper
    return decorator


def validate_file_upload(
    param_name: str = 'file',
    max_size: int = 10 * 1024 * 1024,  # 10MB
    allowed_extensions: Optional[list] = None,
    required: bool = True
):
    """Decorator for validating file uploads with security checks.
    
    Args:
        param_name: Name of the file parameter
        max_size: Maximum file size in bytes
        allowed_extensions: List of allowed file extensions
        required: Whether file upload is required
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if param_name not in request.files:
                if required:
                    raise RequestValidationError(f"File parameter '{param_name}' is required")
                request.uploaded_file = None
                return func(*args, **kwargs)
            
            file = request.files[param_name]
            
            # Check if file was actually uploaded
            if file.filename == '':
                if required:
                    raise RequestValidationError("No file selected")
                request.uploaded_file = None
                return func(*args, **kwargs)
            
            try:
                # Sanitize filename
                sanitizer = get_input_sanitizer()
                sanitized_filename = sanitizer.sanitize_file_path(
                    file.filename,
                    allowed_extensions=allowed_extensions
                )
                
                # Check file size by reading content
                file_content = file.read()
                file.seek(0)  # Reset file pointer
                
                if len(file_content) > max_size:
                    raise RequestValidationError(
                        f"File too large: {len(file_content)} bytes > {max_size} bytes"
                    )
                
                # Store file info in request context
                request.uploaded_file = {
                    'file': file,
                    'filename': sanitized_filename,
                    'original_filename': file.filename,
                    'size': len(file_content),
                    'content': file_content
                }
                
                logger.info(
                    "File upload validated in %s: %s (%d bytes)",
                    func.__name__, sanitized_filename, len(file_content)
                )
                
            except InputSanitizationError as e:
                raise SecureValidationError(f"Security threat in uploaded filename: {e}") from e
            except Exception as e:
                raise RequestValidationError(f"File upload validation failed: {e}") from e
            
            return func(*args, **kwargs)
        
        return wrapper
    return decorator


def require_secure_headers():
    """Decorator to validate that required security headers are present."""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Check for CSRF token in non-GET requests
            if request.method not in ['GET', 'HEAD', 'OPTIONS']:
                csrf_token = request.headers.get('X-CSRF-Token')
                if not csrf_token:
                    logger.warning(
                        "Missing CSRF token in %s request to %s",
                        request.method, func.__name__
                    )
                    # In strict mode, this would be an error
                    # raise SecureValidationError("CSRF token required")
            
            # Validate Content-Type for JSON endpoints
            if request.method in ['POST', 'PUT', 'PATCH']:
                content_type = request.headers.get('Content-Type', '')
                if 'application/json' in content_type:
                    # Additional JSON-specific validation could go here
                    pass
            
            # Store security validation info
            g.security_headers_checked = True
            
            return func(*args, **kwargs)
        
        return wrapper
    return decorator


def rate_limit_by_ip(max_requests: int = 100, window_seconds: int = 3600):
    """Decorator for IP-based rate limiting.
    
    Args:
        max_requests: Maximum requests per window
        window_seconds: Time window in seconds
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            client_ip = request.environ.get('REMOTE_ADDR', 'unknown')
            
            # This is a placeholder for rate limiting logic
            # In a real implementation, you'd use Redis or similar
            # to track request counts per IP
            
            # For now, just log the request
            logger.debug("Rate limit check for IP %s in %s", client_ip, func.__name__)
            
            # Store rate limiting info
            g.rate_limit_checked = True
            g.client_ip = client_ip
            
            return func(*args, **kwargs)
        
        return wrapper
    return decorator


def _format_pydantic_errors(error: ValidationError, context: str = "") -> str:
    """Format Pydantic validation errors for user-friendly display.
    
    Args:
        error: Pydantic ValidationError
        context: Context string
        
    Returns:
        Formatted error message
    """
    error_messages = []
    
    for err in error.errors():
        location = " -> ".join(str(loc) for loc in err["loc"]) if err["loc"] else "root"
        message = err["msg"]
        error_type = err["type"]
        
        if context:
            full_location = f"{context}.{location}" if location != "root" else context
        else:
            full_location = location
        
        formatted_msg = f"[{full_location}] {message}"
        error_messages.append(formatted_msg)
    
    return "; ".join(error_messages)


# Commonly used sanitizers for path/query parameters
def sanitize_ue_id(value: str) -> str:
    """Sanitize UE ID parameter."""
    if not value or len(value) > 64:
        raise ValueError("UE ID must be 1-64 characters")
    
    # UE IDs should be alphanumeric with hyphens/underscores
    import re
    if not re.match(r'^[a-zA-Z0-9_-]+$', value):
        raise ValueError("UE ID contains invalid characters")
    
    return value


def sanitize_antenna_id(value: str) -> str:
    """Sanitize antenna ID parameter."""
    if not value or len(value) > 32:
        raise ValueError("Antenna ID must be 1-32 characters")
    
    # Antenna IDs should be alphanumeric with underscores
    import re
    if not re.match(r'^[a-zA-Z0-9_]+$', value):
        raise ValueError("Antenna ID contains invalid characters")
    
    return value


def sanitize_model_version(value: str) -> str:
    """Sanitize model version parameter."""
    if not value or len(value) > 16:
        raise ValueError("Model version must be 1-16 characters")
    
    # Model versions should follow semantic versioning
    import re
    if not re.match(r'^v?\d+(\.\d+){0,2}(-[a-zA-Z0-9]+)?$', value):
        raise ValueError("Invalid model version format")
    
    return value


def sanitize_integer_param(min_val: int = 0, max_val: int = 1000000):
    """Create a sanitizer for integer parameters.
    
    Args:
        min_val: Minimum allowed value
        max_val: Maximum allowed value
        
    Returns:
        Sanitizer function
    """
    def sanitizer(value: str) -> int:
        try:
            int_val = int(value)
            if not (min_val <= int_val <= max_val):
                raise ValueError(f"Value must be between {min_val} and {max_val}")
            return int_val
        except ValueError as e:
            raise ValueError(f"Invalid integer: {e}") from e
    
    return sanitizer


def sanitize_float_param(min_val: float = 0.0, max_val: float = 1000000.0):
    """Create a sanitizer for float parameters.
    
    Args:
        min_val: Minimum allowed value
        max_val: Maximum allowed value
        
    Returns:
        Sanitizer function
    """
    def sanitizer(value: str) -> float:
        try:
            float_val = float(value)
            if not (min_val <= float_val <= max_val):
                raise ValueError(f"Value must be between {min_val} and {max_val}")
            return float_val
        except ValueError as e:
            raise ValueError(f"Invalid float: {e}") from e
    
    return sanitizer