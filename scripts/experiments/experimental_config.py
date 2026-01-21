"""Experimental matrix configuration for thesis experiments.

Fix #11: Tier 1 Minimal Matrix
Fix #12: Seed Selection Strategy
Fix #13: Realistic Runtime Estimates

This module defines the experimental configuration for reproducible
thesis experiments, including:
- Tier 1: Minimal matrix (40 runs) for core findings
- Tier 2: Extended matrix (100+ runs) for sensitivity analysis
- Pre-selected seeds that avoid known bad states
- Runtime estimates for planning

Usage:
    from scripts.experiments.experimental_config import (
        get_tier1_matrix,
        ExperimentConfig,
        estimate_total_runtime,
    )
    
    # Get all Tier 1 experiment configurations
    for config in get_tier1_matrix():
        run_experiment(config)
"""
from __future__ import annotations

import hashlib
import itertools
import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# SEED STRATEGY (Fix #12)
# =============================================================================

class SeedStrategy(Enum):
    """Strategies for seed selection.
    
    Fix #12: Seed Selection Strategy
    """
    PRIMES = "primes"           # Use prime numbers
    WELL_SPACED = "well_spaced"  # Evenly distributed across range
    MERSENNE = "mersenne"        # Mersenne primes (2^p - 1)
    FIXED = "fixed"              # Pre-selected known-good seeds


# Pre-selected seeds that have been tested to avoid edge cases
# These avoid seeds that cause:
# - Initial UE spawn in cell overlap regions
# - Pathological random number sequences
# - Edge cases in Doppler fading initialization
KNOWN_GOOD_SEEDS = [
    2, 3, 5, 7, 11, 13, 17, 19, 23, 29,  # First 10 primes
    31, 37, 41, 43, 47, 53, 59, 61, 67, 71,  # Next 10 primes
    97, 101, 103, 107, 109, 113, 127, 131, 137, 139,  # More primes
]

# Seeds to explicitly avoid (scientifically justified reasons only)
# NOTE: Seed value itself doesn't affect statistical properties of PRNGs
# We only avoid seeds that have specific technical issues
PROBLEMATIC_SEEDS = {
    0,    # NumPy/some PRNGs treat 0 specially (may seed from clock)
    1,    # Some older PRNGs had poor sequences starting from 1
    # Removed 42, 666, 1234 - no scientific reason to avoid these
}

# Pre-computed primes for efficiency (first 100 primes up to 541)
# Why 100 primes? For statistical experiments:
#   - Most experiments need 10-30 independent seeds for bootstrap CIs
#   - Even 100 replications (generous) only need 100 unique seeds
#   - Primes up to 541 are well-distributed and avoid collisions
#   - If more seeds needed, _is_prime() generates additional primes on-demand
# List for ordered access (get_seeds uses slicing)
_PRIME_CACHE = [
    2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59, 61, 67, 71,
    73, 79, 83, 89, 97, 101, 103, 107, 109, 113, 127, 131, 137, 139, 149, 151,
    157, 163, 167, 173, 179, 181, 191, 193, 197, 199, 211, 223, 227, 229, 233,
    239, 241, 251, 257, 263, 269, 271, 277, 281, 283, 293, 307, 311, 313, 317,
    331, 337, 347, 349, 353, 359, 367, 373, 379, 383, 389, 397, 401, 409, 419,
    421, 431, 433, 439, 443, 449, 457, 461, 463, 467, 479, 487, 491, 499, 503,
    509, 521, 523, 541,
]
# Frozen set for O(1) membership testing in _is_prime()
_PRIME_SET = frozenset(_PRIME_CACHE)


