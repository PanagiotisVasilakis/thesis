"""Authentication helpers for the ML service."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from threading import RLock
from typing import Any, Iterable, Optional
from uuid import uuid4

from flask import current_app
from jose import JWTError, jwt

try:
    import redis  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    redis = None

from .metrics_auth import (
    MetricsAuthenticator,
    MetricsAuthError,
    require_metrics_auth,
    get_metrics_authenticator,
    create_metrics_auth_token,
    validate_metrics_request,
)

ALGORITHM = "HS256"


class BaseRefreshTokenStore:
    """Interface for refresh token stores."""

    def add(self, *, jti: str, subject: str, roles: list[str], expires_at: datetime) -> None:
        raise NotImplementedError

    def pop(self, jti: str) -> Optional[dict[str, Any]]:
        raise NotImplementedError

    def get(self, jti: str) -> Optional[dict[str, Any]]:
        raise NotImplementedError

    def purge_subject(self, subject: str) -> None:
        raise NotImplementedError


class MemoryRefreshTokenStore(BaseRefreshTokenStore):
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


class RedisRefreshTokenStore(BaseRefreshTokenStore):
    """Redis-backed refresh token store."""

    def __init__(self, redis_url: str, prefix: str) -> None:
        if not redis:
            raise RuntimeError("redis package is not installed")
        self._client = redis.Redis.from_url(redis_url, decode_responses=True)
        self._prefix = prefix

    def _key(self, jti: str) -> str:
        return f"{self._prefix}{jti}"

    def _encode(self, subject: str, roles: list[str], expires_at: datetime) -> str:
        payload = {
            "sub": subject,
            "roles": roles,
            "exp": expires_at.isoformat(),
        }
        return json.dumps(payload)

    def _decode(self, raw: str) -> Optional[dict[str, Any]]:
        if not raw:
            return None
        data = json.loads(raw)
        exp = data.get("exp")
        if exp:
            data["exp"] = datetime.fromisoformat(exp)
        return data

    def add(self, *, jti: str, subject: str, roles: list[str], expires_at: datetime) -> None:
        ttl = max(int((expires_at - datetime.now(timezone.utc)).total_seconds()), 0)
        self._client.set(self._key(jti), self._encode(subject, roles, expires_at), ex=ttl)

    def pop(self, jti: str) -> Optional[dict[str, Any]]:
        key = self._key(jti)
        raw = self._client.get(key)
        self._client.delete(key)
        return self._decode(raw) if raw else None

    def get(self, jti: str) -> Optional[dict[str, Any]]:
        raw = self._client.get(self._key(jti))
        return self._decode(raw) if raw else None

    def purge_subject(self, subject: str) -> None:
        pattern = f"{self._prefix}*"
        keys_to_delete = []
        for key in self._client.scan_iter(match=pattern):
            raw = self._client.get(key)
            if not raw:
                continue
            decoded = self._decode(raw)
            if decoded and decoded.get("sub") == subject:
                keys_to_delete.append(key)
        if keys_to_delete:
            self._client.delete(*keys_to_delete)


def _create_refresh_store() -> BaseRefreshTokenStore:
    redis_url = current_app.config.get("REDIS_URL", "")
    prefix = current_app.config.get("REDIS_REFRESH_TOKEN_PREFIX", "ml:refresh:")
    if redis_url:
        try:
            return RedisRefreshTokenStore(redis_url, prefix)
        except Exception as exc:
            current_app.logger.warning(
                "Redis refresh token store unavailable (%s). Falling back to in-memory.",
                exc,
            )
    return MemoryRefreshTokenStore()


def _refresh_store() -> BaseRefreshTokenStore:
    store = current_app.extensions.get("refresh_token_store")
    if not isinstance(store, BaseRefreshTokenStore):
        store = _create_refresh_store()
        current_app.extensions["refresh_token_store"] = store
    return store


def _normalise_roles(roles: Optional[Iterable[str]]) -> list[str]:
    """Return unique, non-empty roles preserving insertion order."""
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
    return datetime.now(timezone.utc) + timedelta(minutes=minutes)


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
        "exp": datetime.now(timezone.utc) + expires_delta,
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
        expires_at = datetime.now(timezone.utc) + expires_delta

    refresh_roles = _normalise_roles(roles)
    payload = {
        "sub": subject,
        "roles": refresh_roles,
        "exp": expires_at,
        "jti": str(uuid4()),
        "type": "refresh",
    }
    secret = current_app.config.get("JWT_REFRESH_SECRET") or current_app.config["JWT_SECRET"]
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
    secret = current_app.config.get("JWT_REFRESH_SECRET") or current_app.config["JWT_SECRET"]
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
    if stored["exp"] < datetime.now(timezone.utc):
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


__all__ = [
    "MetricsAuthenticator",
    "MetricsAuthError",
    "require_metrics_auth",
    "get_metrics_authenticator",
    "create_metrics_auth_token",
    "validate_metrics_request",
    "create_access_token",
    "verify_token",
    "create_refresh_token",
    "verify_refresh_token",
    "rotate_refresh_token",
    "revoke_refresh_tokens_for_subject",
]

