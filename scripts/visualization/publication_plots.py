"""Publication-quality plot configuration for thesis figures.

Fix #20: Publication-Ready Plots (Days 11-14)

This module provides standardized plot configuration ensuring all thesis
figures meet academic publication standards:
- High DPI (300+ for raster, 600 for line art)
- Colorblind-safe palettes
- Proper font sizes (10-12pt for labels)
- Consistent styling across all figures
- Export in multiple formats (PDF, PNG, SVG)

Usage:
    from scripts.visualization.publication_plots import (
        setup_publication_style,
        ThesisFigure,
        COLORBLIND_PALETTE,
    )
    
    # Apply publication settings globally
    setup_publication_style()
    
    # Create a thesis figure
    with ThesisFigure("handover_comparison", figsize=(8, 6)) as fig:
        ax = fig.add_subplot(111)
        ax.plot(x, y, color=COLORBLIND_PALETTE['ml'])
        ax.set_xlabel("Time (s)")
        ax.set_ylabel("Handover Count")
    # Figure automatically saved in thesis_results/figures/

References:
    - IEEE Visualization Conference Guidelines
    - Nature Publishing Group Figure Guidelines
    - ACM SIGCHI Conference Proceedings Format
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# Import from shared utilities (Refactor #1: Consolidated matplotlib imports)
from scripts.visualization._utils import (
    MATPLOTLIB_AVAILABLE,
    plt,
    Figure,
    Axes,
)


# =============================================================================
# COLORBLIND-SAFE PALETTES
# =============================================================================
# Based on Bang Wong's Nature Methods color palette (2011)
# and IBM Design Library colorblind-safe palette

# Primary palette for comparing ML vs A3
COLORBLIND_PALETTE = {
    'ml': '#0072B2',       # Blue - ML approach
    'a3': '#E69F00',       # Orange - A3 baseline
    'optimal': '#009E73',  # Green - Optimal/target
    'error': '#D55E00',    # Red-orange - Errors/failures
    'neutral': '#56B4E9',  # Light blue - Secondary data
    'highlight': '#CC79A7', # Pink - Highlights
    'black': '#000000',    # Black - Text/annotations
    'gray': '#999999',     # Gray - Grid/secondary elements
}

# Extended palette for multi-scenario comparison
SCENARIO_PALETTE = {
    'highway': '#0072B2',
    'urban_canyon': '#E69F00', 
    'smart_city': '#009E73',
    'stationary': '#CC79A7',
    'stressed': '#D55E00',
}

# Marker styles for distinguishing lines
MARKER_STYLES = {
    'ml': ('o', 6),         # Circle, size 6
    'a3': ('s', 5),         # Square, size 5
    'optimal': ('^', 6),    # Triangle, size 6
    'error': ('x', 7),      # X, size 7
}

# Line styles for print-safe differentiation
LINE_STYLES = {
    'ml': '-',       # Solid
    'a3': '--',      # Dashed
    'optimal': '-.',  # Dash-dot
    'secondary': ':',  # Dotted
}


# =============================================================================
# PUBLICATION STANDARDS
# =============================================================================

class FigureFormat(Enum):
    """Output formats for thesis figures."""
    PDF = "pdf"   # Vector, best for LaTeX
    PNG = "png"   # Raster, for web/preview
    SVG = "svg"   # Vector, editable
    EPS = "eps"   # Vector, legacy LaTeX


@dataclass
class PublicationConfig:
    """Configuration for publication-quality figures.
    
    Based on IEEE, ACM, and Nature publication guidelines.
    """
    # DPI settings
    dpi_raster: int = 300      # For PNG exports
    dpi_display: int = 100     # For screen display
    dpi_line_art: int = 600    # For pure line drawings
    
    # Font settings (in points)
    font_size_title: int = 14
    font_size_label: int = 12
    font_size_tick: int = 10
    font_size_legend: int = 10
    font_size_annotation: int = 9
    font_family: str = 'serif'  # Or 'sans-serif' for some venues
    
    # Figure sizes (inches) - common academic formats
    # Single column: ~3.5 inches wide
    # Double column: ~7.0 inches wide
    # Full page: ~10 inches wide
    figsize_single_column: Tuple[float, float] = (3.5, 2.5)
    figsize_double_column: Tuple[float, float] = (7.0, 5.0)
    figsize_full_page: Tuple[float, float] = (10.0, 7.0)
    figsize_square: Tuple[float, float] = (5.0, 5.0)
    
    # Line widths
    line_width_data: float = 1.5
    line_width_axis: float = 0.8
    line_width_grid: float = 0.5
    
    # Marker settings
    marker_size: float = 6.0
    marker_edge_width: float = 0.5
    
    # Grid and spine settings
    show_grid: bool = True
    grid_alpha: float = 0.3
    spine_visibility: Dict[str, bool] = None
    
    # Export settings
    bbox_inches: str = 'tight'
    pad_inches: float = 0.1
    transparent: bool = False  # True for overlays
    
    def __post_init__(self):
        if self.spine_visibility is None:
            self.spine_visibility = {
                'top': False,
                'right': False,
                'bottom': True,
                'left': True,
            }


# Default configuration instance
DEFAULT_CONFIG = PublicationConfig()


def setup_publication_style(config: PublicationConfig = None) -> None:
    """Apply publication-quality settings to matplotlib globally.
    
    Call this at the start of any plotting script to ensure
    consistent styling across all thesis figures.
    
    Args:
        config: Configuration object (uses defaults if None)
    """
    if not MATPLOTLIB_AVAILABLE:
        logger.warning("Matplotlib not available - skipping style setup")
        return
    
    config = config or DEFAULT_CONFIG
    
    # Update matplotlib rcParams
    plt.rcParams.update({
        # Font settings
        'font.family': config.font_family,
        'font.size': config.font_size_label,
        'axes.titlesize': config.font_size_title,
        'axes.labelsize': config.font_size_label,
        'xtick.labelsize': config.font_size_tick,
        'ytick.labelsize': config.font_size_tick,
        'legend.fontsize': config.font_size_legend,
        
        # Line settings
        'lines.linewidth': config.line_width_data,
        'axes.linewidth': config.line_width_axis,
        'grid.linewidth': config.line_width_grid,
        'lines.markersize': config.marker_size,
        
        # Grid settings
        'axes.grid': config.show_grid,
        'grid.alpha': config.grid_alpha,
        
        # Figure settings
        'figure.dpi': config.dpi_display,
        'savefig.dpi': config.dpi_raster,
        'savefig.bbox': config.bbox_inches,
        'savefig.pad_inches': config.pad_inches,
        
        # Spine settings
        'axes.spines.top': config.spine_visibility['top'],
        'axes.spines.right': config.spine_visibility['right'],
        
        # Legend settings
        'legend.frameon': True,
        'legend.framealpha': 0.9,
        'legend.edgecolor': 'gray',
        
        # Other
        'axes.axisbelow': True,  # Grid behind data
        'figure.autolayout': True,  # Tight layout by default
    })
    
    logger.info("Publication style applied to matplotlib")


class ThesisFigure:
    """Context manager for creating publication-quality thesis figures.
    
    Handles figure creation, styling, and automatic export to multiple formats.
    
    Usage:
        with ThesisFigure("my_plot", figsize=(8, 6)) as fig:
            ax = fig.add_subplot(111)
            ax.plot(x, y)
            ax.set_xlabel("X Label")
        # Figure automatically saved to thesis_results/figures/my_plot.pdf
    """
    
    def __init__(
        self,
        name: str,
        figsize: Tuple[float, float] = None,
        output_dir: str | Path = None,
        formats: List[FigureFormat] = None,
        config: PublicationConfig = None,
    ):
        """Initialize thesis figure.
        
        Args:
            name: Figure name (used for filename)
            figsize: Figure size in inches (width, height)
            output_dir: Directory for saving figures
            formats: List of export formats
            config: Publication configuration
        """
        self.name = name
        self.config = config or DEFAULT_CONFIG
        self.figsize = figsize or self.config.figsize_double_column
        self.formats = formats or [FigureFormat.PDF, FigureFormat.PNG]
        
        # Determine output directory
        if output_dir is None:
            # Default to thesis_results/figures/ relative to workspace root
            workspace_root = Path(__file__).parent.parent.parent
            self.output_dir = workspace_root / "thesis_results" / "figures"
        else:
            self.output_dir = Path(output_dir)
        
        self.figure: Optional[Figure] = None
        self._saved_paths: List[Path] = []
    
    def __enter__(self) -> Figure:
        """Create and return the figure."""
        if not MATPLOTLIB_AVAILABLE:
            raise RuntimeError("Matplotlib not available")
        
        # Ensure publication style is applied
        setup_publication_style(self.config)
        
        # Create figure
        self.figure = plt.figure(figsize=self.figsize)
        
        return self.figure
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Save figure and clean up."""
        if exc_type is not None:
            # Exception occurred, don't save
            plt.close(self.figure)
            return False
        
        # Create output directory if needed
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Save in each format
        for fmt in self.formats:
            output_path = self.output_dir / f"{self.name}.{fmt.value}"
            
            # Use higher DPI for line art (SVG/PDF don't need this)
            dpi = self.config.dpi_raster
            if fmt in (FigureFormat.PDF, FigureFormat.SVG):
                dpi = self.config.dpi_line_art
            
            try:
                self.figure.savefig(
                    output_path,
                    format=fmt.value,
                    dpi=dpi,
                    bbox_inches=self.config.bbox_inches,
                    pad_inches=self.config.pad_inches,
                    transparent=self.config.transparent,
                    facecolor='white',
                    edgecolor='none',
                )
                self._saved_paths.append(output_path)
                logger.info("Saved figure: %s", output_path)
            except Exception as e:
                logger.error("Failed to save %s: %s", output_path, e)
        
        # Clean up
        plt.close(self.figure)
        
        return False  # Don't suppress exceptions
    
    @property
    def saved_paths(self) -> List[Path]:
        """Return list of paths where figure was saved."""
        return self._saved_paths


