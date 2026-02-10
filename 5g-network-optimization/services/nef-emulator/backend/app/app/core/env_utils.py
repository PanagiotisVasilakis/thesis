# services/nef-emulator/backend/app/app/core/env_utils.py
"""Environment variable parsing utilities.

Provides consistent parsing of environment variables with proper error handling
and logging. Replaces the repeated try/except pattern found throughout the codebase.
"""

import logging
import os
from typing import Optional, TypeVar

T = TypeVar("T")

logger = logging.getLogger(__name__)


def parse_env_float(
    key: str,
    default: float,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
) -> float:
    """Parse a float from an environment variable with validation.
    
    Args:
        key: Environment variable name.
        default: Default value if env var is not set or invalid.
        min_value: Optional minimum bound (inclusive).
        max_value: Optional maximum bound (inclusive).
    
    Returns:
        Parsed float value or default.
    """
    raw = os.getenv(key)
    if raw is None:
        return default
    
    try:
        value = float(raw)
    except ValueError:
        logger.warning(
            "Invalid value for %s: '%s'. Using default %.2f",
            key, raw, default
        )
        return default
    
    if min_value is not None and value < min_value:
        logger.warning(
            "%s value %.2f below minimum %.2f; clamping",
            key, value, min_value
        )
        value = min_value
    
    if max_value is not None and value > max_value:
        logger.warning(
            "%s value %.2f above maximum %.2f; clamping",
            key, value, max_value
        )
        value = max_value
    
    return value


def parse_env_int(
    key: str,
    default: int,
    min_value: Optional[int] = None,
    max_value: Optional[int] = None,
) -> int:
    """Parse an integer from an environment variable with validation.
    
    Args:
        key: Environment variable name.
        default: Default value if env var is not set or invalid.
        min_value: Optional minimum bound (inclusive).
        max_value: Optional maximum bound (inclusive).
    
    Returns:
        Parsed integer value or default.
    """
    raw = os.getenv(key)
    if raw is None:
        return default
    
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "Invalid value for %s: '%s'. Using default %d",
            key, raw, default
        )
        return default
    
    if min_value is not None and value < min_value:
        logger.warning(
            "%s value %d below minimum %d; clamping",
            key, value, min_value
        )
        value = min_value
    
    if max_value is not None and value > max_value:
        logger.warning(
            "%s value %d above maximum %d; clamping",
            key, value, max_value
        )
        value = max_value
    
    return value


def parse_env_bool(key: str, default: bool) -> bool:
    """Parse a boolean from an environment variable.
    
    Accepts: 'true', '1', 'yes', 'on' (case-insensitive) for True.
    All other non-empty values are treated as False.
    
    Args:
        key: Environment variable name.
        default: Default value if env var is not set.
    
    Returns:
        Parsed boolean value or default.
    """
    raw = os.getenv(key)
    if raw is None:
        return default
    
    return raw.lower() in ("true", "1", "yes", "on")


def parse_env_str(key: str, default: str) -> str:
    """Get a string environment variable with default.
    
    Args:
        key: Environment variable name.
        default: Default value if env var is not set.
    
    Returns:
        Environment variable value or default.
    """
    return os.getenv(key, default)
