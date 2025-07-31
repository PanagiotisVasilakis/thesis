"""Ensemble model combining multiple selectors."""

from .antenna_selector import AntennaSelector, FALLBACK_ANTENNA_ID, FALLBACK_CONFIDENCE
from .lightgbm_selector import LightGBMSelector
from .lstm_selector import LSTMSelector
import numpy as np


class EnsembleSelector(AntennaSelector):
    """Aggregate predictions from several selector models."""

    def __init__(self, models: list[AntennaSelector] | None = None, *, neighbor_count: int | None = None) -> None:
        self.models = models or [LightGBMSelector(neighbor_count=neighbor_count), LSTMSelector(neighbor_count=neighbor_count)]
        super().__init__(model_path=None, neighbor_count=neighbor_count)

    def _initialize_model(self):
        """Ensemble does not use a single underlying model."""
        self.model = None

    def train(self, training_data: list, **kwargs) -> dict:
        """Train all models in the ensemble."""
        metrics = {}
        for model in self.models:
            metrics[model.__class__.__name__] = model.train(training_data, **kwargs)
        return metrics

    def predict(self, features: dict) -> dict:
        """Average probabilities from all models."""
        probs_accum = None
        classes = None
        for model in self.models:
            if hasattr(model, "model") and model.model is not None:
                if isinstance(model, LSTMSelector):
                    if model.classes_ is None:
                        continue
                    X = np.array([[features[name] for name in model.feature_names]], dtype=float)
                    X = X.reshape((1, 1, len(model.feature_names)))
                    prob = model.model.predict(X, verbose=0)[0]
                    model_classes = model.classes_
                else:
                    X = np.array([[features[name] for name in model.feature_names]], dtype=float)
                    prob = model.model.predict_proba(X)[0]
                    model_classes = list(model.model.classes_)
                if probs_accum is None:
                    probs_accum = np.zeros(len(model_classes))
                    classes = model_classes
                aligned = np.zeros(len(classes))
                for idx, cls in enumerate(model_classes):
                    if cls in classes:
                        aligned[classes.index(cls)] = prob[idx]
                probs_accum += aligned
        if probs_accum is None:
            return {"antenna_id": FALLBACK_ANTENNA_ID, "confidence": FALLBACK_CONFIDENCE}
        probs = probs_accum / len(self.models)
        idx = int(np.argmax(probs))
        return {"antenna_id": classes[idx], "confidence": float(probs[idx])}
