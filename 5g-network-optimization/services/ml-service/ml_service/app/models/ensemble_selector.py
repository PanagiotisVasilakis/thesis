"""Ensemble model combining multiple selectors."""

from .antenna_selector import AntennaSelector, FALLBACK_ANTENNA_ID, FALLBACK_CONFIDENCE
from .base_model_mixin import BaseModelMixin
from .lightgbm_selector import LightGBMSelector
from .lstm_selector import LSTMSelector
import numpy as np


class EnsembleSelector(BaseModelMixin, AntennaSelector):
    """Aggregate predictions from several selector models."""

    def __init__(
        self,
        models: list[AntennaSelector] | None = None,
        *,
        neighbor_count: int | None = None,
        config_path: str | None = None,
    ) -> None:
        self.models = models or [
            LightGBMSelector(neighbor_count=neighbor_count, config_path=config_path),
            LSTMSelector(neighbor_count=neighbor_count, config_path=config_path),
        ]
        super().__init__(
            model_path=None,
            neighbor_count=neighbor_count,
            config_path=config_path,
        )

    def _initialize_model(self):
        """Ensemble does not use a single underlying model."""
        self.model = None

    def train(self, training_data: list, **kwargs) -> dict:
        """Train all models in the ensemble.
        
        This method is thread-safe as individual models handle their own locking.
        """
        if not training_data:
            raise ValueError("Training data cannot be empty")
        
        metrics = {}
        for model in self.models:
            try:
                metrics[model.__class__.__name__] = model.train(training_data, **kwargs)
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(
                    "Failed to train model %s in ensemble: %s", 
                    model.__class__.__name__, e
                )
                metrics[model.__class__.__name__] = {"error": str(e)}
        return metrics

    def predict(self, features: dict) -> dict:
        """Average probabilities from all models using fallback mechanism.
        
        This method is thread-safe as individual models handle their own locking.
        """
        # Each individual model handles its own thread safety
        # No additional locking needed at ensemble level
        return self._ensemble_predict(features)
    
    def _ensemble_predict(self, features: dict) -> dict:
        """Internal prediction method that aggregates results from all models."""
        prepared = self._prepare_features_for_model(features)
        probs_accum = None
        classes = None
        active_models = 0
        
        for model in self.models:
            if not hasattr(model, "model") or model.model is None:
                continue
                
            try:
                if isinstance(model, LSTMSelector):
                    if model.classes_ is None:
                        continue
                    # Use the model's own predict method to avoid duplication
                    result = model.predict(prepared)
                    if result["antenna_id"] == FALLBACK_ANTENNA_ID:
                        continue
                    # Convert single prediction to probability array
                    model_classes = model.classes_
                    prob = np.zeros(len(model_classes))
                    if result["antenna_id"] in model_classes:
                        idx = model_classes.index(result["antenna_id"])
                        prob[idx] = result["confidence"]
                else:
                    # Use BaseModelMixin's validate_features if available
                    if hasattr(model, 'validate_features'):
                        model.validate_features(prepared)
                    
                    X = np.array([[prepared[name] for name in model.feature_names]], dtype=float)
                    if hasattr(model, "scaler") and model.scaler is not None:
                        X = model.scaler.transform(X)
                    prob = model.model.predict_proba(X)[0]
                    model_classes = list(model.model.classes_)
                
                # Initialize accumulator with first valid model
                if probs_accum is None:
                    probs_accum = np.zeros(len(model_classes))
                    classes = model_classes
                
                # Align probabilities across different class orders
                aligned = np.zeros(len(classes))
                for idx, cls in enumerate(model_classes):
                    if cls in classes:
                        aligned[classes.index(cls)] = prob[idx]
                
                probs_accum += aligned
                active_models += 1
                
            except Exception as exc:
                # Log but don't fail - ensemble should be robust
                import logging
                logging.getLogger(__name__).warning(
                    "Model %s failed in ensemble: %s", model.__class__.__name__, exc
                )
                continue
        
        if probs_accum is None or active_models == 0:
            raise ValueError("No models produced valid predictions")
        
        # Average the probabilities
        probs = probs_accum / active_models
        idx = int(np.argmax(probs))
        return {"antenna_id": classes[idx], "confidence": float(probs[idx])}
