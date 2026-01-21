"""Visualization utilities for thesis figures."""
from ._utils import (
    MATPLOTLIB_AVAILABLE,
    SHAP_AVAILABLE,
    plt,
    Figure,
    Axes,
    shap,
    require_matplotlib,
    require_shap,
    save_figure_multiformat,
)

from .publication_plots import (
    PublicationConfig,
    DEFAULT_CONFIG,
    FigureFormat,
    setup_publication_style,
    COLORBLIND_PALETTE,
    SCENARIO_PALETTE,
    MARKER_STYLES,
    LINE_STYLES,
    ThesisFigure,
    plot_algorithm_comparison,
    plot_box_comparison,
    create_heatmap,
    add_significance_bars,
    validate_figure_quality,
)

from .shap_validation import (
    SHAPValidationResult,
    validate_shap_values,
    generate_thesis_shap_summary,
    generate_thesis_shap_bar,
    generate_thesis_waterfall,
    validate_and_generate_shap_figures,
    EXPECTED_TOP_FEATURES,
    SUSPICIOUS_TOP_FEATURES,
    # Fix #14: Robust SHAP extraction utilities
    _extract_shap_safely,
    _extract_expected_value_safely,
)

__all__ = [
    # Shared utils
    'MATPLOTLIB_AVAILABLE',
    'SHAP_AVAILABLE',
    'plt',
    'Figure',
    'Axes',
    'shap',
    'require_matplotlib',
    'require_shap',
    'save_figure_multiformat',
    # Publication plots
    'PublicationConfig',
    'DEFAULT_CONFIG',
    'FigureFormat',
    'setup_publication_style',
    'COLORBLIND_PALETTE',
    'SCENARIO_PALETTE',
    'MARKER_STYLES',
    'LINE_STYLES',
    'ThesisFigure',
    'plot_algorithm_comparison',
    'plot_box_comparison',
    'create_heatmap',
    'add_significance_bars',
    'validate_figure_quality',
    # SHAP validation
    'SHAPValidationResult',
    'validate_shap_values',
    'generate_thesis_shap_summary',
    'generate_thesis_shap_bar',
    'generate_thesis_waterfall',
    'validate_and_generate_shap_figures',
    'EXPECTED_TOP_FEATURES',
    'SUSPICIOUS_TOP_FEATURES',
    '_extract_shap_safely',
    '_extract_expected_value_safely',
]
