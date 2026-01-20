"""Input validation utilities for API endpoints."""
import inspect
import re
from functools import wraps
from typing import Any, Dict, List, Optional, Type, Union

from flask import jsonify, request
from pydantic import BaseModel, Field, ValidationError

from .errors import RequestValidationError
from .config.constants import (
    DEFAULT_COLLECTION_DURATION,
    DEFAULT_COLLECTION_INTERVAL,
    MIN_COLLECTION_INTERVAL,
    MAX_COLLECTION_INTERVAL,
    MAX_COLLECTION_DURATION,
    DEFAULT_MAX_USERNAME_LENGTH,
    DEFAULT_MAX_PASSWORD_LENGTH,
)


def _format_validation_errors(validation_error: ValidationError, context: str = "") -> str:
    """Format Pydantic validation errors into user-friendly messages.
    
    Args:
        validation_error: The Pydantic ValidationError
        context: Context string for error location
        
    Returns:
        Formatted error message string
    """
    error_details = []
    
    for error in validation_error.errors():
        location = " -> ".join(str(loc) for loc in error["loc"]) if error["loc"] else "root"
        if context:
            full_location = f"{context}.{location}" if location != "root" else context
        else:
            full_location = location
            
        error_type = error["type"]
        message = error["msg"]
        
        # Add more context for common error types
        if error_type == "value_error.missing":
            formatted_error = f"[{full_location}] Required field is missing"
        elif error_type == "type_error":
            formatted_error = f"[{full_location}] {message}"
        elif error_type == "value_error":
            formatted_error = f"[{full_location}] {message}"
        elif "too_short" in error_type:
            min_length = error.get("ctx", {}).get("limit_value", "unknown")
            formatted_error = f"[{full_location}] Value too short (minimum: {min_length})"
        elif "too_long" in error_type:
            max_length = error.get("ctx", {}).get("limit_value", "unknown")
            formatted_error = f"[{full_location}] Value too long (maximum: {max_length})"
        elif "greater_than" in error_type:
            limit = error.get("ctx", {}).get("limit_value", "unknown")
            formatted_error = f"[{full_location}] Value must be greater than {limit}"
        elif "less_than" in error_type:
            limit = error.get("ctx", {}).get("limit_value", "unknown")
            formatted_error = f"[{full_location}] Value must be less than {limit}"
        elif "enum" in error_type:
            allowed_values = error.get("ctx", {}).get("enum_values", [])
            formatted_error = f"[{full_location}] Invalid value. Allowed: {list(allowed_values)}"
        else:
            formatted_error = f"[{full_location}] {message}"
        
        error_details.append(formatted_error)
    
    return "; ".join(error_details)


def _generate_validation_suggestions(validation_error: ValidationError, payload: dict) -> str:
    """Generate helpful suggestions for fixing validation errors.
    
    Args:
        validation_error: The Pydantic ValidationError
        payload: The original payload that failed validation
        
    Returns:
        Formatted suggestions string
    """
    suggestions = []
    
    for error in validation_error.errors():
        error_type = error["type"]
        location = error.get("loc", [])
        
        if error_type == "value_error.missing":
            field_name = location[-1] if location else "unknown"
            suggestions.append(f"Add required field '{field_name}'")
        elif error_type == "type_error.integer":
            field_name = location[-1] if location else "unknown"
            suggestions.append(f"Convert '{field_name}' to integer")
        elif error_type == "type_error.float":
            field_name = location[-1] if location else "unknown"
            suggestions.append(f"Convert '{field_name}' to number")
        elif error_type == "type_error.bool":
            field_name = location[-1] if location else "unknown"
            suggestions.append(f"Use true/false for '{field_name}'")
        elif "too_short" in error_type:
            field_name = location[-1] if location else "unknown"
            min_length = error.get("ctx", {}).get("limit_value", "required")
            suggestions.append(f"Ensure '{field_name}' has at least {min_length} characters")
        elif "too_long" in error_type:
            field_name = location[-1] if location else "unknown"
            max_length = error.get("ctx", {}).get("limit_value", "allowed")
            suggestions.append(f"Reduce '{field_name}' to {max_length} characters or less")
        elif "enum" in error_type:
            field_name = location[-1] if location else "unknown"
            allowed_values = error.get("ctx", {}).get("enum_values", [])
            if allowed_values:
                suggestions.append(f"Use one of these values for '{field_name}': {list(allowed_values)}")
    
    return "; ".join(suggestions)


