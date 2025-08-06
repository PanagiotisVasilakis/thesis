"""Authentication helpers for the ML service."""

from datetime import datetime, timedelta
from typing import Optional

from flask import current_app
from jose import JWTError, jwt

from .metrics_auth import (
    MetricsAuthenticator,
    MetricsAuthError,
    require_metrics_auth,
    get_metrics_authenticator,
    create_metrics_auth_token,
    validate_metrics_request,
)

ALGORITHM = "HS256"


def create_access_token(subject: str, expires_delta: Optional[timedelta] = None) -> str:
    """Return a signed JWT access token for ``subject``."""
    if expires_delta is None:
        expires_delta = timedelta(
            minutes=current_app.config.get("JWT_EXPIRES_MINUTES", 30)
        )
    to_encode = {"sub": subject, "exp": datetime.utcnow() + expires_delta}
    secret = current_app.config["JWT_SECRET"]
    return jwt.encode(to_encode, secret, algorithm=ALGORITHM)


def verify_token(token: str) -> Optional[str]:
    """Verify ``token`` and return the subject if valid."""
    secret = current_app.config["JWT_SECRET"]
    try:
        payload = jwt.decode(token, secret, algorithms=[ALGORITHM])
    except JWTError:
        return None
    return payload.get("sub")


__all__ = [
    "MetricsAuthenticator",
    "MetricsAuthError",
    "require_metrics_auth",
    "get_metrics_authenticator",
    "create_metrics_auth_token",
    "validate_metrics_request",
    "create_access_token",
    "verify_token",
]

