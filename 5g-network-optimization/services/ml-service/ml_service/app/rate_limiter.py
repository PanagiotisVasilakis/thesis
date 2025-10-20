"""Rate limiting utilities for the ML service."""
from __future__ import annotations

from typing import Callable

from flask import current_app, g, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address


def _identity_key() -> str:
    """Return a rate-limit key combining authenticated user and IP."""
    user = getattr(g, "user", None)
    if user:
        ip = request.headers.get("X-Forwarded-For")
        client_ip = ip.split(",")[0].strip() if ip else get_remote_address()
        return f"user:{user}@{client_ip}"
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return f"ip:{forwarded.split(',')[0].strip()}"
    return f"ip:{get_remote_address()}"


limiter = Limiter(key_func=_identity_key, headers_enabled=True)


def init_app(app):
    """Initialize limiter with configuration-aware defaults."""
    app.config.setdefault("RATELIMIT_DEFAULT", "100 per minute")
    app.config.setdefault("RATELIMIT_ENABLED", True)
    app.config.setdefault("RATELIMIT_STORAGE_URI", "memory://")
    app.config.setdefault("RATE_LIMITS", {})

    limiter.enabled = bool(app.config.get("RATELIMIT_ENABLED", True)) and not app.testing

    limiter.init_app(app)
    return limiter


def limit_for(endpoint_key: str) -> Callable[[], str]:
    """Return a callable resolving the rate limit string for ``endpoint_key``."""

    def _resolver() -> str:
        per_endpoint = current_app.config.get("RATE_LIMITS", {})
        limit = per_endpoint.get(endpoint_key)
        if limit:
            return limit
        return current_app.config.get("RATELIMIT_DEFAULT", "100 per minute")

    return _resolver