# =============================================================================
# SPECIALIZED PLOT FUNCTIONS
# =============================================================================

def plot_algorithm_comparison(
    ax: Axes,
    x_data: np.ndarray,
    ml_data: np.ndarray,
    a3_data: np.ndarray,
    xlabel: str,
    ylabel: str,
    title: str = None,
    show_legend: bool = True,
    ml_label: str = "ML Approach",
    a3_label: str = "A3 Baseline",
    fill_between: bool = False,
    ml_ci: Tuple[np.ndarray, np.ndarray] = None,
    a3_ci: Tuple[np.ndarray, np.ndarray] = None,
) -> None:
    """Create a standardized ML vs A3 comparison plot.
    
    Args:
        ax: Matplotlib axes to plot on
        x_data: X-axis data
        ml_data: ML approach data
        a3_data: A3 baseline data
        xlabel: X-axis label
        ylabel: Y-axis label
        title: Optional plot title
        show_legend: Whether to show legend
        ml_label: Label for ML line
        a3_label: Label for A3 line
        fill_between: Whether to fill confidence intervals
        ml_ci: (lower, upper) confidence intervals for ML
        a3_ci: (lower, upper) confidence intervals for A3
    """
    # Plot ML data
    ax.plot(
        x_data, ml_data,
        color=COLORBLIND_PALETTE['ml'],
        linestyle=LINE_STYLES['ml'],
        marker=MARKER_STYLES['ml'][0],
        markersize=MARKER_STYLES['ml'][1],
        label=ml_label,
        linewidth=DEFAULT_CONFIG.line_width_data,
    )
    
    # Plot A3 data
    ax.plot(
        x_data, a3_data,
        color=COLORBLIND_PALETTE['a3'],
        linestyle=LINE_STYLES['a3'],
        marker=MARKER_STYLES['a3'][0],
        markersize=MARKER_STYLES['a3'][1],
        label=a3_label,
        linewidth=DEFAULT_CONFIG.line_width_data,
    )
    
    # Add confidence intervals if provided
    if fill_between and ml_ci is not None:
        ax.fill_between(
            x_data, ml_ci[0], ml_ci[1],
            color=COLORBLIND_PALETTE['ml'],
            alpha=0.2,
        )
    
    if fill_between and a3_ci is not None:
        ax.fill_between(
            x_data, a3_ci[0], a3_ci[1],
            color=COLORBLIND_PALETTE['a3'],
            alpha=0.2,
        )
    
    # Labels
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    
    if title:
        ax.set_title(title)
    
    if show_legend:
        ax.legend(loc='best', framealpha=0.9)