class LoginRequest(BaseModel):
    """Validation schema for login requests."""
    username: str = Field(..., min_length=1, max_length=DEFAULT_MAX_USERNAME_LENGTH)
    password: str = Field(..., min_length=1, max_length=DEFAULT_MAX_PASSWORD_LENGTH)


class RefreshTokenRequest(BaseModel):
    """Validation schema for refresh-token requests."""
    refresh_token: str = Field(..., min_length=10)


class CollectDataRequest(BaseModel):
    """Validation schema for data collection requests."""
    duration: float = Field(DEFAULT_COLLECTION_DURATION, ge=1, le=MAX_COLLECTION_DURATION)
    interval: float = Field(
        DEFAULT_COLLECTION_INTERVAL,
        ge=MIN_COLLECTION_INTERVAL,
        le=MAX_COLLECTION_INTERVAL,
    )
    username: Optional[str] = Field(None, max_length=DEFAULT_MAX_USERNAME_LENGTH)
    password: Optional[str] = Field(None, max_length=DEFAULT_MAX_PASSWORD_LENGTH)


class ModelVersionRequest(BaseModel):
    """Validation schema for model version switching."""
    
    @classmethod
    def __get_validators__(cls):
        yield cls.validate_version
    
    @classmethod
    def validate_version(cls, v):
        """Validate model version format."""
        if not isinstance(v, str):
            raise ValueError("Version must be a string")
        if not re.match(r'^[a-zA-Z0-9._-]+$', v):
            raise ValueError("Version contains invalid characters")
        if len(v) > 50:
            raise ValueError("Version string too long")
        return v


def validate_json_input(schema_class: Optional[Type[BaseModel]] = None, 
                       allow_list: bool = False,
                       required: bool = True,
                       partial_validation: bool = False):
    """
    Decorator to validate JSON input against a Pydantic schema.
    
    Args:
        schema_class: Pydantic model class to validate against
        allow_list: Whether to allow list inputs
        required: Whether JSON input is required
        partial_validation: Whether to allow partial validation (ignore extra fields)
    """
    def decorator(func):
        def _perform_validation():
            payload = request.get_json(silent=True)

            if required and payload is None:
                raise RequestValidationError("Invalid or missing JSON payload")

            if schema_class is None:
                request.validated_data = payload  # type: ignore[attr-defined]
                request.validation_metadata = {"schema": None}  # type: ignore[attr-defined]
                return

            if allow_list and isinstance(payload, list):
                validated_items = []
                validation_errors = []

                for i, item in enumerate(payload):
                    try:
                        validated_item = schema_class.model_validate(item)
                        validated_items.append(validated_item)
                    except ValidationError as err:
                        detailed_errors = _format_validation_errors(err, f"item[{i}]")
                        validation_errors.append(f"Item {i}: {detailed_errors}")

                if validation_errors:
                    raise RequestValidationError(
                        "Validation failed for "
                        f"{len(validation_errors)} items: "
                        + "; ".join(validation_errors)
                    )

                request.validated_data = validated_items  # type: ignore[attr-defined]
                validation_metadata = {
                    "total_items": len(payload),
                    "validated_items": len(validated_items),
                    "schema": schema_class.__name__,
                }
                request.validation_metadata = validation_metadata  # type: ignore[attr-defined]
            else:
                try:
                    validated_data = schema_class.model_validate(payload)
                    request.validated_data = validated_data  # type: ignore[attr-defined]
                    schema_fields = getattr(schema_class, "model_fields", {})
                    validation_metadata = {
                        "schema": schema_class.__name__,
                        "fields_validated": len(schema_fields),
                    }
                    request.validation_metadata = validation_metadata  # type: ignore[attr-defined]
                except ValidationError as err:
                    detailed_errors = _format_validation_errors(err, "root")
                    payload_dict: Dict[str, Any] = payload if isinstance(payload, dict) else {}
                    suggestions = _generate_validation_suggestions(err, payload_dict)
                    error_message = f"Validation errors: {detailed_errors}"
                    if suggestions:
                        error_message += f". Suggestions: {suggestions}"
                    raise RequestValidationError(error_message) from err

        if inspect.iscoroutinefunction(func):

            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                _perform_validation()
                return await func(*args, **kwargs)

            return async_wrapper

        @wraps(func)
        def wrapper(*args, **kwargs):
            _perform_validation()
            return func(*args, **kwargs)

        return wrapper
    return decorator