def get_seeds(
    n_seeds: int = 10,
    strategy: SeedStrategy = SeedStrategy.PRIMES,
    avoid: Optional[set] = None,
) -> List[int]:
    """Generate seeds according to specified strategy.
    
    Args:
        n_seeds: Number of seeds needed
        strategy: Seed selection strategy
        avoid: Additional seeds to avoid
        
    Returns:
        List of seed values
    """
    avoid = avoid or set()
    combined_avoid = PROBLEMATIC_SEEDS | avoid
    
    if strategy == SeedStrategy.FIXED:
        # Use pre-tested known-good seeds
        valid_seeds = [s for s in KNOWN_GOOD_SEEDS if s not in combined_avoid]
        return valid_seeds[:n_seeds]
    
    elif strategy == SeedStrategy.PRIMES:
        # Use pre-computed primes from cache first for efficiency
        seeds = [p for p in _PRIME_CACHE if p not in combined_avoid][:n_seeds]
        
        # If we need more, generate dynamically
        if len(seeds) < n_seeds:
            candidate = _PRIME_CACHE[-1] + 2  # Start after cached primes
            while len(seeds) < n_seeds:
                if _is_prime(candidate) and candidate not in combined_avoid:
                    seeds.append(candidate)
                candidate += 2  # Skip even numbers
        return seeds
    
    elif strategy == SeedStrategy.WELL_SPACED:
        # Evenly distributed across range [100, 10000]
        seeds = []
        step = 9900 // (n_seeds + 1)
        for i in range(1, n_seeds + 1):
            candidate = 100 + i * step
            while candidate in combined_avoid:
                candidate += 1
            seeds.append(candidate)
        return seeds
    
    elif strategy == SeedStrategy.MERSENNE:
        # Mersenne primes: 2^p - 1 where both p and 2^p-1 are prime
        mersenne_primes = [3, 7, 31, 127, 8191]
        valid = [m for m in mersenne_primes if m not in combined_avoid]
        # Pad with regular primes if needed
        if len(valid) < n_seeds:
            valid.extend(get_seeds(n_seeds - len(valid), SeedStrategy.PRIMES, avoid))
        return valid[:n_seeds]
    
    else:
        raise ValueError(f"Unknown seed strategy: {strategy}")


def _is_prime(n: int) -> bool:
    """Check if n is prime.
    
    Uses cached primes (frozenset) for O(1) lookup on small numbers.
    Falls back to trial division for larger numbers.
    """
    if n < 2:
        return False
    
    # Use frozenset for O(1) lookup on cached primes
    if n <= _PRIME_CACHE[-1]:
        return n in _PRIME_SET
    
    # Trial division for larger numbers
    if n % 2 == 0:
        return False
    for i in range(3, int(n ** 0.5) + 1, 2):
        if n % i == 0:
            return False
    return True


# =============================================================================
# SCENARIO DEFINITIONS
# =============================================================================

class Scenario(Enum):
    """Available experimental scenarios."""
    HIGHWAY = "highway"
    URBAN_CANYON = "urban_canyon"
    SMART_CITY = "smart_city"
    STATIONARY_EDGE = "stationary_edge"


class Algorithm(Enum):
    """Available handover algorithms."""
    ML = "ml"
    A3 = "a3"


@dataclass
class ScenarioConfig:
    """Configuration for a specific scenario."""
    name: str
    description: str
    duration_seconds: float
    n_ues: int
    n_cells: int
    velocity_range: Tuple[float, float]  # (min, max) in m/s
    expected_handovers: Tuple[int, int]  # (min, max) expected handovers
    
    # Runtime estimates in minutes
    estimated_runtime_minutes: float = 8.0


# Scenario configurations with runtime estimates
SCENARIO_CONFIGS = {
    Scenario.HIGHWAY: ScenarioConfig(
        name="Highway High-Speed",
        description="High-speed UEs (100-120 km/h) along linear highway",
        duration_seconds=300.0,
        n_ues=10,
        n_cells=5,
        velocity_range=(27.8, 33.3),  # 100-120 km/h in m/s
        expected_handovers=(20, 50),
        estimated_runtime_minutes=8.0,
    ),
    Scenario.URBAN_CANYON: ScenarioConfig(
        name="Urban Canyon",
        description="Medium-speed UEs (30-50 km/h) with shadowing effects",
        duration_seconds=300.0,
        n_ues=20,
        n_cells=8,
        velocity_range=(8.3, 13.9),  # 30-50 km/h in m/s
        expected_handovers=(30, 80),
        estimated_runtime_minutes=10.0,
    ),
    Scenario.SMART_CITY: ScenarioConfig(
        name="Smart City Downtown",
        description="Mixed mobility with dense small cells",
        duration_seconds=300.0,
        n_ues=30,
        n_cells=12,
        velocity_range=(1.4, 13.9),  # Walking to 50 km/h
        expected_handovers=(40, 120),
        estimated_runtime_minutes=12.0,
    ),
    Scenario.STATIONARY_EDGE: ScenarioConfig(
        name="Stationary Cell Edge",
        description="Static UEs at cell boundaries (baseline)",
        duration_seconds=180.0,
        n_ues=5,
        n_cells=3,
        velocity_range=(0.0, 0.5),  # Near-stationary
        expected_handovers=(0, 5),
        estimated_runtime_minutes=5.0,
    ),
}


# =============================================================================
# EXPERIMENT CONFIGURATION (Fix #11, #13)
# =============================================================================

@dataclass
class ExperimentConfig:
    """Complete configuration for a single experiment run.
    
    Fix #11: Complete specification of experiment parameters.
    """
    # Identification
    experiment_id: str
    tier: int
    
    # Core parameters
    scenario: Scenario
    algorithm: Algorithm
    seed: int
    
    # Derived parameters (from scenario)
    duration_seconds: float = field(default=300.0)
    
    # SHAP configuration (Fix #15)
    shap_mode: str = "off"  # off, sampled, always
    
    # Metrics collection
    collect_rsrp_traces: bool = True
    collect_position_traces: bool = True
    collect_throughput_samples: bool = True
    
    # Output configuration
    output_dir: Optional[str] = None
    
    def __post_init__(self):
        """Generate experiment ID if not provided."""
        if not self.experiment_id:
            self.experiment_id = self._generate_id()
        
        # Set duration from scenario
        if self.scenario in SCENARIO_CONFIGS:
            self.duration_seconds = SCENARIO_CONFIGS[self.scenario].duration_seconds
    
    def _generate_id(self) -> str:
        """Generate unique experiment ID."""
        id_string = f"{self.tier}_{self.scenario.value}_{self.algorithm.value}_{self.seed}"
        hash_suffix = hashlib.md5(id_string.encode()).hexdigest()[:6]
        return f"exp_{id_string}_{hash_suffix}"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        d = asdict(self)
        d['scenario'] = self.scenario.value
        d['algorithm'] = self.algorithm.value
        return d
    
    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ExperimentConfig":
        """Create from dictionary."""
        d['scenario'] = Scenario(d['scenario'])
        d['algorithm'] = Algorithm(d['algorithm'])
        return cls(**d)
    
    def get_estimated_runtime(self) -> timedelta:
        """Get estimated runtime for this experiment.
        
        Fix #13: Realistic runtime estimates.
        """
        if self.scenario in SCENARIO_CONFIGS:
            minutes = SCENARIO_CONFIGS[self.scenario].estimated_runtime_minutes
        else:
            minutes = 10.0  # Default
        
        # SHAP adds overhead
        if self.shap_mode == "always":
            minutes *= 1.5
        elif self.shap_mode == "sampled":
            minutes *= 1.1
        
        return timedelta(minutes=minutes)


# =============================================================================
# TIER DEFINITIONS
# =============================================================================