def plot_box_comparison(
    ax: Axes,
    data_dict: Dict[str, np.ndarray],
    ylabel: str,
    title: str = None,
    show_points: bool = True,
    horizontal: bool = False,
) -> None:
    """Create a box plot comparing multiple conditions.
    
    Args:
        ax: Matplotlib axes
        data_dict: Dictionary mapping labels to data arrays
        ylabel: Y-axis label
        title: Optional title
        show_points: Whether to overlay individual data points
        horizontal: Whether boxes should be horizontal
    """
    labels = list(data_dict.keys())
    data = [data_dict[label] for label in labels]
    
    # Color mapping
    colors = [
        COLORBLIND_PALETTE.get(label.lower(), COLORBLIND_PALETTE['neutral'])
        for label in labels
    ]
    
    # Create box plot
    bp = ax.boxplot(
        data,
        labels=labels,
        patch_artist=True,
        vert=not horizontal,
    )
    
    # Color the boxes
    for patch, color in zip(bp['boxes'], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.7)
    
    # Style whiskers and caps
    for whisker in bp['whiskers']:
        whisker.set_color(COLORBLIND_PALETTE['black'])
        whisker.set_linewidth(1.0)
    
    for cap in bp['caps']:
        cap.set_color(COLORBLIND_PALETTE['black'])
        cap.set_linewidth(1.0)
    
    for median in bp['medians']:
        median.set_color(COLORBLIND_PALETTE['black'])
        median.set_linewidth(2.0)
    
    # Overlay individual points (seeded RNG for reproducibility)
    if show_points:
        plot_rng = np.random.default_rng(seed=42)
        for i, (label, d) in enumerate(data_dict.items()):
            x = plot_rng.normal(i + 1, 0.04, size=len(d))
            ax.scatter(
                x if not horizontal else d,
                d if not horizontal else x,
                alpha=0.5,
                color=COLORBLIND_PALETTE['black'],
                s=15,
                zorder=3,
            )
    
    ax.set_ylabel(ylabel)
    if title:
        ax.set_title(title)


