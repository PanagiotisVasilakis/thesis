"""SHAP visualization validation for thesis figures.

Fix #28: SHAP Configuration Based on Use Case
Fix #29: SHAP Visualization Validation

This module provides validation and generation of SHAP visualizations
suitable for thesis publication.

Features:
- Validates SHAP plots meet publication standards
- Generates consistent SHAP figures across experiments
- Provides sanity checks for feature importance ordering
- Validates SHAP additivity property visually
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# Import from shared utilities (Refactor #1 & #2: Consolidated imports and save helper)
from scripts.visualization._utils import (
    MATPLOTLIB_AVAILABLE,
    SHAP_AVAILABLE,
    plt,
    Figure,
    shap,
    save_figure_multiformat,
)

# =============================================================================
# SHAP EXTRACTION UTILITIES
# =============================================================================

def _extract_shap_safely(
    shap_values: Any,
    feature_names: List[str],
    predicted_class_idx: int = 1,
) -> Optional[np.ndarray]:
    """Safely extract SHAP values handling different formats.
    
    Fix #14: Robust SHAP extraction.
    
    SHAP can return values in multiple formats depending on:
    - Model type (tree vs linear vs kernel)
    - Number of classes (binary vs multiclass)
    - SHAP version
    
    Supported formats:
        - Format 1: List of arrays [negative_class, positive_class]
        - Format 2: Single 2D array (n_samples, n_features)
        - Format 3: 3D array (n_samples, n_classes, n_features)
        - Format 4: shap.Explanation object
    
    Args:
        shap_values: Raw SHAP output (various formats)
        feature_names: List of feature names for validation
        predicted_class_idx: Index of class to extract (default 1 for binary positive)
        
    Returns:
        2D array of SHAP values (n_samples, n_features), or None on error
        
    Example:
        >>> explainer = shap.TreeExplainer(model)
        >>> raw_shap = explainer.shap_values(X_test)
        >>> shap_array = _extract_shap_safely(raw_shap, feature_names)
    """
    try:
        n_features = len(feature_names)
        
        # Format 4: shap.Explanation object (newer SHAP versions)
        if SHAP_AVAILABLE and hasattr(shap, 'Explanation'):
            if isinstance(shap_values, shap.Explanation):
                values = shap_values.values
                if values.ndim == 3:
                    # Multi-class: (n_samples, n_features, n_classes)
                    values = values[:, :, predicted_class_idx]
                logger.debug("Extracted SHAP from Explanation object: shape %s", values.shape)
                return values
        
        # Format 1: List of arrays (one per class)
        if isinstance(shap_values, list):
            if len(shap_values) == 0:
                logger.error("Empty SHAP values list")
                return None
            
            # Select the appropriate class
            if len(shap_values) > predicted_class_idx:
                values = shap_values[predicted_class_idx]
            else:
                values = shap_values[-1]  # Fallback to last class
                logger.warning(
                    "Requested class %d but only %d classes available, using last",
                    predicted_class_idx, len(shap_values)
                )
            
            values = np.array(values)
            logger.debug("Extracted SHAP from list: shape %s", values.shape)
            
        elif isinstance(shap_values, np.ndarray):
            values = shap_values
            
            # Format 3: 3D array (n_samples, n_classes, n_features) or
            #           (n_samples, n_features, n_classes)
            if values.ndim == 3:
                # Determine axis order by checking which dimension matches n_features
                if values.shape[1] == n_features:
                    # Shape: (n_samples, n_features, n_classes)
                    values = values[:, :, predicted_class_idx]
                elif values.shape[2] == n_features:
                    # Shape: (n_samples, n_classes, n_features)
                    values = values[:, predicted_class_idx, :]
                else:
                    logger.error(
                        "Cannot determine 3D SHAP layout: shape %s, n_features=%d",
                        values.shape, n_features
                    )
                    return None
                logger.debug("Extracted SHAP from 3D array: shape %s", values.shape)
            
            # Format 2: 2D array (n_samples, n_features) - already correct
            elif values.ndim == 2:
                logger.debug("SHAP already 2D: shape %s", values.shape)
            
            # 1D array (single sample)
            elif values.ndim == 1:
                values = values.reshape(1, -1)
                logger.debug("Reshaped 1D SHAP to 2D: shape %s", values.shape)
            
            else:
                logger.error("Unexpected SHAP array dimensions: %d", values.ndim)
                return None
        else:
            logger.error("Unexpected SHAP type: %s", type(shap_values))
            return None
        
        # Validate feature dimension
        if values.shape[-1] != n_features:
            logger.error(
                "SHAP values feature mismatch: got %d, expected %d features",
                values.shape[-1], n_features
            )
            return None
        
        # Check for NaN/Inf
        if np.any(np.isnan(values)):
            logger.warning("NaN values detected in extracted SHAP values")
        if np.any(np.isinf(values)):
            logger.warning("Inf values detected in extracted SHAP values")
        
        return values
        
    except Exception as e:
        logger.error("Failed to extract SHAP values: %s", e)
        return None


def _extract_expected_value_safely(
    expected_value: Any,
    predicted_class_idx: int = 1,
) -> Optional[float]:
    """Safely extract SHAP expected value (base value).
    
    Args:
        expected_value: Raw expected value from SHAP explainer
        predicted_class_idx: Class index for multi-class
        
    Returns:
        Float base value, or None on error
    """
    try:
        if isinstance(expected_value, np.ndarray):
            if expected_value.ndim == 0:
                return float(expected_value)
            elif len(expected_value) > predicted_class_idx:
                return float(expected_value[predicted_class_idx])
            else:
                return float(expected_value[-1])
        elif isinstance(expected_value, (list, tuple)):
            if len(expected_value) > predicted_class_idx:
                return float(expected_value[predicted_class_idx])
            else:
                return float(expected_value[-1])
        else:
            return float(expected_value)
    except Exception as e:
        logger.error("Failed to extract expected value: %s", e)
        return None


# =============================================================================
# EXPECTED FEATURE IMPORTANCE
# =============================================================================

# Based on domain knowledge, these features should be most important
# Used for sanity checking SHAP results
EXPECTED_TOP_FEATURES = {
    "handover_prediction": [
        "rsrp_serving",
        "rsrp_delta",  # or rsrp_target - rsrp_serving
        "velocity",
        "rsrp_trend",
        "time_since_last_handover",
        "distance_to_target",
    ],
    "qos_prediction": [
        "sinr",
        "rsrp_serving",
        "load_serving_cell",
        "velocity",
        "buffer_occupancy",
    ],
}

# Features that should NOT be in top 5 (would indicate data leakage or bugs)
SUSPICIOUS_TOP_FEATURES = [
    "ue_id",
    "cell_id",
    "timestamp",
    "experiment_id",
    "seed",
]


# =============================================================================
# VALIDATION FUNCTIONS
# =============================================================================

@dataclass
class SHAPValidationResult:
    """Result of SHAP validation."""
    is_valid: bool
    warnings: List[str]
    errors: List[str]
    feature_importance_order: List[str]
    top_5_features: List[Tuple[str, float]]
    additivity_check_passed: bool
    
    def summary(self) -> str:
        """Generate human-readable summary."""
        lines = [
            "SHAP Validation Result",
            "=" * 40,
            f"Valid: {'✓ Yes' if self.is_valid else '✗ No'}",
            f"Additivity: {'✓ Pass' if self.additivity_check_passed else '✗ Fail'}",
            "",
            "Top 5 Features:",
        ]
        
        for name, importance in self.top_5_features:
            lines.append(f"  {importance:.4f} - {name}")
        
        if self.warnings:
            lines.append("")
            lines.append("Warnings:")
            for w in self.warnings:
                lines.append(f"  ⚠ {w}")
        
        if self.errors:
            lines.append("")
            lines.append("Errors:")
            for e in self.errors:
                lines.append(f"  ✗ {e}")
        
        return "\n".join(lines)


def validate_shap_values(
    shap_values: np.ndarray,
    feature_names: List[str],
    expected_value: float,
    predictions: np.ndarray,
    task_type: str = "handover_prediction",
    tolerance: float = 0.01,
) -> SHAPValidationResult:
    """Validate SHAP values for sanity and correctness.
    
    Fix #29: SHAP Visualization Validation
    
    Args:
        shap_values: SHAP values array (n_samples, n_features)
        feature_names: Feature names
        expected_value: SHAP base value
        predictions: Model predictions (log-odds for classification)
        task_type: Type of prediction task
        tolerance: Tolerance for additivity check
        
    Returns:
        SHAPValidationResult
    """
    warnings = []
    errors = []
    
    # Check 1: Additivity property
    # sum(SHAP values) + expected_value ≈ prediction
    shap_sums = np.sum(shap_values, axis=1)
    reconstructed = shap_sums + expected_value
    
    if predictions is not None:
        relative_errors = np.abs(reconstructed - predictions) / (np.abs(predictions) + 1e-10)
        additivity_passed = np.mean(relative_errors < tolerance) > 0.95
        
        if not additivity_passed:
            errors.append(
                f"Additivity check failed: mean relative error = {np.mean(relative_errors):.4f}"
            )
    else:
        additivity_passed = True  # Can't check without predictions
        warnings.append("Predictions not provided - skipping additivity check")
    
    # Check 2: Feature importance ordering
    mean_abs_importance = np.mean(np.abs(shap_values), axis=0)
    sorted_indices = np.argsort(mean_abs_importance)[::-1]
    feature_order = [feature_names[i] for i in sorted_indices]
    
    top_5 = [
        (feature_names[i], mean_abs_importance[i])
        for i in sorted_indices[:5]
    ]
    
    # Check 3: Suspicious features in top 5
    for name, _ in top_5:
        if name.lower() in [s.lower() for s in SUSPICIOUS_TOP_FEATURES]:
            errors.append(f"Suspicious feature in top 5: '{name}' - possible data leakage")
    
    # Check 4: Expected features present in top 10
    if task_type in EXPECTED_TOP_FEATURES:
        expected = EXPECTED_TOP_FEATURES[task_type]
        top_10_names = [feature_names[i].lower() for i in sorted_indices[:10]]
        
        found = sum(1 for exp in expected if any(exp in name for name in top_10_names))
        if found < len(expected) // 2:
            warnings.append(
                f"Only {found}/{len(expected)} expected features in top 10"
            )
    
    # Check 5: SHAP values reasonable range
    max_abs_shap = np.max(np.abs(shap_values))
    if max_abs_shap > 10:
        warnings.append(f"Large SHAP values detected: max |SHAP| = {max_abs_shap:.2f}")
    
    # Check 6: No NaN or Inf
    if np.any(np.isnan(shap_values)):
        errors.append("NaN values detected in SHAP values")
    if np.any(np.isinf(shap_values)):
        errors.append("Inf values detected in SHAP values")
    
    # Determine overall validity
    is_valid = len(errors) == 0
    
    return SHAPValidationResult(
        is_valid=is_valid,
        warnings=warnings,
        errors=errors,
        feature_importance_order=feature_order,
        top_5_features=top_5,
        additivity_check_passed=additivity_passed,
    )


# =============================================================================
# SHAP PLOT GENERATION
# =============================================================================

def generate_thesis_shap_summary(
    shap_values: np.ndarray,
    feature_names: List[str],
    feature_data: np.ndarray,
    output_path: Path,
    title: str = "Feature Importance (SHAP Values)",
    max_display: int = 15,
    show_colorbar: bool = True,
) -> Optional[Path]:
    """Generate publication-quality SHAP summary plot.
    
    Fix #28: SHAP Configuration Based on Use Case
    
    Creates a beeswarm plot showing:
    - Feature importance ranking
    - Impact direction (positive/negative)
    - Feature value correlation with impact
    
    Args:
        shap_values: SHAP values (n_samples, n_features)
        feature_names: Feature names
        feature_data: Original feature values (n_samples, n_features)
        output_path: Path to save figure
        title: Figure title
        max_display: Maximum features to show
        show_colorbar: Whether to show value colorbar
        
    Returns:
        Path to saved figure or None on error
    """
    if not SHAP_AVAILABLE or not MATPLOTLIB_AVAILABLE:
        logger.warning("SHAP or matplotlib not available")
        return None
    
    try:
        # Import publication plot settings
        from scripts.visualization.publication_plots import (
            setup_publication_style,
            DEFAULT_CONFIG,
            COLORBLIND_PALETTE,
        )
        
        setup_publication_style()
        
        # Create figure
        fig, ax = plt.subplots(figsize=(10, 8))
        
        # Calculate mean absolute SHAP for ordering
        mean_abs_shap = np.mean(np.abs(shap_values), axis=0)
        sorted_indices = np.argsort(mean_abs_shap)[-max_display:]
        
        # Use seeded RNG for reproducible jitter in plot
        plot_rng = np.random.default_rng(seed=42)
        
        # Prepare data for beeswarm
        for i, feature_idx in enumerate(sorted_indices):
            feature_shap = shap_values[:, feature_idx]
            feature_vals = feature_data[:, feature_idx]
            
            # Normalize feature values for coloring
            val_min, val_max = np.min(feature_vals), np.max(feature_vals)
            if val_max > val_min:
                normalized_vals = (feature_vals - val_min) / (val_max - val_min)
            else:
                # All feature values are identical (constant feature)
                # Use zeros so all points get the same neutral color
                normalized_vals = np.zeros_like(feature_vals)
            
            # Jitter y position (seeded for reproducibility)
            y = np.ones_like(feature_shap) * i + plot_rng.standard_normal(len(feature_shap)) * 0.1
            
            scatter = ax.scatter(
                feature_shap, y,
                c=normalized_vals,
                cmap='coolwarm',
                alpha=0.6,
                s=10,
                vmin=0, vmax=1,
            )
        
        # Y-axis labels (feature names)
        ax.set_yticks(range(len(sorted_indices)))
        ax.set_yticklabels([feature_names[i] for i in sorted_indices])
        
        # X-axis
        ax.set_xlabel("SHAP Value (impact on prediction)")
        ax.axvline(x=0, color='gray', linestyle='-', linewidth=0.5, alpha=0.5)
        
        # Title
        if title:
            ax.set_title(title, pad=15)
        
        # Colorbar
        if show_colorbar:
            cbar = plt.colorbar(scatter, ax=ax, pad=0.02)
            cbar.set_label("Feature Value (normalized)")
        
        # Remove top/right spines
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        
        # Save using shared utility (Refactor #2)
        output_path = Path(output_path)  # Ensure Path type
        saved = save_figure_multiformat(
            fig=fig,
            output_path=output_path,
            dpi_raster=DEFAULT_CONFIG.dpi_raster,
            dpi_vector=DEFAULT_CONFIG.dpi_line_art,
            formats=('png', 'pdf'),
        )
        
        plt.close(fig)
        
        logger.info("Saved SHAP summary to %s", output_path)
        return output_path if saved else None
        
    except Exception as e:
        logger.error("Failed to generate SHAP summary: %s", e)
        return None


def generate_thesis_shap_bar(
    shap_values: np.ndarray,
    feature_names: List[str],
    output_path: Path,
    title: str = "Mean |SHAP| Feature Importance",
    max_display: int = 15,
    color: str = None,
) -> Optional[Path]:
    """Generate publication-quality SHAP bar chart.
    
    Simpler visualization showing mean absolute SHAP values.
    Better for presentations and thesis figures where beeswarm
    may be too complex.
    
    Args:
        shap_values: SHAP values (n_samples, n_features)
        feature_names: Feature names
        output_path: Path to save figure
        title: Figure title
        max_display: Maximum features to show
        color: Bar color (uses ML color from palette if None)
        
    Returns:
        Path to saved figure or None on error
    """
    if not MATPLOTLIB_AVAILABLE:
        logger.warning("Matplotlib not available")
        return None
    
    try:
        from scripts.visualization.publication_plots import (
            setup_publication_style,
            DEFAULT_CONFIG,
            COLORBLIND_PALETTE,
        )
        
        setup_publication_style()
        
        # Calculate mean absolute SHAP
        mean_abs_shap = np.mean(np.abs(shap_values), axis=0)
        sorted_indices = np.argsort(mean_abs_shap)[-max_display:]
        
        sorted_names = [feature_names[i] for i in sorted_indices]
        sorted_values = mean_abs_shap[sorted_indices]
        
        # Create figure
        fig, ax = plt.subplots(figsize=(8, 6))
        
        bar_color = color or COLORBLIND_PALETTE['ml']
        
        bars = ax.barh(
            range(len(sorted_indices)),
            sorted_values,
            color=bar_color,
            edgecolor='none',
            alpha=0.8,
        )
        
        # Y-axis labels
        ax.set_yticks(range(len(sorted_indices)))
        ax.set_yticklabels(sorted_names)
        
        # X-axis
        ax.set_xlabel("Mean |SHAP Value|")
        
        # Title
        if title:
            ax.set_title(title, pad=15)
        
        # Remove top/right spines
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        
        # Add value labels on bars
        for bar, val in zip(bars, sorted_values):
            ax.text(
                bar.get_width() + 0.005,
                bar.get_y() + bar.get_height() / 2,
                f'{val:.3f}',
                va='center',
                fontsize=DEFAULT_CONFIG.font_size_annotation,
            )
        
        # Save using shared utility (Refactor #2)
        output_path = Path(output_path)  # Ensure Path type
        saved = save_figure_multiformat(
            fig=fig,
            output_path=output_path,
            dpi_raster=DEFAULT_CONFIG.dpi_raster,
            dpi_vector=DEFAULT_CONFIG.dpi_line_art,
            formats=('png', 'pdf'),
        )
        
        plt.close(fig)
        
        logger.info("Saved SHAP bar chart to %s", output_path)
        return output_path if saved else None
        
    except Exception as e:
        logger.error("Failed to generate SHAP bar chart: %s", e)
        return None


def generate_thesis_waterfall(
    shap_values: np.ndarray,
    feature_names: List[str],
    expected_value: float,
    sample_idx: int,
    output_path: Path,
    title: str = "Single Prediction Explanation",
    max_display: int = 10,
) -> Optional[Path]:
    """Generate waterfall plot for single prediction.
    
    Shows how each feature contributes to moving the prediction
    from the base value to the final prediction.
    
    Args:
        shap_values: SHAP values (n_samples, n_features)
        feature_names: Feature names
        expected_value: Base value
        sample_idx: Index of sample to explain
        output_path: Path to save figure
        title: Figure title
        max_display: Maximum features to show
        
    Returns:
        Path to saved figure or None on error
    """
    if not SHAP_AVAILABLE or not MATPLOTLIB_AVAILABLE:
        logger.warning("SHAP or matplotlib not available")
        return None
    
    try:
        from scripts.visualization.publication_plots import (
            setup_publication_style,
            DEFAULT_CONFIG,
            COLORBLIND_PALETTE,
        )
        
        setup_publication_style()
        
        # Validate sample_idx bounds
        if sample_idx < 0 or sample_idx >= len(shap_values):
            raise ValueError(
                f"sample_idx {sample_idx} out of bounds [0, {len(shap_values)-1}]"
            )
        
        # Get SHAP values for this sample
        sample_shap = shap_values[sample_idx]
        
        # Sort by absolute value
        sorted_indices = np.argsort(np.abs(sample_shap))[::-1][:max_display]
        
        # Prepare waterfall data
        values = [sample_shap[i] for i in sorted_indices]
        names = [feature_names[i] for i in sorted_indices]
        
        # Create waterfall visualization
        fig, ax = plt.subplots(figsize=(10, 6))
        
        current = expected_value
        y_positions = range(len(values), 0, -1)
        
        # Draw bars (using colorblind-safe palette)
        for i, (val, name, y) in enumerate(zip(values, names, y_positions)):
            color = COLORBLIND_PALETTE['ml'] if val > 0 else COLORBLIND_PALETTE['error']
            
            ax.barh(
                y, val,
                left=current if val > 0 else current + val,
                color=color,
                height=0.6,
                alpha=0.8,
            )
            
            # Add value annotation
            text_x = current + val / 2
            ax.text(
                text_x, y,
                f'{val:+.3f}',
                ha='center', va='center',
                fontsize=DEFAULT_CONFIG.font_size_annotation,
                color='white',
            )
            
            # Update running total
            current += val
        
        # Y-axis labels
        ax.set_yticks(list(y_positions))
        ax.set_yticklabels(names)
        
        # Add base value and final value annotations
        ax.axvline(x=expected_value, color='gray', linestyle='--', linewidth=1, label='Base value')
        
        final_value = expected_value + np.sum(sample_shap)
        ax.axvline(x=final_value, color='black', linestyle='-', linewidth=1, label='Prediction')
        
        ax.set_xlabel("Impact on Prediction")
        if title:
            ax.set_title(title, pad=15)
        
        ax.legend(loc='best')
        
        # Remove spines
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        
        # Save using shared utility (Refactor #2) - add PDF for consistency
        output_path = Path(output_path)  # Ensure Path type
        saved = save_figure_multiformat(
            fig=fig,
            output_path=output_path,
            dpi_raster=DEFAULT_CONFIG.dpi_raster,
            dpi_vector=DEFAULT_CONFIG.dpi_line_art,
            formats=('png', 'pdf'),
        )
        
        plt.close(fig)
        
        logger.info("Saved waterfall plot to %s", output_path)
        return output_path if saved else None
        
    except Exception as e:
        logger.error("Failed to generate waterfall plot: %s", e)
        return None


# =============================================================================
# BATCH VALIDATION
# =============================================================================

def validate_and_generate_shap_figures(
    model: Any,
    X_test: np.ndarray,
    feature_names: List[str],
    output_dir: Path,
    task_type: str = "handover_prediction",
) -> Dict[str, Any]:
    """Complete SHAP analysis pipeline for thesis.
    
    Performs:
    1. SHAP value computation
    2. Validation
    3. Figure generation (summary, bar, waterfall)
    
    Args:
        model: Trained model
        X_test: Test data
        feature_names: Feature names
        output_dir: Directory for outputs
        task_type: Type of prediction task
        
    Returns:
        Dictionary with validation results and figure paths
    """
    results = {
        "validation": None,
        "figures": {},
        "errors": [],
    }
    
    if not SHAP_AVAILABLE:
        results["errors"].append("SHAP not available")
        return results
    
    try:
        # Compute SHAP values
        explainer = shap.TreeExplainer(model)
        shap_values = explainer.shap_values(X_test)
        
        # Handle multi-class
        if isinstance(shap_values, list):
            shap_values = shap_values[1]  # Positive class
        
        expected_value = explainer.expected_value
        if isinstance(expected_value, np.ndarray):
            expected_value = expected_value[1]
        
        # Get predictions for validation
        try:
            predictions = model.predict(X_test, raw_score=True)
        except (TypeError, AttributeError, ValueError) as e:
            # Some models don't support raw_score parameter
            logger.debug("Could not get raw predictions: %s", e)
            predictions = None
        
        # Validate
        validation = validate_shap_values(
            shap_values=shap_values,
            feature_names=feature_names,
            expected_value=expected_value,
            predictions=predictions,
            task_type=task_type,
        )
        results["validation"] = validation
        
        # Generate figures
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Summary plot
        summary_path = generate_thesis_shap_summary(
            shap_values=shap_values,
            feature_names=feature_names,
            feature_data=X_test,
            output_path=output_dir / "shap_summary.png",
        )
        if summary_path:
            results["figures"]["summary"] = summary_path
        
        # Bar plot
        bar_path = generate_thesis_shap_bar(
            shap_values=shap_values,
            feature_names=feature_names,
            output_path=output_dir / "shap_bar.png",
        )
        if bar_path:
            results["figures"]["bar"] = bar_path
        
        # Waterfall for a representative sample
        # Choose sample with median prediction
        pred_values = model.predict(X_test)
        median_idx = np.argsort(pred_values)[len(pred_values) // 2]
        
        waterfall_path = generate_thesis_waterfall(
            shap_values=shap_values,
            feature_names=feature_names,
            expected_value=expected_value,
            sample_idx=median_idx,
            output_path=output_dir / "shap_waterfall.png",
        )
        if waterfall_path:
            results["figures"]["waterfall"] = waterfall_path
        
        logger.info("SHAP analysis complete: %d figures generated", len(results['figures']))
        
    except Exception as e:
        logger.error("SHAP analysis failed: %s", e)
        results["errors"].append(str(e))
    
    return results


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    'SHAPValidationResult',
    'validate_shap_values',
    'generate_thesis_shap_summary',
    'generate_thesis_shap_bar',
    'generate_thesis_waterfall',
    'validate_and_generate_shap_figures',
    'EXPECTED_TOP_FEATURES',
    'SUSPICIOUS_TOP_FEATURES',
    # Fix #14: Robust SHAP extraction
    '_extract_shap_safely',
    '_extract_expected_value_safely',
]
