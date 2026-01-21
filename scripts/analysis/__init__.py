"""Analysis utilities for thesis experiments."""

from .statistical_analysis import (
    PairedComparisonResult,
    run_paired_comparison,
    run_multi_metric_comparison,
    calculate_cohens_d_z,
    bootstrap_ci,
    apply_bonferroni_correction,
    check_normality,
    format_results_table,
    generate_latex_table,
)

from .sample_collector import (
    ExperimentResult,
    PairedSamples,
    SampleValidationResult,
    SampleCollector,
    validate_samples,
    calculate_required_sample_size,
    PRIMARY_METRICS,
    SECONDARY_METRICS,
    MIN_SAMPLE_SIZE,
    RECOMMENDED_SAMPLE_SIZE,
)

__all__ = [
    # Statistical analysis
    "PairedComparisonResult",
    "run_paired_comparison",
    "run_multi_metric_comparison",
    "calculate_cohens_d_z",
    "bootstrap_ci",
    "apply_bonferroni_correction",
    "check_normality",
    "format_results_table",
    "generate_latex_table",
    # Sample collection
    "ExperimentResult",
    "PairedSamples",
    "SampleValidationResult",
    "SampleCollector",
    "validate_samples",
    "calculate_required_sample_size",
    "PRIMARY_METRICS",
    "SECONDARY_METRICS",
    "MIN_SAMPLE_SIZE",
    "RECOMMENDED_SAMPLE_SIZE",
]