def create_heatmap(
    ax: Axes,
    data: np.ndarray,
    row_labels: List[str],
    col_labels: List[str],
    xlabel: str = None,
    ylabel: str = None,
    title: str = None,
    cmap: str = 'RdYlGn',
    annotate: bool = True,
    fmt: str = '.2f',
    vmin: float = None,
    vmax: float = None,
) -> None:
    """Create a publication-quality heatmap.
    
    Args:
        ax: Matplotlib axes
        data: 2D array of values
        row_labels: Labels for rows
        col_labels: Labels for columns
        xlabel: X-axis label
        ylabel: Y-axis label
        title: Plot title
        cmap: Colormap name (RdYlGn is colorblind-safe)
        annotate: Whether to add value annotations
        fmt: Format string for annotations
        vmin: Minimum value for colorscale
        vmax: Maximum value for colorscale
    """
    im = ax.imshow(
        data,
        cmap=cmap,
        aspect='auto',
        vmin=vmin,
        vmax=vmax,
    )
    
    # Set ticks
    ax.set_xticks(np.arange(len(col_labels)))
    ax.set_yticks(np.arange(len(row_labels)))
    ax.set_xticklabels(col_labels)
    ax.set_yticklabels(row_labels)
    
    # Rotate x labels for readability
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right", rotation_mode="anchor")
    
    # Add annotations
    if annotate:
        # Determine threshold for text color based on colormap midpoint
        data_min = vmin if vmin is not None else data.min()
        data_max = vmax if vmax is not None else data.max()
        threshold = (data_min + data_max) / 2
        
        for i in range(len(row_labels)):
            for j in range(len(col_labels)):
                value = data[i, j]
                # Choose text color based on whether value is in darker region
                # For diverging colormaps, extremes are dark, middle is light
                text_color = 'white' if abs(value - threshold) > 0.25 * (data_max - data_min) else 'black'
                ax.text(
                    j, i, format(value, fmt),
                    ha="center", va="center",
                    color=text_color,
                    fontsize=DEFAULT_CONFIG.font_size_annotation,
                )
    
    # Labels
    if xlabel:
        ax.set_xlabel(xlabel)
    if ylabel:
        ax.set_ylabel(ylabel)
    if title:
        ax.set_title(title)
    
    # Colorbar
    cbar = ax.figure.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    
    return im