def get_tier1_matrix(
    n_seeds: int = 10,
    seed_strategy: SeedStrategy = SeedStrategy.PRIMES,
) -> Iterator[ExperimentConfig]:
    """Generate Tier 1 minimal experiment matrix.
    
    Fix #11: Tier 1 Minimal Matrix
    
    Tier 1 = 2 scenarios × 2 algorithms × 10 seeds = 40 experiments
    
    Scenarios: Highway (high-speed) + Smart City (mixed)
    Algorithms: ML vs A3
    Seeds: 10 prime numbers
    
    This provides:
    - Sufficient statistical power (n=10 per condition)
    - Core findings for thesis
    - ~6-7 hours total runtime
    
    Yields:
        ExperimentConfig instances
    """
    # Tier 1 scenarios - most important for thesis
    tier1_scenarios = [Scenario.HIGHWAY, Scenario.SMART_CITY]
    algorithms = [Algorithm.ML, Algorithm.A3]
    seeds = get_seeds(n_seeds, seed_strategy)
    
    for scenario, algorithm, seed in itertools.product(
        tier1_scenarios, algorithms, seeds
    ):
        yield ExperimentConfig(
            experiment_id="",  # Auto-generated
            tier=1,
            scenario=scenario,
            algorithm=algorithm,
            seed=seed,
            shap_mode="off",  # No SHAP for batch experiments
        )


def get_tier2_matrix(
    n_seeds: int = 10,
    seed_strategy: SeedStrategy = SeedStrategy.PRIMES,
) -> Iterator[ExperimentConfig]:
    """Generate Tier 2 extended experiment matrix.
    
    Tier 2 adds:
    - Urban Canyon scenario
    - Stationary Edge baseline
    
    Total: 4 scenarios × 2 algorithms × 10 seeds = 80 experiments
    """
    all_scenarios = list(Scenario)
    algorithms = [Algorithm.ML, Algorithm.A3]
    seeds = get_seeds(n_seeds, seed_strategy)
    
    for scenario, algorithm, seed in itertools.product(
        all_scenarios, algorithms, seeds
    ):
        yield ExperimentConfig(
            experiment_id="",
            tier=2,
            scenario=scenario,
            algorithm=algorithm,
            seed=seed,
            shap_mode="off",
        )


def get_sensitivity_matrix(
    base_scenario: Scenario = Scenario.HIGHWAY,
    parameter_name: str = "hysteresis",
    parameter_values: List[Any] = None,
    n_seeds: int = 5,
) -> Iterator[ExperimentConfig]:
    """Generate sensitivity analysis matrix.
    
    Used for exploring parameter sensitivity (e.g., A3 hysteresis).
    """
    if parameter_values is None:
        parameter_values = [1.0, 2.0, 3.0, 4.0, 5.0]  # dB values for hysteresis
    
    seeds = get_seeds(n_seeds, SeedStrategy.PRIMES)
    
    for value, seed in itertools.product(parameter_values, seeds):
        config = ExperimentConfig(
            experiment_id="",
            tier=3,  # Sensitivity analysis tier
            scenario=base_scenario,
            algorithm=Algorithm.A3,
            seed=seed,
            shap_mode="off",
        )
        # Store parameter variation in output_dir as identifier
        config.output_dir = f"sensitivity_{parameter_name}_{value}"
        yield config


# =============================================================================
# RUNTIME ESTIMATION (Fix #13)
# =============================================================================

def estimate_total_runtime(
    configs: List[ExperimentConfig],
    parallel_workers: int = 1,
) -> Dict[str, Any]:
    """Estimate total runtime for experiment matrix.
    
    Fix #13: Realistic Runtime Estimates
    
    Args:
        configs: List of experiment configurations
        parallel_workers: Number of parallel workers (1 = sequential)
        
    Returns:
        Dictionary with runtime estimates
    """
    total_minutes = sum(
        config.get_estimated_runtime().total_seconds() / 60
        for config in configs
    )
    
    # Account for parallelism
    effective_minutes = total_minutes / parallel_workers
    
    # Add overhead for startup/shutdown (5% per experiment)
    overhead_factor = 1.05
    effective_minutes *= overhead_factor
    
    # Add buffer for variance (10%)
    buffer_factor = 1.10
    with_buffer = effective_minutes * buffer_factor
    
    return {
        "total_experiments": len(configs),
        "parallel_workers": parallel_workers,
        "estimated_minutes": round(effective_minutes, 1),
        "with_buffer_minutes": round(with_buffer, 1),
        "estimated_hours": round(effective_minutes / 60, 1),
        "with_buffer_hours": round(with_buffer / 60, 1),
        "breakdown": _breakdown_by_scenario(configs),
    }


