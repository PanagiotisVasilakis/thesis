"""Type conversion and validation helpers.

This module provides utilities for safe type conversion used throughout
the ML service. Consolidates previously duplicated implementations.

Usage:
    from ..utils.type_helpers import safe_float, safe_float_or_none

    value = safe_float(data.get("latency"), fallback=0.0)
    optional_value = safe_float_or_none(data.get("rsrp"))
"""

from typing import Any, Optional


def safe_float(value: Any, fallback: float = 0.0) -> float:
    """Convert value to float with fallback on failure.
    
    Args:
        value: Value to convert (can be None, str, int, float, etc.)
        fallback: Value to return if conversion fails
    
    Returns:
        float: Converted value or fallback
    
    Example:
        >>> safe_float("3.14")
        3.14
        >>> safe_float(None, fallback=-1.0)
        -1.0
        >>> safe_float("invalid", fallback=0.0)
        0.0
    """
    if value is None:
        return fallback
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def safe_float_or_none(value: Any) -> Optional[float]:
    """Convert value to float, returning None on failure.
    
    Args:
        value: Value to convert
    
    Returns:
        Optional[float]: Converted value or None
    
    Example:
        >>> safe_float_or_none("3.14")
        3.14
        >>> safe_float_or_none(None)
        None
        >>> safe_float_or_none("invalid")
        None
    """
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def safe_int(value: Any, fallback: int = 0) -> int:
    """Convert value to int with fallback on failure.
    
    Args:
        value: Value to convert
        fallback: Value to return if conversion fails
    
    Returns:
        int: Converted value or fallback
    """
    if value is None:
        return fallback
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback
