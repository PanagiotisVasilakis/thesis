"""Input validation utilities for API endpoints."""
from functools import wraps
from flask import request, jsonify
from pydantic import BaseModel, ValidationError, Field
from typing import Dict, Any, Optional, List, Union
import re

from .errors import RequestValidationError


class LoginRequest(BaseModel):
    """Validation schema for login requests."""
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1, max_length=1000)


class CollectDataRequest(BaseModel):
    """Validation schema for data collection requests."""
    duration: int = Field(60, ge=1, le=3600)  # 1 second to 1 hour
    interval: int = Field(1, ge=1, le=60)     # 1 to 60 seconds
    username: Optional[str] = Field(None, max_length=100)
    password: Optional[str] = Field(None, max_length=1000)


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


def validate_json_input(schema_class: Optional[BaseModel] = None, 
                       allow_list: bool = False,
                       required: bool = True):
    """
    Decorator to validate JSON input against a Pydantic schema.
    
    Args:
        schema_class: Pydantic model class to validate against
        allow_list: Whether to allow list inputs
        required: Whether JSON input is required
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Get JSON payload
            payload = request.get_json(silent=True)
            
            # Check if JSON is required
            if required and payload is None:
                raise RequestValidationError("Invalid or missing JSON payload")
            
            # If no schema validation needed, just pass through
            if schema_class is None:
                return func(*args, **kwargs)
            
            # Handle list inputs
            if allow_list and isinstance(payload, list):
                validated_items = []
                for i, item in enumerate(payload):
                    try:
                        validated_items.append(schema_class.parse_obj(item))
                    except ValidationError as err:
                        raise RequestValidationError(
                            f"Validation error in item {i}: {err}"
                        ) from err
                # Replace request data with validated data
                request.validated_data = validated_items
            else:
                # Validate single object
                try:
                    validated_data = schema_class.parse_obj(payload)
                    request.validated_data = validated_data
                except ValidationError as err:
                    raise RequestValidationError(f"Validation error: {err}") from err
            
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
        @wraps(func)
        def wrapper(*args, **kwargs):
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
            
            request.validated_params = validated_params
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
        @wraps(func)
        def wrapper(*args, **kwargs):
            validated_kwargs = {}
            for param_name, validator in param_specs.items():
                if param_name in kwargs:
                    try:
                        validated_kwargs[param_name] = validator(kwargs[param_name])
                    except (ValueError, TypeError) as err:
                        raise RequestValidationError(
                            f"Invalid path parameter '{param_name}': {err}"
                        ) from err
                else:
                    validated_kwargs[param_name] = kwargs[param_name]
            
            # Update kwargs with validated values
            kwargs.update(validated_kwargs)
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
        @wraps(func)
        def wrapper(*args, **kwargs):
            content_type = request.content_type
            if content_type not in allowed_types:
                raise RequestValidationError(
                    f"Invalid content type '{content_type}'. "
                    f"Allowed types: {', '.join(allowed_types)}"
                )
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
        @wraps(func)
        def wrapper(*args, **kwargs):
            content_length = request.content_length
            if content_length is not None:
                max_bytes = max_size_mb * 1024 * 1024
                if content_length > max_bytes:
                    raise RequestValidationError(
                        f"Request payload too large. "
                        f"Maximum allowed: {max_size_mb}MB"
                    )
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