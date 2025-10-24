"""Compatibility shim exposing feature schema constants for Feast utilities."""

from mlops.feature_store.feature_repo.schema import (
    UE_METRIC_FIELDS,
    UE_METRIC_FEATURE_NAMES,
    feast_fields,
)

__all__ = ["UE_METRIC_FIELDS", "UE_METRIC_FEATURE_NAMES", "feast_fields"]
