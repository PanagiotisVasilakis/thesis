"""Shared request decorators for API authentication and authorization."""
from __future__ import annotations

import asyncio
from functools import wraps

from flask import current_app, g, jsonify, request

from ..auth import verify_token

# Legacy decorator kept for backward compatibility; unused in codebase.
def log_slow_request(func):
    return func


def require_auth(func):
    """Decorator enforcing JWT authentication for API handlers."""

    def _check_token():
        if current_app.testing:
            return None
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return jsonify({"error": "Missing token"}), 401
        token = header.split(" ", 1)[1]
        payload = verify_token(token)
        if not payload or not payload.get("sub"):
            return jsonify({"error": "Invalid token"}), 401
        g.user = payload.get("sub")
        g.roles = payload.get("roles", [])
        return None

    if asyncio.iscoroutinefunction(func):

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            resp = _check_token()
            if resp is not None:
                return resp
            return await func(*args, **kwargs)

        return async_wrapper

    @wraps(func)
    def wrapper(*args, **kwargs):
        resp = _check_token()
        if resp is not None:
            return resp
        return func(*args, **kwargs)

    return wrapper


def require_roles(*allowed_roles: str):
    """Decorator ensuring the authenticated principal has the required role(s)."""

    def decorator(func):
        if not allowed_roles:
            return func

        if asyncio.iscoroutinefunction(func):

            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                if current_app.testing:
                    return await func(*args, **kwargs)
                user_roles = set(getattr(g, "roles", []) or [])
                if not user_roles.intersection(allowed_roles):
                    return jsonify({"error": "Forbidden"}), 403
                return await func(*args, **kwargs)

            return async_wrapper

        @wraps(func)
        def wrapper(*args, **kwargs):
            if current_app.testing:
                return func(*args, **kwargs)
            user_roles = set(getattr(g, "roles", []) or [])
            if not user_roles.intersection(allowed_roles):
                return jsonify({"error": "Forbidden"}), 403
            return func(*args, **kwargs)

        return wrapper

    return decorator


def sync_or_async_wrapper(check_func, func):
    """Return either an async or sync wrapper that calls check_func before func.
    
    This helper eliminates the repeated pattern of checking if a function is async
    and creating appropriate wrappers. Use this to reduce code duplication in decorators.
    
    Args:
        check_func: A function to call before the wrapped function (returns None or response)
        func: The function to wrap
        
    Returns:
        Wrapped function (async or sync based on original function type)
    """
    if asyncio.iscoroutinefunction(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            result = check_func()
            if result is not None:
                return result
            return await func(*args, **kwargs)
        return async_wrapper
    
    @wraps(func)
    def wrapper(*args, **kwargs):
        result = check_func()
        if result is not None:
            return result
        return func(*args, **kwargs)
    return wrapper


def handle_model_errors(operation_name: str = "operation"):
    """Decorator that provides standardized error handling for model operations.
    
    This eliminates the repeated try/except blocks in predict, train, and other
    endpoints that all handle the same set of exceptions.
    
    Args:
        operation_name: Name of the operation for error messages (e.g., "Prediction", "Training")
        
    Usage:
        @handle_model_errors("Prediction")
        def predict():
            model = load_model(...)
            result = model.predict(...)
            return result
    """
    from ..errors import ModelError
    
    def decorator(func):
        if asyncio.iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                try:
                    return await func(*args, **kwargs)
                except (ValueError, TypeError, KeyError) as exc:
                    raise ModelError(f"{operation_name} failed: {exc}") from exc
                except FileNotFoundError as exc:
                    raise ModelError(f"Model file not found: {exc}") from exc
                except MemoryError as exc:
                    raise ModelError(f"Insufficient memory for {operation_name.lower()}: {exc}") from exc
            return async_wrapper
        
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except (ValueError, TypeError, KeyError) as exc:
                raise ModelError(f"{operation_name} failed: {exc}") from exc
            except FileNotFoundError as exc:
                raise ModelError(f"Model file not found: {exc}") from exc
            except MemoryError as exc:
                raise ModelError(f"Insufficient memory for {operation_name.lower()}: {exc}") from exc
        return wrapper
    
    return decorator
