"""Shared utilities for visualization modules.

This module provides common functionality used across visualization modules
to avoid code duplication.
"""
from __future__ import annotations

import logging
from functools import wraps

logger = logging.getLogger(__name__)

# =============================================================================
# MATPLOTLIB SAFE IMPORT
# =============================================================================
# Shared pattern for safely importing matplotlib with non-interactive backend
# for headless environments (servers, CI/CD, etc.)

MATPLOTLIB_AVAILABLE = False
plt = None
Figure = None
Axes = None

try:
    import matplotlib
    matplotlib.use('Agg')  # Non-interactive backend for headless environments
    import matplotlib.pyplot as _plt
    from matplotlib.figure import Figure as _Figure
    from matplotlib.axes import Axes as _Axes
    
    plt = _plt
    Figure = _Figure
    Axes = _Axes
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    logger.warning(
        "Matplotlib not available. Plot generation disabled. "
        "Install with: pip install matplotlib"
    )


def require_matplotlib(func):
    """Decorator to check matplotlib availability before running a function.
    
    Usage:
        @require_matplotlib
        def my_plot_function(...):
            ...
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not MATPLOTLIB_AVAILABLE:
            logger.warning(
                "Cannot run %s: matplotlib not available", func.__name__
            )
            return None
        return func(*args, **kwargs)
    return wrapper


# =============================================================================
# SHAP SAFE IMPORT
# =============================================================================

SHAP_AVAILABLE = False
shap = None

try:
    import shap as _shap
    shap = _shap
    SHAP_AVAILABLE = True
except ImportError:
    logger.warning(
        "SHAP not available. Explainability features disabled. "
        "Install with: pip install shap"
    )


def require_shap(func):
    """Decorator to check SHAP availability before running a function."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not SHAP_AVAILABLE:
            logger.warning(
                "Cannot run %s: SHAP not available", func.__name__
            )
            return None
        return func(*args, **kwargs)
    return wrapper


# =============================================================================
# FIGURE SAVE UTILITIES (Refactor #2)
# =============================================================================

def save_figure_multiformat(
    fig: 'Figure',
    output_path: 'Path',
    dpi_raster: int = 300,
    dpi_vector: int = 600,
    formats: tuple = ('png', 'pdf'),
    facecolor: str = 'white',
    bbox_inches: str = 'tight',
) -> list:
    """Save figure in multiple formats for publication.
    
    This helper consolidates the repeated PNG+PDF save pattern
    used across SHAP validation and publication plot modules.
    
    Args:
        fig: Matplotlib figure to save
        output_path: Base path (extension will be replaced)
        dpi_raster: DPI for raster formats (PNG)
        dpi_vector: DPI for vector formats (PDF, SVG)
        formats: Tuple of format extensions to save
        facecolor: Background color
        bbox_inches: Bounding box setting
        
    Returns:
        List of paths where figure was saved
        
    Example:
        >>> saved = save_figure_multiformat(fig, Path("output/plot.png"))
        >>> print(saved)  # [Path("output/plot.png"), Path("output/plot.pdf")]
    """
    from pathlib import Path
    
    if not MATPLOTLIB_AVAILABLE or fig is None:
        return []
    
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    saved_paths = []
    
    for fmt in formats:
        # Determine DPI based on format type
        if fmt in ('png', 'jpg', 'jpeg', 'tiff'):
            dpi = dpi_raster
        else:
            dpi = dpi_vector
        
        # Create path with correct extension
        save_path = output_path.with_suffix(f'.{fmt}')
        
        try:
            fig.savefig(
                save_path,
                dpi=dpi,
                bbox_inches=bbox_inches,
                facecolor=facecolor,
            )
            saved_paths.append(save_path)
            logger.debug("Saved figure to %s (dpi=%d)", save_path, dpi)
        except Exception as e:
            logger.error("Failed to save figure to %s: %s", save_path, e)
    
    return saved_paths


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    'MATPLOTLIB_AVAILABLE',
    'SHAP_AVAILABLE',
    'plt',
    'Figure',
    'Axes',
    'shap',
    'require_matplotlib',
    'require_shap',
    'save_figure_multiformat',
]
