"""Model interpretability utilities using SHAP.

This module provides explainability features for the ML handover model,
generating visualizations and explanations that can be used in thesis
documentation and for debugging model behavior.

Implements Fix #14 and Fix #15 from the thesis implementation plan:

Fix #14: SHAP Value Extraction Robustness
- Handles different SHAP output formats (list, 2D array, 3D array)
- Validates SHAP additivity property
- Defensive extraction with type checking

Fix #15: SHAP Performance Configuration
- Three operational modes: disabled, sampled, always
- Configurable sampling rate for batch experiments
- Mode selection based on use case

Usage:
    from ml_service.app.models.interpretability import (
        ModelExplainer,
        SHAPConfig,
        SHAPMode
    )
    
    # Configure SHAP mode
    config = SHAPConfig(mode=SHAPMode.SAMPLED, sample_rate=0.1)
    explainer = ModelExplainer(model, feature_names, shap_config=config)
    
    # Explain prediction (respects configuration)
    explanation = explainer.explain_prediction(features)
"""
from __future__ import annotations

import logging
import os
import random
from dataclasses import dataclass
from enum import Enum
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


class SHAPMode(Enum):
    """SHAP computation modes for different use cases.
    
    Fix #15: SHAP Performance Configuration
    """
    OFF = "off"           # SHAP disabled (fastest, for batch experiments)
    SAMPLED = "sampled"   # SHAP computed for X% of decisions
    ALWAYS = "always"     # SHAP computed for every decision (UI/demo)


@dataclass
class SHAPConfig:
    """Configuration for SHAP explanation behavior.
    
    Fix #15: Configuration-based SHAP control.
    """
    mode: SHAPMode = SHAPMode.OFF
    sample_rate: float = 0.1  # Only used when mode=SAMPLED (10% default)
    validate_additivity: bool = False  # Check SHAP sum ≈ prediction - base
    additivity_tolerance: float = 0.01  # 1% tolerance for additivity check
    
    @classmethod
    def from_env(cls) -> "SHAPConfig":
        """Create config from environment variables.
        
        Environment variables:
            SHAP_ENABLED: true/false
            SHAP_MODE: off/sampled/always
            SHAP_SAMPLE_RATE: 0.0-1.0
            SHAP_VALIDATE_ADDITIVITY: true/false
        """
        enabled = os.getenv("SHAP_ENABLED", "false").lower() in ("1", "true", "yes")
        if not enabled:
            return cls(mode=SHAPMode.OFF)
        
        mode_str = os.getenv("SHAP_MODE", "off").lower()
        try:
            mode = SHAPMode(mode_str)
        except ValueError:
            mode = SHAPMode.OFF
        
        sample_rate = float(os.getenv("SHAP_SAMPLE_RATE", "0.1"))
        validate = os.getenv("SHAP_VALIDATE_ADDITIVITY", "false").lower() in ("1", "true")
        
        return cls(
            mode=mode,
            sample_rate=max(0.0, min(1.0, sample_rate)),
            validate_additivity=validate,
        )
    
    def should_compute_shap(self) -> bool:
        """Determine if SHAP should be computed for this call.
        
        Returns:
            True if SHAP should be computed
        """
        if self.mode == SHAPMode.OFF:
            return False
        if self.mode == SHAPMode.ALWAYS:
            return True
        # SAMPLED mode - random decision
        return random.random() < self.sample_rate