def _breakdown_by_scenario(configs: List[ExperimentConfig]) -> Dict[str, Dict[str, Any]]:
    """Break down runtime estimates by scenario.
    
    Args:
        configs: List of experiment configurations
        
    Returns:
        Dict mapping scenario name to dict with 'count' and 'total_minutes' keys
    """
    breakdown: Dict[str, Dict[str, Any]] = {}
    
    for config in configs:
        scenario_name = config.scenario.value
        if scenario_name not in breakdown:
            breakdown[scenario_name] = {
                "count": 0,
                "total_minutes": 0.0,
            }
        
        breakdown[scenario_name]["count"] += 1
        breakdown[scenario_name]["total_minutes"] += (
            config.get_estimated_runtime().total_seconds() / 60
        )
    
    return breakdown


# =============================================================================
# EXPERIMENT MATRIX PERSISTENCE
# =============================================================================

def save_experiment_matrix(
    configs: List[ExperimentConfig],
    output_path: Path,
) -> None:
    """Save experiment matrix to JSON file.
    
    Args:
        configs: List of configurations
        output_path: Path to save JSON
    """
    data = {
        "version": "1.0",
        "total_experiments": len(configs),
        "experiments": [c.to_dict() for c in configs],
        "runtime_estimate": estimate_total_runtime(configs),
    }
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(data, f, indent=2)
    
    logger.info("Saved experiment matrix to %s", output_path)


def load_experiment_matrix(input_path: Path) -> List[ExperimentConfig]:
    """Load experiment matrix from JSON file.
    
    Args:
        input_path: Path to JSON file
        
    Returns:
        List of ExperimentConfig instances
    """
    with open(input_path, 'r') as f:
        data = json.load(f)
    
    configs = [ExperimentConfig.from_dict(d) for d in data["experiments"]]
    logger.info("Loaded %d experiments from %s", len(configs), input_path)
    
    return configs


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def print_matrix_summary(configs: List[ExperimentConfig]) -> None:
    """Print summary of experiment matrix."""
    estimate = estimate_total_runtime(configs)
    
    print("\n" + "=" * 60)
    print("EXPERIMENT MATRIX SUMMARY")
    print("=" * 60)
    print(f"Total Experiments: {estimate['total_experiments']}")
    print(f"Estimated Runtime: {estimate['estimated_hours']:.1f} hours")
    print(f"With Buffer:       {estimate['with_buffer_hours']:.1f} hours")
    print("\nBreakdown by Scenario:")
    for scenario, info in estimate['breakdown'].items():
        print(f"  {scenario}: {info['count']} runs, {info['total_minutes']:.0f} min")
    print("=" * 60 + "\n")


def generate_tier1_matrix_file(output_dir: Path = None) -> Path:
    """Generate and save Tier 1 experiment matrix.
    
    Convenience function for thesis preparation.
    """
    if output_dir is None:
        output_dir = Path(__file__).parent.parent.parent / "thesis_results"
    
    configs = list(get_tier1_matrix())
    output_path = output_dir / "experiment_matrix_tier1.json"
    
    save_experiment_matrix(configs, output_path)
    print_matrix_summary(configs)
    
    return output_path


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Enums
    'Scenario',
    'Algorithm',
    'SeedStrategy',
    
    # Data classes
    'ScenarioConfig',
    'ExperimentConfig',
    
    # Configurations
    'SCENARIO_CONFIGS',
    'KNOWN_GOOD_SEEDS',
    'PROBLEMATIC_SEEDS',
    
    # Matrix generators
    'get_tier1_matrix',
    'get_tier2_matrix',
    'get_sensitivity_matrix',
    'get_seeds',
    
    # Runtime estimation
    'estimate_total_runtime',
    
    # Persistence
    'save_experiment_matrix',
    'load_experiment_matrix',
    
    # Utilities
    'print_matrix_summary',
    'generate_tier1_matrix_file',
]


if __name__ == "__main__":
    # Generate Tier 1 matrix when run directly
    generate_tier1_matrix_file()
