"""JWT authentication utilities for ML Service."""
from __future__ import annotations

from datetime import datetime, timedelta
from threading import RLock
from typing import Any, Iterable, Optional
from uuid import uuid4

from jose import jwt, JWTError
from flask import current_app


ALGORITHM = "HS256"


class RefreshTokenStore:
    """Thread-safe in-memory refresh token registry."""

    def __init__(self) -> None:
        self._tokens: dict[str, dict[str, Any]] = {}
        self._lock = RLock()

    def add(self, *, jti: str, subject: str, roles: list[str], expires_at: datetime) -> None:
        with self._lock:
            self._tokens[jti] = {
                "sub": subject,
                "roles": roles,
                "exp": expires_at,
            }

    def pop(self, jti: str) -> Optional[dict[str, Any]]:
        with self._lock:
            return self._tokens.pop(jti, None)

    def get(self, jti: str) -> Optional[dict[str, Any]]:
        with self._lock:
            return self._tokens.get(jti)

    def purge_subject(self, subject: str) -> None:
        with self._lock:
            expired = [j for j, meta in self._tokens.items() if meta.get("sub") == subject]
            for jti in expired:
                self._tokens.pop(jti, None)


def _refresh_store() -> RefreshTokenStore:
    store = current_app.extensions.setdefault("refresh_token_store", RefreshTokenStore())
    if not isinstance(store, RefreshTokenStore):
        store = RefreshTokenStore()
        current_app.extensions["refresh_token_store"] = store
    return store


def _normalise_roles(roles: Optional[Iterable[str]]) -> list[str]:
    """Return a normalised list of unique roles preserving insertion order."""
    if not roles:
        return []
    seen: set[str] = set()
    ordered: list[str] = []
    for role in roles:
        if not role:
            continue
        key = str(role)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(key)
    return ordered


def _compute_expiry(config_key: str, fallback_minutes: int) -> datetime:
    minutes = int(current_app.config.get(config_key, fallback_minutes))
    return datetime.utcnow() + timedelta(minutes=minutes)


def create_access_token(
    subject: str,
    *,
    roles: Optional[Iterable[str]] = None,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Return a signed JWT access token for ``subject`` with optional roles."""
    if expires_delta is None:
        expires_delta = timedelta(minutes=current_app.config.get("JWT_EXPIRES_MINUTES", 30))
    to_encode = {
        "sub": subject,
        "exp": datetime.utcnow() + expires_delta,
        "roles": _normalise_roles(roles),
        "type": "access",
    }
    secret = current_app.config["JWT_SECRET"]
    return jwt.encode(to_encode, secret, algorithm=ALGORITHM)


def create_refresh_token(
    subject: str,
    *,
    roles: Optional[Iterable[str]] = None,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create and register a refresh token for ``subject``."""
    if expires_delta is None:
        expires_at = _compute_expiry("JWT_REFRESH_EXPIRES_MINUTES", 1440)
    else:
        expires_at = datetime.utcnow() + expires_delta

    refresh_roles = _normalise_roles(roles)
    payload = {
        "sub": subject,
        "roles": refresh_roles,
        "exp": expires_at,
        "jti": str(uuid4()),
        "type": "refresh",
    }
    secret = current_app.config.get("JWT_REFRESH_SECRET", current_app.config["JWT_SECRET"])
    token = jwt.encode(payload, secret, algorithm=ALGORITHM)
    store = _refresh_store()
    store.add(jti=payload["jti"], subject=subject, roles=refresh_roles, expires_at=expires_at)
    return token


def verify_token(token: str) -> Optional[dict[str, Any]]:
    """Verify ``token`` and return the decoded payload if valid."""
    secret = current_app.config["JWT_SECRET"]
    try:
        payload = jwt.decode(token, secret, algorithms=[ALGORITHM])
    except JWTError:
        return None
    if payload.get("type") != "access":
        return None
    return {
        "sub": payload.get("sub"),
        "roles": payload.get("roles", []),
        "exp": payload.get("exp"),
    }


def verify_refresh_token(token: str) -> Optional[dict[str, Any]]:
    """Verify ``token`` is a valid, registered refresh token."""
    secret = current_app.config.get("JWT_REFRESH_SECRET", current_app.config["JWT_SECRET"])
    try:
        payload = jwt.decode(token, secret, algorithms=[ALGORITHM])
    except JWTError:
        return None
    if payload.get("type") != "refresh":
        return None

    jti = payload.get("jti")
    subject = payload.get("sub")
    if not jti or not subject:
        return None

    store = _refresh_store()
    stored = store.get(jti)
    if not stored:
        return None
    if stored["sub"] != subject:
        store.pop(jti)
        return None
    if stored["exp"] < datetime.utcnow():
        store.pop(jti)
        return None
    return {
        "sub": stored["sub"],
        "roles": stored.get("roles", []),
        "exp": stored.get("exp"),
        "jti": jti,
    }


def rotate_refresh_token(jti: str) -> None:
    """Retire the refresh token identified by ``jti``."""
    store = _refresh_store()
    store.pop(jti)


def revoke_refresh_tokens_for_subject(subject: str) -> None:
    """Remove all refresh tokens for ``subject`` from the store."""
    store = _refresh_store()
    store.purge_subject(subject)
