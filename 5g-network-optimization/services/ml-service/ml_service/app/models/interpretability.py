"""Model interpretability utilities using SHAP.

This module provides explainability features for the ML handover model,
generating visualizations and explanations that can be used in thesis
documentation and for debugging model behavior.

Usage:
    from ml_service.app.models.interpretability import ModelExplainer
    
    explainer = ModelExplainer(model, feature_names)
    explanation = explainer.explain_prediction(features)
    explainer.generate_summary_plot(X_samples, output_path="shap_summary.png")
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

# SHAP is optional - gracefully handle if not installed
try:
    import shap
    SHAP_AVAILABLE = True
except ImportError:
    SHAP_AVAILABLE = False
    logger.warning("SHAP not installed. Interpretability features will be limited.")


class ModelExplainer:
    """Provides SHAP-based explanations for handover predictions.
    
    This class wraps a trained LightGBM model and provides methods to
    explain individual predictions and generate summary visualizations.
    
    Thesis Value:
        - Generates figures showing feature contributions
        - Validates that model learned meaningful patterns
        - Demonstrates transparency of ML decision-making
    """
    
    def __init__(
        self,
        model: Any,
        feature_names: List[str],
        background_samples: Optional[np.ndarray] = None,
    ):
        """Initialize the model explainer.
        
        Args:
            model: Trained LightGBM classifier
            feature_names: List of feature names in order
            background_samples: Optional background dataset for SHAP
        """
        self.model = model
        self.feature_names = feature_names
        self.background_samples = background_samples
        self.explainer = None
        
        if SHAP_AVAILABLE and model is not None:
            self._initialize_explainer()
    
    def _initialize_explainer(self):
        """Initialize SHAP TreeExplainer for LightGBM model."""
        try:
            self.explainer = shap.TreeExplainer(self.model)
            logger.info("SHAP TreeExplainer initialized successfully")
        except Exception as e:
            logger.warning(f"Failed to initialize SHAP explainer: {e}")
            self.explainer = None
    
    def is_available(self) -> bool:
        """Check if SHAP explanation is available."""
        return SHAP_AVAILABLE and self.explainer is not None
    
    def explain_prediction(
        self,
        features: Dict[str, float],
        top_k: int = 5,
    ) -> Dict[str, Any]:
        """Explain a single prediction.
        
        Args:
            features: Feature dictionary for the prediction
            top_k: Number of top features to return
            
        Returns:
            Dictionary containing:
                - prediction: Predicted class
                - confidence: Prediction confidence
                - top_positive_features: Features pushing toward prediction
                - top_negative_features: Features pushing against prediction
                - all_shap_values: Complete SHAP values
        """
        if not self.is_available():
            return {
                "error": "SHAP not available",
                "prediction": None,
                "confidence": None,
            }
        
        # Convert features to array
        X = np.array([[features.get(name, 0.0) for name in self.feature_names]])
        
        try:
            # Get SHAP values
            shap_values = self.explainer.shap_values(X)
            
            # Get prediction
            prediction_proba = self.model.predict_proba(X)[0]
            predicted_class_idx = np.argmax(prediction_proba)
            predicted_class = self.model.classes_[predicted_class_idx]
            confidence = float(prediction_proba[predicted_class_idx])
            
            # Get SHAP values for predicted class
            if isinstance(shap_values, list):
                # Multi-class case
                class_shap_values = shap_values[predicted_class_idx][0]
            else:
                # Binary case
                class_shap_values = shap_values[0]
            
            # Create feature importance ranking
            feature_contributions = list(zip(self.feature_names, class_shap_values))
            sorted_contributions = sorted(feature_contributions, key=lambda x: abs(x[1]), reverse=True)
            
            # Split into positive and negative
            positive_features = [(name, float(val)) for name, val in sorted_contributions if val > 0][:top_k]
            negative_features = [(name, float(val)) for name, val in sorted_contributions if val < 0][:top_k]
            
            return {
                "prediction": str(predicted_class),
                "confidence": confidence,
                "top_positive_features": positive_features,
                "top_negative_features": negative_features,
                "all_shap_values": {name: float(val) for name, val in feature_contributions},
                "expected_value": float(self.explainer.expected_value[predicted_class_idx]) if isinstance(self.explainer.expected_value, (list, np.ndarray)) else float(self.explainer.expected_value),
            }
        except Exception as e:
            logger.error(f"Failed to explain prediction: {e}")
            return {
                "error": str(e),
                "prediction": None,
                "confidence": None,
            }
    
    def generate_summary_plot(
        self,
        X: np.ndarray,
        output_path: Optional[str] = None,
        max_display: int = 15,
        plot_type: str = "bar",
    ) -> Optional[str]:
        """Generate SHAP summary plot for thesis figures.
        
        Args:
            X: Sample data to explain (numpy array)
            output_path: Path to save the figure (or None to display)
            max_display: Maximum number of features to display
            plot_type: Type of plot ('bar', 'dot', 'violin')
            
        Returns:
            Path to saved figure or None
        """
        if not self.is_available():
            logger.warning("SHAP not available for summary plot")
            return None
        
        try:
            import matplotlib
            matplotlib.use('Agg')  # Non-interactive backend
            import matplotlib.pyplot as plt
            
            # Compute SHAP values
            shap_values = self.explainer.shap_values(X)
            
            # Handle multi-class case - use absolute mean across classes
            if isinstance(shap_values, list):
                # Average across all classes for overall importance
                mean_abs_shap = np.mean([np.abs(sv) for sv in shap_values], axis=0)
                shap_values_for_plot = shap_values[0]  # Use first class for visualization
            else:
                mean_abs_shap = np.abs(shap_values)
                shap_values_for_plot = shap_values
            
            plt.figure(figsize=(12, 8))
            
            if plot_type == "bar":
                # Feature importance bar chart
                mean_importance = np.mean(np.abs(shap_values_for_plot), axis=0)
                sorted_idx = np.argsort(mean_importance)[-max_display:]
                
                plt.barh(
                    [self.feature_names[i] for i in sorted_idx],
                    mean_importance[sorted_idx],
                    color='#1f77b4'
                )
                plt.xlabel('Mean |SHAP Value|', fontsize=12)
                plt.ylabel('Feature', fontsize=12)
                plt.title('Feature Importance (SHAP Values)', fontsize=14)
                plt.tight_layout()
            else:
                # Use SHAP's built-in summary plot
                shap.summary_plot(
                    shap_values_for_plot,
                    X,
                    feature_names=self.feature_names,
                    max_display=max_display,
                    plot_type=plot_type,
                    show=False,
                )
            
            if output_path:
                plt.savefig(output_path, dpi=150, bbox_inches='tight')
                plt.close()
                logger.info(f"SHAP summary plot saved to {output_path}")
                return output_path
            else:
                plt.show()
                return None
                
        except Exception as e:
            logger.error(f"Failed to generate summary plot: {e}")
            return None
    
    def get_feature_importance_ranking(
        self,
        X: np.ndarray,
    ) -> List[Tuple[str, float]]:
        """Get ranked feature importance based on SHAP values.
        
        Args:
            X: Sample data to analyze
            
        Returns:
            List of (feature_name, importance) tuples, sorted by importance
        """
        if not self.is_available():
            return []
        
        try:
            shap_values = self.explainer.shap_values(X)
            
            # Handle multi-class case
            if isinstance(shap_values, list):
                mean_abs_shap = np.mean([np.mean(np.abs(sv), axis=0) for sv in shap_values], axis=0)
            else:
                mean_abs_shap = np.mean(np.abs(shap_values), axis=0)
            
            importance_list = list(zip(self.feature_names, mean_abs_shap))
            return sorted(importance_list, key=lambda x: x[1], reverse=True)
            
        except Exception as e:
            logger.error(f"Failed to compute feature importance: {e}")
            return []


def explain_single_handover(
    model: Any,
    feature_names: List[str],
    features: Dict[str, float],
) -> Dict[str, Any]:
    """Convenience function to explain a single handover decision.
    
    Args:
        model: Trained model
        feature_names: Feature names
        features: Feature values for the prediction
        
    Returns:
        Explanation dictionary
    """
    explainer = ModelExplainer(model, feature_names)
    return explainer.explain_prediction(features)
