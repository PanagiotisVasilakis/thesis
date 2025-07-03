"""Helper functions for ML service API operations."""

from __future__ import annotations

from typing import Any, Iterable

from .initialization import model_init


def load_model(model_path: str | None = None):
    """Return a LightGBM model instance using ``model_init.get_model``."""
    return model_init.get_model(model_path)


def predict(ue_data: dict, model: Any | None = None):
    """Return prediction for ``ue_data`` using the provided model."""
    mdl = model or load_model()
    features = mdl.extract_features(ue_data)
    result = mdl.predict(features)
    return result, features


def train(data: Iterable[dict], model: Any | None = None):
    """Train ``model`` with ``data`` and return training metrics."""
    mdl = model or load_model()
    metrics = mdl.train(data)
    return metrics
