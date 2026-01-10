"""JWT authentication utilities for ML Service.

This module re-exports the canonical authentication functions from the
``auth`` subpackage to maintain backward compatibility with existing imports.
All new code should import directly from ``ml_service.app.auth``.
"""
from __future__ import annotations

# Re-export all authentication functions from the auth package
from .auth import (
    create_access_token,
    create_refresh_token,
    verify_token,
    verify_refresh_token,
    rotate_refresh_token,
    revoke_refresh_tokens_for_subject,
    RefreshTokenStore,
    ALGORITHM,
)

__all__ = [
    "create_access_token",
    "create_refresh_token",
    "verify_token",
    "verify_refresh_token",
    "rotate_refresh_token",
    "revoke_refresh_tokens_for_subject",
    "RefreshTokenStore",
    "ALGORITHM",
]
