"""Base mixin for common model functionality."""
import numpy as np
from typing import List, Dict, Any, Tuple
import logging

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
            
        X, y = [], []
        for sample in training_data:
            features = self.extract_features(sample)
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
        missing_features = set(self.feature_names) - set(features.keys())
        if missing_features:
            raise ValueError(f"Missing required features: {missing_features}")
    
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