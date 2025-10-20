"""QoS encoding helpers.

This module provides a single helper to encode string service types into
numeric ordinals used by the training pipeline. The mapping is intentionally
small and can be overridden in tests by passing a custom mapping.
"""
from typing import Any, Mapping


DEFAULT_SERVICE_TYPE_MAP: dict[str, float] = {
    "mmtc": 0.5,
    "embb": 1.0,
    "urllc": 2.0,
    "default": 0.0,
}


def encode_service_type(value: Any, mapping: Mapping[str, float] | None = None) -> float:
    """Encode a service type string into a numeric value.

    Args:
        value: service type value (string or numeric)
        mapping: optional mapping overriding the default

    Returns:
        Numeric encoding of the service type; fallback to 0.0 when unknown.
    """
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    mapping = mapping or DEFAULT_SERVICE_TYPE_MAP
    return float(mapping.get(str(value).lower(), 0.0))
