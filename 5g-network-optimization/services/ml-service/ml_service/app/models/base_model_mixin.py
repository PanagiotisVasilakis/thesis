"""Base mixin for common model functionality."""
import numpy as np
from typing import List, Dict, Any, Tuple
import logging

from ml_service.app.config.feature_specs import sanitize_feature_ranges, validate_feature_ranges

logger = logging.getLogger(__name__)

class BaseModelMixin:
    """Mixin providing common functionality for ML models."""
    
    def build_dataset(self, training_data: List[Dict[str, Any]]) -> Tuple[np.ndarray, np.ndarray]:
        """Convert training samples to arrays for model training.
        
        Args:
            training_data: List of training samples with features and labels
            
        Returns:
            Tuple of (features, labels) as numpy arrays
        """
        if not training_data:
            raise ValueError("Training data cannot be empty")
            
        ensure_capacity = getattr(self, "ensure_neighbor_capacity", None)
        if callable(ensure_capacity):
            max_neighbors = 0
            for sample in training_data:
                metrics = sample.get("rf_metrics") or {}
                current = sample.get("connected_to")
                neighbor_count = len([aid for aid in metrics.keys() if aid != current])
                if neighbor_count > max_neighbors:
                    max_neighbors = neighbor_count
            if max_neighbors:
                ensure_capacity(max_neighbors)

        X, y = [], []
        for sample in training_data:
            features = self.extract_features(sample)
            sanitize_feature_ranges(features)
            validate_feature_ranges(features)
            # Ensure service_type (if present) is encoded as numeric so the
            # feature vector can be converted to float. Preserve other
            # features as-is; non-numeric values will raise below.
            from ml_service.app.core.qos_encoding import encode_service_type

            svc = features.get("service_type")
            if svc is not None and not isinstance(svc, (int, float)):
                features["service_type"] = encode_service_type(svc)

            X.append([features[name] for name in self.feature_names])
            y.append(sample.get("optimal_antenna"))
            
        return np.array(X, dtype=float), np.array(y)
    
    def validate_features(self, features: Dict[str, Any]) -> None:
        """Validate that all required features are present.
        
        Args:
            features: Dictionary of feature values
            
        Raises:
            ValueError: If required features are missing
        """
        optional_features = getattr(self, "optional_feature_names", set())
        missing_features = set(self.feature_names) - set(features.keys()) - set(optional_features)
        if missing_features:
            raise ValueError(f"Missing required features: {missing_features}")

        # Ensure feature values fall within configured bounds
        sanitize_feature_ranges(features)
        validate_feature_ranges(features)
    
    def get_prediction_with_fallback(
        self, 
        features: Dict[str, Any],
        fallback_antenna: str,
        fallback_confidence: float
    ) -> Dict[str, Any]:
        """Get prediction with fallback for error cases.
        
        Args:
            features: Feature dictionary
            fallback_antenna: Default antenna ID if prediction fails
            fallback_confidence: Default confidence if prediction fails
            
        Returns:
            Dictionary with antenna_id and confidence
        """
        optional_features = getattr(self, "optional_feature_names", set())
        missing_required = set(self.feature_names) - set(features.keys()) - set(optional_features)
        if missing_required:
            logger.error(
                "Prediction skipped due to missing required features for UE %s: %s. Using fallback.",
                features.get("ue_id", "unknown"),
                sorted(missing_required),
            )
            return {
                "antenna_id": fallback_antenna,
                "confidence": fallback_confidence
            }

        try:
            return self.predict(features)
        except ValueError as exc:
            # Data validation errors
            logger.error(
                "Prediction failed due to invalid data for UE %s: %s. Using fallback.",
                features.get("ue_id", "unknown"),
                exc
            )
            return {
                "antenna_id": fallback_antenna,
                "confidence": fallback_confidence
            }
        except (TypeError, KeyError) as exc:
            # Feature processing errors
            logger.error(
                "Prediction failed due to feature error for UE %s: %s. Using fallback.",
                features.get("ue_id", "unknown"),
                exc
            )
            return {
                "antenna_id": fallback_antenna,
                "confidence": fallback_confidence
            }
        except MemoryError as exc:
            # Memory allocation errors
            logger.critical(
                "Prediction failed due to memory error for UE %s: %s. Using fallback.",
                features.get("ue_id", "unknown"),
                exc
            )
            return {
                "antenna_id": fallback_antenna,
                "confidence": fallback_confidence
            }
        except Exception as exc:
            # Catch-all for unexpected errors - log as critical for investigation
            logger.critical(
                "Unexpected prediction error for UE %s: %s (%s). Using fallback.",
                features.get("ue_id", "unknown"),
                exc,
                type(exc).__name__
            )
            return {
                "antenna_id": fallback_antenna,
                "confidence": fallback_confidence
            }