"""Statistical validation sample collection for thesis experiments.

Fix #8: Statistical Validation Sample Collection

This module ensures proper sample collection for statistical analysis:
- Paired samples (same seed, different algorithms)
- Sufficient sample sizes for statistical power
- Proper data structure for paired tests
- Sample validation and sanity checks

Usage:
    from scripts.analysis.sample_collector import (
        SampleCollector,
        PairedSamples,
        validate_samples,
    )
    
    collector = SampleCollector()
    collector.add_ml_result(seed=2, metrics={...})
    collector.add_a3_result(seed=2, metrics={...})
    
    paired = collector.get_paired_samples()
    validation = validate_samples(paired)
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np
from scipy import stats

logger = logging.getLogger(__name__)


# =============================================================================
# METRICS DEFINITIONS
# =============================================================================

# Primary metrics for thesis comparison
PRIMARY_METRICS = [
    "handover_count",
    "pingpong_rate",
    "rlf_count",
    "mean_throughput",
    "handover_latency_ms",
]

# Secondary metrics (optional, for extended analysis)
SECONDARY_METRICS = [
    "total_interruption_time_ms",
    "max_rsrp_drop_db",
    "sinr_mean",
    "cell_edge_time_ratio",
]

# Minimum sample size for statistical validity
MIN_SAMPLE_SIZE = 10

# Recommended sample size for good power (0.8)
RECOMMENDED_SAMPLE_SIZE = 30


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class ExperimentResult:
    """Result from a single experiment run."""
    seed: int
    algorithm: str  # 'ml' or 'a3'
    scenario: str
    metrics: Dict[str, float]
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def get_metric(self, name: str) -> Optional[float]:
        """Get metric value, returning None if not present."""
        return self.metrics.get(name)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "seed": self.seed,
            "algorithm": self.algorithm,
            "scenario": self.scenario,
            "metrics": self.metrics,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ExperimentResult":
        """Create from dictionary."""
        return cls(
            seed=d["seed"],
            algorithm=d["algorithm"],
            scenario=d["scenario"],
            metrics=d["metrics"],
            metadata=d.get("metadata", {}),
        )


@dataclass
class PairedSamples:
    """Paired samples for statistical comparison.
    
    Contains matched pairs of ML and A3 results with the same seeds.
    """
    scenario: str
    seeds: List[int]
    ml_values: Dict[str, np.ndarray]  # metric_name -> array of values
    a3_values: Dict[str, np.ndarray]  # metric_name -> array of values
    
    @property
    def n_pairs(self) -> int:
        """Number of matched pairs."""
        return len(self.seeds)
    
    def get_differences(self, metric: str) -> np.ndarray:
        """Get difference array (ML - A3) for a metric."""
        if metric not in self.ml_values or metric not in self.a3_values:
            raise ValueError(f"Metric '{metric}' not in samples")
        return self.ml_values[metric] - self.a3_values[metric]
    
    def is_valid_for_analysis(self) -> Tuple[bool, str]:
        """Check if samples are valid for statistical analysis."""
        if self.n_pairs < MIN_SAMPLE_SIZE:
            return False, f"Insufficient pairs: {self.n_pairs} < {MIN_SAMPLE_SIZE}"
        
        # Check for any missing metrics
        ml_metrics = set(self.ml_values.keys())
        a3_metrics = set(self.a3_values.keys())
        
        if ml_metrics != a3_metrics:
            return False, f"Metric mismatch: ML has {ml_metrics}, A3 has {a3_metrics}"
        
        # Check for NaN/Inf
        for metric in ml_metrics:
            if np.any(np.isnan(self.ml_values[metric])):
                return False, f"NaN in ML values for {metric}"
            if np.any(np.isnan(self.a3_values[metric])):
                return False, f"NaN in A3 values for {metric}"
        
        return True, "Valid"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "scenario": self.scenario,
            "seeds": self.seeds,
            "ml_values": {k: v.tolist() for k, v in self.ml_values.items()},
            "a3_values": {k: v.tolist() for k, v in self.a3_values.items()},
        }
    
    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PairedSamples":
        """Create from dictionary."""
        return cls(
            scenario=d["scenario"],
            seeds=d["seeds"],
            ml_values={k: np.array(v) for k, v in d["ml_values"].items()},
            a3_values={k: np.array(v) for k, v in d["a3_values"].items()},
        )


# =============================================================================
# SAMPLE COLLECTOR
# =============================================================================

class SampleCollector:
    """Collects and pairs experiment results for statistical analysis.
    
    Ensures proper pairing of ML and A3 results by seed.
    """
    
    def __init__(self, scenario: str):
        """Initialize collector for a specific scenario.
        
        Args:
            scenario: Scenario name (e.g., 'highway', 'smart_city')
        """
        self.scenario = scenario
        self.ml_results: Dict[int, ExperimentResult] = {}  # seed -> result
        self.a3_results: Dict[int, ExperimentResult] = {}  # seed -> result
        self._warnings: List[str] = []
    
    def add_result(self, result: ExperimentResult) -> None:
        """Add an experiment result.
        
        Args:
            result: Experiment result to add
        """
        if result.scenario != self.scenario:
            self._warnings.append(
                f"Scenario mismatch: expected {self.scenario}, got {result.scenario}"
            )
        
        if result.algorithm.lower() == 'ml':
            if result.seed in self.ml_results:
                self._warnings.append(f"Duplicate ML result for seed {result.seed}")
            self.ml_results[result.seed] = result
        elif result.algorithm.lower() == 'a3':
            if result.seed in self.a3_results:
                self._warnings.append(f"Duplicate A3 result for seed {result.seed}")
            self.a3_results[result.seed] = result
        else:
            raise ValueError(f"Unknown algorithm: {result.algorithm}")
    
    def add_ml_result(self, seed: int, metrics: Dict[str, float], **metadata) -> None:
        """Convenience method to add ML result."""
        self.add_result(ExperimentResult(
            seed=seed,
            algorithm='ml',
            scenario=self.scenario,
            metrics=metrics,
            metadata=metadata,
        ))
    
    def add_a3_result(self, seed: int, metrics: Dict[str, float], **metadata) -> None:
        """Convenience method to add A3 result."""
        self.add_result(ExperimentResult(
            seed=seed,
            algorithm='a3',
            scenario=self.scenario,
            metrics=metrics,
            metadata=metadata,
        ))
    
    def get_paired_seeds(self) -> List[int]:
        """Get seeds that have both ML and A3 results."""
        ml_seeds = set(self.ml_results.keys())
        a3_seeds = set(self.a3_results.keys())
        return sorted(ml_seeds & a3_seeds)
    
    def get_unpaired_seeds(self) -> Dict[str, List[int]]:
        """Get seeds that are missing a pair."""
        ml_seeds = set(self.ml_results.keys())
        a3_seeds = set(self.a3_results.keys())
        
        return {
            "ml_only": sorted(ml_seeds - a3_seeds),
            "a3_only": sorted(a3_seeds - ml_seeds),
        }
    
    def get_paired_samples(self, metrics: List[str] = None) -> PairedSamples:
        """Get paired samples for analysis.
        
        Args:
            metrics: List of metrics to include (default: PRIMARY_METRICS)
            
        Returns:
            PairedSamples object
        """
        metrics = metrics or PRIMARY_METRICS
        paired_seeds = self.get_paired_seeds()
        
        if not paired_seeds:
            raise ValueError("No paired samples available")
        
        ml_values = {m: [] for m in metrics}
        a3_values = {m: [] for m in metrics}
        
        for seed in paired_seeds:
            ml_result = self.ml_results[seed]
            a3_result = self.a3_results[seed]
            
            for metric in metrics:
                ml_val = ml_result.get_metric(metric)
                a3_val = a3_result.get_metric(metric)
                
                if ml_val is None or a3_val is None:
                    # Skip this metric if not available
                    continue
                
                ml_values[metric].append(ml_val)
                a3_values[metric].append(a3_val)
        
        # Remove metrics that had no valid pairs
        ml_values = {k: np.array(v) for k, v in ml_values.items() if v}
        a3_values = {k: np.array(v) for k, v in a3_values.items() if v}
        
        return PairedSamples(
            scenario=self.scenario,
            seeds=paired_seeds,
            ml_values=ml_values,
            a3_values=a3_values,
        )
    
    def get_collection_status(self) -> Dict[str, Any]:
        """Get status of sample collection."""
        paired = self.get_paired_seeds()
        unpaired = self.get_unpaired_seeds()
        
        return {
            "scenario": self.scenario,
            "ml_count": len(self.ml_results),
            "a3_count": len(self.a3_results),
            "paired_count": len(paired),
            "unpaired_ml": len(unpaired["ml_only"]),
            "unpaired_a3": len(unpaired["a3_only"]),
            "ready_for_analysis": len(paired) >= MIN_SAMPLE_SIZE,
            "recommended_more": len(paired) < RECOMMENDED_SAMPLE_SIZE,
            "warnings": self._warnings,
        }
    
    def save(self, output_path: Path) -> None:
        """Save collected samples to JSON."""
        data = {
            "scenario": self.scenario,
            "ml_results": {str(k): v.to_dict() for k, v in self.ml_results.items()},
            "a3_results": {str(k): v.to_dict() for k, v in self.a3_results.items()},
            "status": self.get_collection_status(),
        }
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w') as f:
            json.dump(data, f, indent=2)
        
        logger.info(f"Saved samples to {output_path}")
    
    @classmethod
    def load(cls, input_path: Path) -> "SampleCollector":
        """Load samples from JSON."""
        with open(input_path, 'r') as f:
            data = json.load(f)
        
        collector = cls(data["scenario"])
        
        for seed_str, result_dict in data["ml_results"].items():
            collector.ml_results[int(seed_str)] = ExperimentResult.from_dict(result_dict)
        
        for seed_str, result_dict in data["a3_results"].items():
            collector.a3_results[int(seed_str)] = ExperimentResult.from_dict(result_dict)
        
        return collector


# =============================================================================
# SAMPLE VALIDATION
# =============================================================================

@dataclass
class SampleValidationResult:
    """Result of sample validation."""
    is_valid: bool
    n_pairs: int
    warnings: List[str]
    errors: List[str]
    power_analysis: Dict[str, float]
    outlier_info: Dict[str, Any]
    
    def summary(self) -> str:
        """Generate human-readable summary."""
        lines = [
            "Sample Validation Result",
            "=" * 40,
            f"Valid: {'✓ Yes' if self.is_valid else '✗ No'}",
            f"Paired samples: {self.n_pairs}",
            "",
        ]
        
        if self.power_analysis:
            lines.append("Power Analysis:")
            for metric, power in self.power_analysis.items():
                status = "✓" if power >= 0.8 else "⚠"
                lines.append(f"  {status} {metric}: {power:.2f}")
        
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


def validate_samples(
    paired: PairedSamples,
    alpha: float = 0.05,
    min_effect_size: float = 0.5,
) -> SampleValidationResult:
    """Validate paired samples for statistical analysis.
    
    Args:
        paired: Paired samples to validate
        alpha: Significance level (default 0.05)
        min_effect_size: Minimum effect size to detect (Cohen's d)
        
    Returns:
        SampleValidationResult
    """
    warnings = []
    errors = []
    
    # Check basic validity
    valid, msg = paired.is_valid_for_analysis()
    if not valid:
        errors.append(msg)
    
    # Check sample size
    if paired.n_pairs < MIN_SAMPLE_SIZE:
        errors.append(
            f"Insufficient sample size: {paired.n_pairs} < {MIN_SAMPLE_SIZE}"
        )
    elif paired.n_pairs < RECOMMENDED_SAMPLE_SIZE:
        warnings.append(
            f"Below recommended sample size: {paired.n_pairs} < {RECOMMENDED_SAMPLE_SIZE}"
        )
    
    # Power analysis
    power_analysis = {}
    for metric in paired.ml_values.keys():
        try:
            diff = paired.get_differences(metric)
            
            # Estimate effect size
            d = np.mean(diff) / (np.std(diff) + 1e-10)
            
            # Approximate power calculation
            # For paired t-test: power ≈ Φ(|d|√n - z_α/2)
            from scipy.stats import norm
            z_alpha = norm.ppf(1 - alpha / 2)
            z_power = abs(d) * np.sqrt(paired.n_pairs) - z_alpha
            power = norm.cdf(z_power)
            
            power_analysis[metric] = round(power, 3)
            
            if power < 0.8:
                warnings.append(
                    f"Low power for {metric}: {power:.2f} (need ≥0.80)"
                )
                
        except Exception as e:
            warnings.append(f"Power analysis failed for {metric}: {e}")
    
    # Outlier detection
    outlier_info = {}
    for metric in paired.ml_values.keys():
        try:
            diff = paired.get_differences(metric)
            
            # IQR method
            q1, q3 = np.percentile(diff, [25, 75])
            iqr = q3 - q1
            lower = q1 - 1.5 * iqr
            upper = q3 + 1.5 * iqr
            
            outliers = np.sum((diff < lower) | (diff > upper))
            
            if outliers > 0:
                outlier_info[metric] = {
                    "count": int(outliers),
                    "indices": np.where((diff < lower) | (diff > upper))[0].tolist(),
                }
                
                if outliers / paired.n_pairs > 0.1:
                    warnings.append(
                        f"High outlier ratio for {metric}: {outliers}/{paired.n_pairs}"
                    )
                    
        except Exception as e:
            warnings.append(f"Outlier detection failed for {metric}: {e}")
    
    is_valid = len(errors) == 0
    
    return SampleValidationResult(
        is_valid=is_valid,
        n_pairs=paired.n_pairs,
        warnings=warnings,
        errors=errors,
        power_analysis=power_analysis,
        outlier_info=outlier_info,
    )


def calculate_required_sample_size(
    effect_size: float = 0.5,
    power: float = 0.8,
    alpha: float = 0.05,
) -> int:
    """Calculate required sample size for desired power.
    
    Args:
        effect_size: Expected Cohen's d
        power: Desired statistical power
        alpha: Significance level
        
    Returns:
        Required sample size (number of pairs)
    """
    from scipy.stats import norm
    
    z_alpha = norm.ppf(1 - alpha / 2)
    z_power = norm.ppf(power)
    
    # n = ((z_α/2 + z_β) / d)^2
    n = ((z_alpha + z_power) / effect_size) ** 2
    
    return int(np.ceil(n))


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Data structures
    'ExperimentResult',
    'PairedSamples',
    'SampleValidationResult',
    
    # Collector
    'SampleCollector',
    
    # Validation
    'validate_samples',
    'calculate_required_sample_size',
    
    # Constants
    'PRIMARY_METRICS',
    'SECONDARY_METRICS',
    'MIN_SAMPLE_SIZE',
    'RECOMMENDED_SAMPLE_SIZE',
]