def add_significance_bars(
    ax: Axes,
    pairs: List[Tuple[int, int]],
    p_values: List[float],
    y_max: float,
    bar_height: float = 0.05,
) -> None:
    """Add significance bars between conditions.
    
    Args:
        ax: Matplotlib axes
        pairs: List of (index1, index2) pairs to compare
        p_values: P-values for each pair
        y_max: Maximum y value in plot
        bar_height: Height of significance bars as fraction of y range
    """
    y_range = ax.get_ylim()[1] - ax.get_ylim()[0]
    
    for i, ((x1, x2), p) in enumerate(zip(pairs, p_values)):
        # Determine significance symbol
        if p < 0.001:
            sig = '***'
        elif p < 0.01:
            sig = '**'
        elif p < 0.05:
            sig = '*'
        else:
            sig = 'ns'
        
        # Calculate bar position
        bar_y = y_max + (i + 1) * bar_height * y_range
        
        # Draw bar
        ax.plot(
            [x1, x1, x2, x2],
            [bar_y - 0.01 * y_range, bar_y, bar_y, bar_y - 0.01 * y_range],
            color=COLORBLIND_PALETTE['black'],
            linewidth=1.0,
        )
        
        # Add significance text
        ax.text(
            (x1 + x2) / 2, bar_y + 0.01 * y_range,
            sig,
            ha='center', va='bottom',
            fontsize=DEFAULT_CONFIG.font_size_annotation,
        )


# =============================================================================
# VALIDATION UTILITIES
# =============================================================================

def validate_figure_quality(figure_path: str | Path) -> Dict[str, Any]:
    """Validate a figure meets publication standards.
    
    Args:
        figure_path: Path to figure file
        
    Returns:
        Dictionary with validation results
    """
    try:
        from PIL import Image
        PIL_AVAILABLE = True
    except ImportError:
        PIL_AVAILABLE = False
        logger.warning("PIL not available - PNG validation disabled")
    
    path = Path(figure_path)
    results = {
        'valid': True,
        'warnings': [],
        'errors': [],
    }
    
    if not path.exists():
        results['valid'] = False
        results['errors'].append(f"File not found: {path}")
        return results
    
    # Check format-specific requirements
    if path.suffix.lower() == '.png' and PIL_AVAILABLE:
        try:
            with Image.open(path) as img:
                # Check DPI
                dpi = img.info.get('dpi', (72, 72))
                if isinstance(dpi, tuple):
                    dpi = dpi[0]
                
                if dpi < 300:
                    results['warnings'].append(
                        f"DPI too low: {dpi} (minimum 300 for publication)"
                    )
                
                # Check dimensions
                width, height = img.size
                if width < 1000 or height < 700:
                    results['warnings'].append(
                        f"Resolution may be too low: {width}x{height}"
                    )
                
                # Check color mode
                if img.mode not in ('RGB', 'RGBA'):
                    results['warnings'].append(
                        f"Unusual color mode: {img.mode}"
                    )
                
        except Exception as e:
            results['errors'].append(f"Failed to analyze PNG: {e}")
    
    elif path.suffix.lower() == '.pdf':
        # PDF validation would require additional libraries
        results['warnings'].append("PDF validation not implemented - manual check required")
    
    # File size check
    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > 10:
        results['warnings'].append(f"File size large: {size_mb:.1f} MB")
    
    results['valid'] = len(results['errors']) == 0
    
    return results


# =============================================================================
# CONVENIENCE EXPORTS
# =============================================================================

__all__ = [
    # Configuration
    'PublicationConfig',
    'DEFAULT_CONFIG',
    'FigureFormat',
    'setup_publication_style',
    
    # Palettes
    'COLORBLIND_PALETTE',
    'SCENARIO_PALETTE',
    'MARKER_STYLES',
    'LINE_STYLES',
    
    # Figure management
    'ThesisFigure',
    
    # Plot functions
    'plot_algorithm_comparison',
    'plot_box_comparison',
    'create_heatmap',
    'add_significance_bars',
    
    # Validation
    'validate_figure_quality',
]
