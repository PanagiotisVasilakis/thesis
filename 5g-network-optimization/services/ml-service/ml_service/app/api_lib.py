"""Helper functions for ML service API operations."""

from __future__ import annotations

from typing import Any, Iterable

from .initialization.model_init import ModelManager


def load_model(
    model_path: str | None = None,
    neighbor_count: int | None = None,
) -> Any:
    """Return a LightGBM model instance using ``ModelManager``."""
    return ModelManager.get_instance(model_path, neighbor_count=neighbor_count)


def predict(ue_data: dict, model: Any | None = None):
    """Return prediction for ``ue_data`` using the provided model."""
    mdl = model or load_model()
    features = mdl.extract_features(ue_data)
    result = mdl.predict(features)
    return result, features


def train(
    data: Iterable[dict],
    model: Any | None = None,
    *,
    neighbor_count: int | None = None,
) -> dict:
    """Train ``model`` with ``data`` and return training metrics."""
    mdl = model or load_model(neighbor_count=neighbor_count)
    metrics = mdl.train(data)
    return metrics