def validate_query_params(**param_specs):
    """
    Decorator to validate query parameters.
    
    Args:
        **param_specs: Parameter name -> validation function mapping
    """
    def decorator(func):
        def _validate():
            validated_params = {}
            for param_name, validator in param_specs.items():
                value = request.args.get(param_name)
                if value is not None:
                    try:
                        validated_params[param_name] = validator(value)
                    except (ValueError, TypeError) as err:
                        raise RequestValidationError(
                            f"Invalid query parameter '{param_name}': {err}"
                        ) from err

            request.validated_params = validated_params  # type: ignore[attr-defined]

        if inspect.iscoroutinefunction(func):

            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                _validate()
                return await func(*args, **kwargs)

            return async_wrapper

        @wraps(func)
        def wrapper(*args, **kwargs):
            _validate()
            return func(*args, **kwargs)

        return wrapper
    return decorator


def validate_path_params(**param_specs):
    """
    Decorator to validate path parameters.
    
    Args:
        **param_specs: Parameter name -> validation function mapping
    """
    def decorator(func):
        def _validate(kwargs_to_update):
            validated_kwargs = {}
            for param_name, validator in param_specs.items():
                if param_name in kwargs_to_update:
                    try:
                        validated_kwargs[param_name] = validator(kwargs_to_update[param_name])
                    except (ValueError, TypeError) as err:
                        raise RequestValidationError(
                            f"Invalid path parameter '{param_name}': {err}"
                        ) from err

            kwargs_to_update.update(validated_kwargs)

        if inspect.iscoroutinefunction(func):

            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                _validate(kwargs)
                return await func(*args, **kwargs)

            return async_wrapper

        @wraps(func)
        def wrapper(*args, **kwargs):
            _validate(kwargs)
            return func(*args, **kwargs)

        return wrapper
    return decorator


def validate_content_type(*allowed_types):
    """
    Decorator to validate request content type.
    
    Args:
        *allowed_types: List of allowed content types
    """
    def decorator(func):
        def _validate():
            content_type = request.content_type
            if content_type not in allowed_types:
                raise RequestValidationError(
                    f"Invalid content type '{content_type}'. "
                    f"Allowed types: {', '.join(allowed_types)}"
                )

        if inspect.iscoroutinefunction(func):

            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                _validate()
                return await func(*args, **kwargs)

            return async_wrapper

        @wraps(func)
        def wrapper(*args, **kwargs):
            _validate()
            return func(*args, **kwargs)

        return wrapper
    return decorator


def validate_request_size(max_size_mb: int = 10):
    """
    Decorator to validate request payload size.
    
    Args:
        max_size_mb: Maximum allowed payload size in MB
    """
    def decorator(func):
        def _validate():
            content_length = request.content_length
            if content_length is not None:
                max_bytes = max_size_mb * 1024 * 1024
                if content_length > max_bytes:
                    raise RequestValidationError(
                        "Request payload too large. "
                        f"Maximum allowed: {max_size_mb}MB"
                    )

        if inspect.iscoroutinefunction(func):

            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                _validate()
                return await func(*args, **kwargs)

            return async_wrapper

        @wraps(func)
        def wrapper(*args, **kwargs):
            _validate()
            return func(*args, **kwargs)

        return wrapper
    return decorator


# Common validators for reuse
def positive_int(value: str) -> int:
    """Validate positive integer."""
    try:
        val = int(value)
        if val <= 0:
            raise ValueError("Must be positive")
        return val
    except ValueError as err:
        raise ValueError(f"Invalid integer: {err}") from err


def bounded_int(min_val: int, max_val: int):
    """Create a bounded integer validator."""
    def validator(value: str) -> int:
        try:
            val = int(value)
            if val < min_val or val > max_val:
                raise ValueError(f"Must be between {min_val} and {max_val}")
            return val
        except ValueError as err:
            raise ValueError(f"Invalid integer: {err}") from err
    return validator


def safe_string(max_length: int = 100):
    """Create a safe string validator."""
    def validator(value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("Must be a string")
        if len(value) > max_length:
            raise ValueError(f"String too long (max {max_length} characters)")
        # Basic sanitization - remove control characters
        sanitized = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', value)
        return sanitized.strip()
    return validator


def model_version_validator(value: str) -> str:
    """Validate model version string."""
    if not isinstance(value, str):
        raise ValueError("Version must be a string")
    if not re.match(r'^[a-zA-Z0-9._-]+$', value):
        raise ValueError("Version contains invalid characters")
    if len(value) > 50:
        raise ValueError("Version string too long")
    return value