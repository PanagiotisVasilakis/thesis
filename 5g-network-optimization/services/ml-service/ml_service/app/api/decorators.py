"""Shared request decorators for API authentication and authorization."""
from __future__ import annotations

import asyncio
from functools import wraps

from flask import current_app, g, jsonify, request

from ..auth import verify_token


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
