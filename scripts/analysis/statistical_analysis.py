"""Statistical analysis utilities for thesis experiments.

This module implements Fixes #16, #17, #18, #19 from the thesis implementation plan:

Fix #16: Paired vs Independent Statistical Test
- Uses paired t-test or Wilcoxon signed-rank for matched experimental design
- Each seed defines a scenario instance run with both A3 and ML

Fix #17: Cohen's d for Paired Data
- Uses Cohen's d_z (difference-based) for paired comparisons
- Reports both d_z and percentage improvement

Fix #18: Multiple Comparisons Correction
- Bonferroni correction for family-wise error rate control
- Reports both raw and corrected p-values

Fix #19: Bootstrap Confidence Intervals
- Maintains pairing during resampling
- 10,000 iterations for stable percentile estimates

Usage:
    from scripts.analysis.statistical_analysis import (
        run_paired_comparison,
        calculate_effect_size,
        bootstrap_ci,
        apply_bonferroni_correction
    )
    
    # Compare A3 vs ML results
    results = run_paired_comparison(
        a3_values=[15, 18, 12, 20, 14],
        ml_values=[4, 3, 5, 2, 6],
        metric_name="handover_count"
    )
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy import stats

logger = logging.getLogger(__name__)


@dataclass
class PairedComparisonResult:
    """Result of a paired statistical comparison.
    
    Attributes:
        metric_name: Name of the metric being compared
        n_pairs: Number of paired observations
        a3_mean: Mean of A3 values
        a3_std: Standard deviation of A3 values
        ml_mean: Mean of ML values
        ml_std: Standard deviation of ML values
        mean_difference: Mean of (A3 - ML) differences
        std_difference: Std of differences
        improvement_percent: Percentage improvement ((A3 - ML) / A3 * 100)
        test_statistic: Test statistic value
        p_value_raw: Raw (uncorrected) p-value
        p_value_corrected: Bonferroni-corrected p-value (if applicable)
        is_significant: Whether result is significant at alpha=0.05 (corrected)
        test_type: Type of test used ("paired_t" or "wilcoxon")
        cohens_d_z: Effect size (Cohen's d for paired data)
        effect_size_interpretation: "small", "medium", "large", or "very large"
        ci_lower: Lower bound of 95% CI for improvement
        ci_upper: Upper bound of 95% CI for improvement
        normality_p: P-value from Shapiro-Wilk test on differences
    """
    metric_name: str
    n_pairs: int
    a3_mean: float
    a3_std: float
    ml_mean: float
    ml_std: float
    mean_difference: float
    std_difference: float
    improvement_percent: float
    test_statistic: float
    p_value_raw: float
    p_value_corrected: Optional[float] = None
    is_significant: bool = False
    test_type: str = "paired_t"
    cohens_d_z: float = 0.0
    effect_size_interpretation: str = "negligible"
    ci_lower: Optional[float] = None
    ci_upper: Optional[float] = None
    normality_p: Optional[float] = None


def check_normality(differences: np.ndarray, alpha: float = 0.05) -> Tuple[bool, float]:
    """Check if differences are normally distributed using Shapiro-Wilk test.
    
    Args:
        differences: Array of paired differences
        alpha: Significance level for normality test
        
    Returns:
        Tuple of (is_normal, p_value)
    """
    if len(differences) < 3:
        logger.warning("Too few samples for normality test, assuming normal")
        return True, 1.0
    
    if len(differences) > 5000:
        # Shapiro-Wilk limited to 5000 samples
        differences = np.random.choice(differences, 5000, replace=False)
    
    stat, p_value = stats.shapiro(differences)
    is_normal = p_value > alpha
    
    logger.debug(
        "Normality test: W=%.4f, p=%.4f, is_normal=%s",
        stat, p_value, is_normal
    )
    
    return is_normal, p_value


def calculate_cohens_d_z(differences: np.ndarray) -> Tuple[float, str]:
    """Calculate Cohen's d_z for paired data.
    
    Fix #17: Uses the difference in the denominator for paired comparisons.
    
    Cohen's d_z = mean(differences) / std(differences)
    
    Args:
        differences: Array of paired differences (a3 - ml)
        
    Returns:
        Tuple of (d_z value, interpretation string)
    """
    if len(differences) == 0:
        return 0.0, "negligible"
    
    # Fix: Handle single-element case where ddof=1 would cause division by zero
    if len(differences) == 1:
        # With single pair, we cannot estimate variance
        # Return the difference normalized by a reasonable assumption
        return float('inf') if differences[0] != 0 else 0.0, "undefined (n=1)"
    
    mean_diff = np.mean(differences)
    std_diff = np.std(differences, ddof=1)  # Use sample std
    
    if std_diff == 0:
        # All differences are identical
        return float('inf') if mean_diff != 0 else 0.0, "very large" if mean_diff != 0 else "negligible"
    
    d_z = mean_diff / std_diff
    
    # Interpretation based on Cohen's guidelines
    abs_d = abs(d_z)
    if abs_d < 0.2:
        interpretation = "negligible"
    elif abs_d < 0.5:
        interpretation = "small"
    elif abs_d < 0.8:
        interpretation = "medium"
    elif abs_d < 1.2:
        interpretation = "large"
    else:
        interpretation = "very large"
    
    logger.debug("Cohen's d_z = %.3f (%s effect)", d_z, interpretation)
    
    return d_z, interpretation


def bootstrap_ci(
    a3_values: np.ndarray,
    ml_values: np.ndarray,
    n_iterations: int = 10000,
    ci_level: float = 0.95,
    metric: str = "improvement_percent",
    seed: Optional[int] = None,
) -> Tuple[float, float]:
    """Calculate bootstrap confidence interval for paired data.
    
    Fix #19: Maintains pairing during resampling.
    
    Args:
        a3_values: Array of A3 values
        ml_values: Array of ML values (paired with A3)
        n_iterations: Number of bootstrap iterations (default 10,000)
        ci_level: Confidence level (default 0.95 for 95% CI)
        metric: What to calculate CI for ("improvement_percent" or "mean_difference")
        seed: Random seed for reproducibility
        
    Returns:
        Tuple of (lower_bound, upper_bound)
    """
    rng = np.random.RandomState(seed)
    n_pairs = len(a3_values)
    
    if n_pairs == 0:
        return 0.0, 0.0
    
    bootstrap_stats = []
    
    for _ in range(n_iterations):
        # Resample PAIRS with replacement (Fix #19: maintain pairing)
        indices = rng.choice(n_pairs, size=n_pairs, replace=True)
        boot_a3 = a3_values[indices]
        boot_ml = ml_values[indices]
        
        if metric == "improvement_percent":
            # Calculate improvement percentage for this bootstrap sample
            a3_mean = np.mean(boot_a3)
            ml_mean = np.mean(boot_ml)
            if a3_mean != 0:
                improvement = (a3_mean - ml_mean) / a3_mean * 100
            else:
                improvement = 0.0
            bootstrap_stats.append(improvement)
        else:
            # Mean difference
            bootstrap_stats.append(np.mean(boot_a3 - boot_ml))
    
    bootstrap_stats = np.array(bootstrap_stats)
    
    # Calculate percentiles
    alpha = 1 - ci_level
    lower = np.percentile(bootstrap_stats, alpha / 2 * 100)
    upper = np.percentile(bootstrap_stats, (1 - alpha / 2) * 100)
    
    logger.debug(
        "Bootstrap CI (%.0f%%): [%.2f, %.2f] based on %d iterations",
        ci_level * 100, lower, upper, n_iterations
    )
    
    return lower, upper


def run_paired_comparison(
    a3_values: List[float] | np.ndarray,
    ml_values: List[float] | np.ndarray,
    metric_name: str,
    alpha: float = 0.05,
    n_comparisons: int = 1,
    bootstrap_iterations: int = 10000,
    seed: Optional[int] = None,
) -> PairedComparisonResult:
    """Run a complete paired statistical comparison between A3 and ML.
    
    Implements Fixes #16, #17, #18, #19:
    - Chooses correct test (paired t or Wilcoxon) based on normality
    - Calculates Cohen's d_z for effect size
    - Applies Bonferroni correction if multiple comparisons
    - Computes bootstrap confidence interval
    
    Args:
        a3_values: Array of A3 metric values
        ml_values: Array of ML metric values (paired with A3)
        metric_name: Name of the metric for reporting
        alpha: Significance level (default 0.05)
        n_comparisons: Number of total comparisons for Bonferroni (default 1)
        bootstrap_iterations: Number of bootstrap iterations for CI
        seed: Random seed for bootstrap
        
    Returns:
        PairedComparisonResult with all statistics
    """
    a3_arr = np.array(a3_values, dtype=float)
    ml_arr = np.array(ml_values, dtype=float)
    
    if len(a3_arr) != len(ml_arr):
        raise ValueError(
            f"Arrays must have same length: A3={len(a3_arr)}, ML={len(ml_arr)}"
        )
    
    n_pairs = len(a3_arr)
    if n_pairs < 2:
        raise ValueError(f"Need at least 2 pairs, got {n_pairs}")
    
    # Calculate basic statistics
    a3_mean = np.mean(a3_arr)
    a3_std = np.std(a3_arr, ddof=1)
    ml_mean = np.mean(ml_arr)
    ml_std = np.std(ml_arr, ddof=1)
    
    differences = a3_arr - ml_arr
    mean_diff = np.mean(differences)
    std_diff = np.std(differences, ddof=1)
    
    # Improvement percentage (positive = ML is better)
    if a3_mean != 0:
        improvement_pct = (a3_mean - ml_mean) / a3_mean * 100
    else:
        improvement_pct = 0.0
    
    # Fix #16: Check normality of differences to select test
    is_normal, normality_p = check_normality(differences)
    
    # Run appropriate statistical test
    if is_normal:
        # Paired t-test
        stat, p_value = stats.ttest_rel(a3_arr, ml_arr)
        test_type = "paired_t"
        logger.info(
            "%s: Using paired t-test (differences normally distributed, p=%.4f)",
            metric_name, normality_p
        )
    else:
        # Wilcoxon signed-rank test
        try:
            stat, p_value = stats.wilcoxon(a3_arr, ml_arr, alternative='two-sided')
            test_type = "wilcoxon"
            logger.info(
                "%s: Using Wilcoxon signed-rank test (differences not normal, p=%.4f)",
                metric_name, normality_p
            )
        except ValueError as e:
            # Wilcoxon fails if all differences are zero
            logger.warning("%s: Wilcoxon failed (%s), falling back to paired t", metric_name, e)
            stat, p_value = stats.ttest_rel(a3_arr, ml_arr)
            test_type = "paired_t"
    
    # Fix #18: Bonferroni correction
    p_corrected = min(p_value * n_comparisons, 1.0)
    alpha_corrected = alpha / n_comparisons
    is_significant = p_corrected < alpha
    
    # Fix #17: Cohen's d_z
    d_z, effect_interpretation = calculate_cohens_d_z(differences)
    
    # Fix #19: Bootstrap CI
    ci_lower, ci_upper = bootstrap_ci(
        a3_arr, ml_arr,
        n_iterations=bootstrap_iterations,
        metric="improvement_percent",
        seed=seed
    )
    
    result = PairedComparisonResult(
        metric_name=metric_name,
        n_pairs=n_pairs,
        a3_mean=a3_mean,
        a3_std=a3_std,
        ml_mean=ml_mean,
        ml_std=ml_std,
        mean_difference=mean_diff,
        std_difference=std_diff,
        improvement_percent=improvement_pct,
        test_statistic=stat,
        p_value_raw=p_value,
        p_value_corrected=p_corrected,
        is_significant=is_significant,
        test_type=test_type,
        cohens_d_z=d_z,
        effect_size_interpretation=effect_interpretation,
        ci_lower=ci_lower,
        ci_upper=ci_upper,
        normality_p=normality_p,
    )
    
    logger.info(
        "%s: A3=%.2f±%.2f, ML=%.2f±%.2f, improvement=%.1f%% [%.1f, %.1f], "
        "p=%.4f (corrected=%.4f), d_z=%.2f (%s), significant=%s",
        metric_name, a3_mean, a3_std, ml_mean, ml_std,
        improvement_pct, ci_lower, ci_upper,
        p_value, p_corrected, d_z, effect_interpretation, is_significant
    )
    
    return result


def apply_bonferroni_correction_scalar(
    p_value: float,
    n_comparisons: int,
) -> float:
    """Apply Bonferroni correction to a single p-value.
    
    Simple scalar version for direct p-value correction.
    
    Args:
        p_value: Raw (uncorrected) p-value
        n_comparisons: Number of comparisons being made
        
    Returns:
        Corrected p-value (capped at 1.0)
    """
    return min(p_value * n_comparisons, 1.0)


def apply_bonferroni_correction(
    results: List[PairedComparisonResult],
    alpha: float = 0.05,
) -> List[PairedComparisonResult]:
    """Apply Bonferroni correction to a list of comparison results.
    
    Fix #18: Family-wise error rate control.
    
    Args:
        results: List of PairedComparisonResult objects
        alpha: Original significance level
        
    Returns:
        Updated list with corrected p-values and significance
    """
    n_comparisons = len(results)
    alpha_corrected = alpha / n_comparisons
    
    for result in results:
        result.p_value_corrected = min(result.p_value_raw * n_comparisons, 1.0)
        result.is_significant = result.p_value_corrected < alpha
    
    logger.info(
        "Applied Bonferroni correction for %d comparisons (α_corrected=%.4f)",
        n_comparisons, alpha_corrected
    )
    
    return results


def run_multi_metric_comparison(
    a3_results: Dict[str, List[float]],
    ml_results: Dict[str, List[float]],
    alpha: float = 0.05,
    bootstrap_iterations: int = 10000,
    seed: Optional[int] = None,
) -> Dict[str, PairedComparisonResult]:
    """Run paired comparison for multiple metrics with Bonferroni correction.
    
    Args:
        a3_results: Dict mapping metric names to A3 values
        ml_results: Dict mapping metric names to ML values
        alpha: Overall significance level
        bootstrap_iterations: Bootstrap iterations per metric
        seed: Random seed for reproducibility
        
    Returns:
        Dict mapping metric names to PairedComparisonResult
    """
    common_metrics = set(a3_results.keys()) & set(ml_results.keys())
    n_comparisons = len(common_metrics)
    
    if n_comparisons == 0:
        raise ValueError("No common metrics found between A3 and ML results")
    
    logger.info(
        "Running %d paired comparisons with Bonferroni correction",
        n_comparisons
    )
    
    results = {}
    for metric_name in sorted(common_metrics):
        results[metric_name] = run_paired_comparison(
            a3_values=a3_results[metric_name],
            ml_values=ml_results[metric_name],
            metric_name=metric_name,
            alpha=alpha,
            n_comparisons=n_comparisons,
            bootstrap_iterations=bootstrap_iterations,
            seed=seed,
        )
    
    return results


def format_results_table(
    results: Dict[str, PairedComparisonResult],
    include_raw_p: bool = True,
) -> str:
    """Format comparison results as a markdown table.
    
    Args:
        results: Dict of comparison results
        include_raw_p: Whether to include raw (uncorrected) p-values
        
    Returns:
        Markdown-formatted table string
    """
    lines = []
    
    # Header
    if include_raw_p:
        lines.append("| Metric | A3 Mean (SD) | ML Mean (SD) | Improvement | p-value (raw) | p-value (corr) | Sig? | Cohen's d |")
        lines.append("|--------|--------------|--------------|-------------|---------------|----------------|------|-----------|")
    else:
        lines.append("| Metric | A3 Mean (SD) | ML Mean (SD) | Improvement | p-value | Sig? | Cohen's d |")
        lines.append("|--------|--------------|--------------|-------------|---------|------|-----------|")
    
    # Rows
    for name, r in sorted(results.items()):
        sig_marker = "***" if r.p_value_corrected < 0.001 else (
            "**" if r.p_value_corrected < 0.01 else (
                "*" if r.is_significant else ""
            )
        )
        
        ci_str = f"[{r.ci_lower:.1f}%, {r.ci_upper:.1f}%]" if r.ci_lower is not None else ""
        
        if include_raw_p:
            lines.append(
                f"| {name} | {r.a3_mean:.2f} ({r.a3_std:.2f}) | {r.ml_mean:.2f} ({r.ml_std:.2f}) | "
                f"{r.improvement_percent:.1f}% {ci_str} | {r.p_value_raw:.4f} | {r.p_value_corrected:.4f} | "
                f"{sig_marker} | {r.cohens_d_z:.2f} ({r.effect_size_interpretation}) |"
            )
        else:
            lines.append(
                f"| {name} | {r.a3_mean:.2f} ({r.a3_std:.2f}) | {r.ml_mean:.2f} ({r.ml_std:.2f}) | "
                f"{r.improvement_percent:.1f}% {ci_str} | {r.p_value_corrected:.4f} | "
                f"{sig_marker} | {r.cohens_d_z:.2f} ({r.effect_size_interpretation}) |"
            )
    
    return "\n".join(lines)


def generate_latex_table(
    results: Dict[str, PairedComparisonResult],
    caption: str = "Statistical comparison of A3 vs ML handover algorithms",
    label: str = "tab:comparison",
) -> str:
    """Generate LaTeX table for thesis.
    
    Args:
        results: Dict of comparison results
        caption: Table caption
        label: LaTeX label
        
    Returns:
        LaTeX table string
    """
    lines = [
        r"\begin{table}[htbp]",
        r"\centering",
        f"\\caption{{{caption}}}",
        f"\\label{{{label}}}",
        r"\begin{tabular}{lcccccc}",
        r"\toprule",
        r"Metric & A3 Mean & ML Mean & Improvement & $p$-value & Cohen's $d_z$ & Sig. \\",
        r"\midrule",
    ]
    
    for name, r in sorted(results.items()):
        sig = r"$^{***}$" if r.p_value_corrected < 0.001 else (
            r"$^{**}$" if r.p_value_corrected < 0.01 else (
                r"$^{*}$" if r.is_significant else ""
            )
        )
        
        lines.append(
            f"{name} & {r.a3_mean:.2f} & {r.ml_mean:.2f} & "
            f"{r.improvement_percent:.1f}\\% & {r.p_value_corrected:.4f} & "
            f"{r.cohens_d_z:.2f} & {sig} \\\\"
        )
    
    lines.extend([
        r"\bottomrule",
        r"\end{tabular}",
        r"\begin{tablenotes}",
        r"\small",
        r"\item Note: p-values are Bonferroni-corrected for multiple comparisons.",
        r"\item $^{*}p < 0.05$, $^{**}p < 0.01$, $^{***}p < 0.001$",
        r"\end{tablenotes}",
        r"\end{table}",
    ])
    
    return "\n".join(lines)