class ModelExplainer:
    """Provides SHAP-based explanations for handover predictions.
    
    This class wraps a trained LightGBM model and provides methods to
    explain individual predictions and generate summary visualizations.
    
    Implements Fix #14: Robust SHAP extraction handling different formats.
    Implements Fix #15: Configurable SHAP modes for different use cases.
    
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
        shap_config: Optional[SHAPConfig] = None,
    ):
        """Initialize the model explainer.
        
        Args:
            model: Trained LightGBM classifier
            feature_names: List of feature names in order
            background_samples: Optional background dataset for SHAP
            shap_config: SHAP configuration (uses env vars if None)
        """
        self.model = model
        self.feature_names = feature_names
        self.background_samples = background_samples
        self.explainer = None
        
        # Fix #15: Configuration-based SHAP control
        self.config = shap_config or SHAPConfig.from_env()
        
        # Only initialize explainer if SHAP might be used
        if SHAP_AVAILABLE and model is not None and self.config.mode != SHAPMode.OFF:
            self._initialize_explainer()
        
        logger.info(
            "ModelExplainer initialized: mode=%s, sample_rate=%.2f",
            self.config.mode.value, self.config.sample_rate
        )
    
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
    
    def _extract_shap_safely(
        self,
        shap_values: Any,
        predicted_class_idx: int,
    ) -> Optional[np.ndarray]:
        """Safely extract SHAP values handling different formats.
        
        Fix #14: Robust SHAP extraction.
        
        SHAP can return:
        - Format 1: List of two arrays [negative_class, positive_class]
        - Format 2: Single 2D array (n_samples, n_features)
        - Format 3: 3D array (n_samples, n_classes, n_features)
        
        Args:
            shap_values: Raw SHAP output
            predicted_class_idx: Index of predicted class
            
        Returns:
            1D array of SHAP values for the predicted class, or None on error
        """
        try:
            # Step 1: Check type
            if isinstance(shap_values, list):
                # Format 1: List of arrays (one per class)
                if len(shap_values) > predicted_class_idx:
                    values = shap_values[predicted_class_idx]
                else:
                    values = shap_values[-1]  # Fallback to last class
                
                # Handle if it's 2D (n_samples, n_features)
                if values.ndim == 2:
                    values = values[0]  # Take first sample
                    
            elif isinstance(shap_values, np.ndarray):
                # Step 2: Check dimensions
                if shap_values.ndim == 3:
                    # Format 3: (n_samples, n_classes, n_features)
                    values = shap_values[0, predicted_class_idx, :]
                elif shap_values.ndim == 2:
                    # Format 2: (n_samples, n_features)
                    values = shap_values[0, :]
                elif shap_values.ndim == 1:
                    # Already 1D
                    values = shap_values
                else:
                    logger.error(f"Unexpected SHAP array dimensions: {shap_values.ndim}")
                    return None
            else:
                logger.error(f"Unexpected SHAP type: {type(shap_values)}")
                return None
            
            # Step 3: Validate length
            if len(values) != len(self.feature_names):
                logger.error(
                    f"SHAP values length mismatch: got {len(values)}, "
                    f"expected {len(self.feature_names)}"
                )
                return None
            
            return np.array(values)
            
        except Exception as e:
            logger.error(f"Failed to extract SHAP values: {e}")
            return None
    
    def _validate_additivity(
        self,
        shap_values: np.ndarray,
        expected_value: float,
        prediction_log_odds: float,
    ) -> bool:
        """Validate SHAP additivity property.
        
        Fix #14: SHAP values should sum to (prediction - base_value).
        
        Args:
            shap_values: Extracted SHAP values
            expected_value: SHAP base/expected value
            prediction_log_odds: Model's log-odds prediction
            
        Returns:
            True if additivity holds within tolerance
        """
        if not self.config.validate_additivity:
            return True  # Skip validation if disabled
        
        shap_sum = np.sum(shap_values)
        expected_sum = prediction_log_odds - expected_value
        
        relative_error = abs(shap_sum - expected_sum) / (abs(expected_sum) + 1e-10)
        
        if relative_error > self.config.additivity_tolerance:
            logger.warning(
                f"SHAP additivity violated: sum={shap_sum:.4f}, "
                f"expected={expected_sum:.4f}, error={relative_error:.2%}"
            )
            return False
        
        return True
    
    def explain_prediction(
        self,
        features: Dict[str, float],
        top_k: int = 5,
        force_compute: bool = False,
    ) -> Dict[str, Any]:
        """Explain a single prediction.
        
        Fix #14: Robust extraction with format handling.
        Fix #15: Respects SHAP configuration mode.
        
        Args:
            features: Feature dictionary for the prediction
            top_k: Number of top features to return
            force_compute: If True, compute SHAP regardless of mode
            
        Returns:
            Dictionary containing:
                - prediction: Predicted class
                - confidence: Prediction confidence
                - top_positive_features: Features pushing toward prediction
                - top_negative_features: Features pushing against prediction
                - all_shap_values: Complete SHAP values
                - shap_computed: Whether SHAP was actually computed
        """
        # Fix #15: Check if SHAP should be computed
        if not force_compute and not self.config.should_compute_shap():
            # Return basic prediction without SHAP
            return self._predict_without_shap(features)
        
        if not self.is_available():
            return {
                "error": "SHAP not available",
                "prediction": None,
                "confidence": None,
                "shap_computed": False,
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
            
            # Fix #14: Safely extract SHAP values
            class_shap_values = self._extract_shap_safely(shap_values, predicted_class_idx)
            
            if class_shap_values is None:
                return {
                    "error": "Failed to extract SHAP values",
                    "prediction": str(predicted_class),
                    "confidence": confidence,
                    "shap_computed": False,
                }
            
            # Fix #14: Validate additivity if enabled
            expected_value = self.explainer.expected_value
            if isinstance(expected_value, (list, np.ndarray)):
                expected_value = expected_value[predicted_class_idx]
            
            self._validate_additivity(
                class_shap_values,
                float(expected_value),
                float(np.log(confidence / (1 - confidence + 1e-10)))  # Log-odds
            )
            
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
                "expected_value": float(expected_value),
                "shap_computed": True,
            }
        except Exception as e:
            logger.error(f"Failed to explain prediction: {e}")
            return {
                "error": str(e),
                "prediction": None,
                "confidence": None,
                "shap_computed": False,
            }
    
    def _predict_without_shap(self, features: Dict[str, float]) -> Dict[str, Any]:
        """Make prediction without computing SHAP values.
        
        Used when SHAP is disabled or sampled out.
        """
        try:
            X = np.array([[features.get(name, 0.0) for name in self.feature_names]])
            prediction_proba = self.model.predict_proba(X)[0]
            predicted_class_idx = np.argmax(prediction_proba)
            predicted_class = self.model.classes_[predicted_class_idx]
            confidence = float(prediction_proba[predicted_class_idx])
            
            return {
                "prediction": str(predicted_class),
                "confidence": confidence,
                "shap_computed": False,
            }
        except Exception as e:
            logger.error(f"Prediction failed: {e}")
            return {
                "error": str(e),
                "prediction": None,
                "confidence": None,
                "shap_computed": False,
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
