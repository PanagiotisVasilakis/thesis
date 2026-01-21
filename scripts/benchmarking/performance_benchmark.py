"""Performance benchmarking protocol for thesis experiments.

Fix #22: Performance Benchmarking Protocol

This module provides tools for measuring and validating system performance
to ensure experiments can complete within reasonable timeframes.

Usage:
    from scripts.benchmarking.performance_benchmark import (
        run_benchmark_suite,
        BenchmarkResult,
    )
    
    results = run_benchmark_suite()
    print(results.summary())
"""
from __future__ import annotations

import gc
import json
import logging
import os
import platform
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


# =============================================================================
# SYSTEM INFORMATION
# =============================================================================

@dataclass
class SystemInfo:
    """System information for benchmarking context."""
    platform: str
    platform_release: str
    platform_version: str
    architecture: str
    processor: str
    python_version: str
    cpu_count: int
    memory_total_gb: float
    
    @classmethod
    def collect(cls) -> "SystemInfo":
        """Collect current system information."""
        try:
            import psutil
            memory_total_gb = psutil.virtual_memory().total / (1024 ** 3)
        except ImportError:
            logger.warning(
                "psutil not installed - memory info unavailable. "
                "Install with: pip install psutil"
            )
            memory_total_gb = 0.0
        
        return cls(
            platform=platform.system(),
            platform_release=platform.release(),
            platform_version=platform.version(),
            architecture=platform.machine(),
            processor=platform.processor(),
            python_version=platform.python_version(),
            cpu_count=os.cpu_count() or 1,
            memory_total_gb=memory_total_gb,
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


# =============================================================================
# BENCHMARK RESULTS
# =============================================================================

@dataclass
class SingleBenchmark:
    """Result of a single benchmark run."""
    name: str
    iterations: int
    mean_time_ms: float
    std_time_ms: float
    min_time_ms: float
    max_time_ms: float
    ops_per_second: float
    passed: bool
    threshold_ms: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class BenchmarkSuite:
    """Collection of benchmark results."""
    timestamp: str
    system_info: SystemInfo
    benchmarks: List[SingleBenchmark] = field(default_factory=list)
    overall_passed: bool = True
    
    def add(self, benchmark: SingleBenchmark) -> None:
        """Add benchmark result."""
        self.benchmarks.append(benchmark)
        if not benchmark.passed:
            self.overall_passed = False
    
    def summary(self) -> str:
        """Generate human-readable summary."""
        lines = [
            "=" * 60,
            "PERFORMANCE BENCHMARK RESULTS",
            "=" * 60,
            f"Timestamp: {self.timestamp}",
            f"Platform: {self.system_info.platform} {self.system_info.platform_release}",
            f"Python: {self.system_info.python_version}",
            f"CPUs: {self.system_info.cpu_count}",
            f"Memory: {self.system_info.memory_total_gb:.1f} GB",
            "-" * 60,
        ]
        
        for b in self.benchmarks:
            status = "✓ PASS" if b.passed else "✗ FAIL"
            lines.append(
                f"{status} {b.name}: {b.mean_time_ms:.2f} ± {b.std_time_ms:.2f} ms"
            )
            if b.threshold_ms:
                lines.append(f"      (threshold: {b.threshold_ms:.2f} ms)")
        
        lines.append("-" * 60)
        overall = "PASSED" if self.overall_passed else "FAILED"
        lines.append(f"Overall: {overall}")
        lines.append("=" * 60)
        
        return "\n".join(lines)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "timestamp": self.timestamp,
            "system_info": self.system_info.to_dict(),
            "benchmarks": [b.to_dict() for b in self.benchmarks],
            "overall_passed": self.overall_passed,
        }
    
    def save(self, output_path: Path) -> None:
        """Save results to JSON file."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)
        logger.info(f"Saved benchmark results to {output_path}")


# =============================================================================
# BENCHMARK EXECUTION
# =============================================================================

def run_timed_iterations(
    func: Callable[[], Any],
    iterations: int = 100,
    warmup: int = 5,
) -> Tuple[List[float], Any]:
    """Run function multiple times and collect timing data.
    
    Args:
        func: Function to benchmark
        iterations: Number of timed iterations
        warmup: Number of warmup iterations (not timed)
        
    Returns:
        (list of times in ms, last result)
    """
    # Warmup
    result = None
    for _ in range(warmup):
        result = func()
    
    # Force garbage collection
    gc.collect()
    
    # Timed iterations
    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        result = func()
        end = time.perf_counter()
        times.append((end - start) * 1000)  # Convert to ms
    
    return times, result


def benchmark_function(
    name: str,
    func: Callable[[], Any],
    iterations: int = 100,
    threshold_ms: Optional[float] = None,
    warmup: int = 5,
) -> SingleBenchmark:
    """Benchmark a single function.
    
    Args:
        name: Benchmark name
        func: Function to benchmark
        iterations: Number of iterations
        threshold_ms: Pass/fail threshold in milliseconds
        warmup: Warmup iterations
        
    Returns:
        SingleBenchmark result
    """
    times, _ = run_timed_iterations(func, iterations, warmup)
    
    mean_time = statistics.mean(times)
    std_time = statistics.stdev(times) if len(times) > 1 else 0.0
    
    passed = True
    if threshold_ms is not None:
        passed = mean_time <= threshold_ms
    
    return SingleBenchmark(
        name=name,
        iterations=iterations,
        mean_time_ms=mean_time,
        std_time_ms=std_time,
        min_time_ms=min(times),
        max_time_ms=max(times),
        ops_per_second=1000.0 / mean_time if mean_time > 0 else 0.0,
        passed=passed,
        threshold_ms=threshold_ms,
    )


# =============================================================================
# THESIS-SPECIFIC BENCHMARKS
# =============================================================================

def benchmark_numpy_operations() -> SingleBenchmark:
    """Benchmark NumPy operations typical in simulation."""
    n = 10000
    
    def numpy_ops():
        a = np.random.randn(n)
        b = np.random.randn(n)
        c = a * b + np.sin(a) + np.log(np.abs(b) + 1)
        return np.mean(c)
    
    return benchmark_function(
        name="NumPy Operations (10k elements)",
        func=numpy_ops,
        iterations=100,
        threshold_ms=10.0,  # Should complete in < 10ms
    )


def benchmark_rsrp_calculation() -> SingleBenchmark:
    """Benchmark RSRP calculation typical in handover decisions."""
    
    def rsrp_calc():
        n_ues = 50
        n_cells = 10
        
        # Distance calculation
        ue_positions = np.random.rand(n_ues, 2) * 1000  # 1km x 1km
        cell_positions = np.random.rand(n_cells, 2) * 1000
        
        # Calculate all distances
        distances = np.sqrt(
            np.sum(
                (ue_positions[:, np.newaxis, :] - cell_positions[np.newaxis, :, :]) ** 2,
                axis=2
            )
        )
        
        # Path loss (ABG model)
        alpha, beta, gamma = 3.5, 22.4, 2.0
        path_loss = alpha * 10 * np.log10(distances + 1) + beta + gamma * 10 * np.log10(3.5)
        
        # RSRP
        tx_power = 23.0  # dBm
        rsrp = tx_power - path_loss
        
        return np.argmax(rsrp, axis=1)  # Best cell per UE
    
    return benchmark_function(
        name="RSRP Calculation (50 UEs × 10 cells)",
        func=rsrp_calc,
        iterations=100,
        threshold_ms=5.0,
    )


def benchmark_ml_prediction() -> SingleBenchmark:
    """Benchmark ML model prediction latency."""
    try:
        import lightgbm as lgb
    except ImportError:
        return SingleBenchmark(
            name="ML Model Prediction",
            iterations=0,
            mean_time_ms=0,
            std_time_ms=0,
            min_time_ms=0,
            max_time_ms=0,
            ops_per_second=0,
            passed=False,
            threshold_ms=None,
        )
    
    # Create dummy model
    n_samples = 1000
    n_features = 15
    X = np.random.randn(n_samples, n_features)
    y = np.random.randint(0, 2, n_samples)
    
    train_data = lgb.Dataset(X, label=y)
    params = {
        "objective": "binary",
        "num_leaves": 31,
        "learning_rate": 0.1,
        "verbose": -1,
    }
    model = lgb.train(params, train_data, num_boost_round=10)
    
    # Benchmark single prediction
    single_sample = np.random.randn(1, n_features)
    
    def predict():
        return model.predict(single_sample)
    
    return benchmark_function(
        name="LightGBM Single Prediction",
        func=predict,
        iterations=1000,
        threshold_ms=1.0,  # Should be < 1ms for real-time
    )


def benchmark_ml_batch_prediction() -> SingleBenchmark:
    """Benchmark ML model batch prediction."""
    try:
        import lightgbm as lgb
    except ImportError:
        return SingleBenchmark(
            name="ML Batch Prediction",
            iterations=0,
            mean_time_ms=0,
            std_time_ms=0,
            min_time_ms=0,
            max_time_ms=0,
            ops_per_second=0,
            passed=False,
            threshold_ms=None,
        )
    
    # Create dummy model
    n_samples = 1000
    n_features = 15
    X = np.random.randn(n_samples, n_features)
    y = np.random.randint(0, 2, n_samples)
    
    train_data = lgb.Dataset(X, label=y)
    params = {
        "objective": "binary",
        "num_leaves": 31,
        "learning_rate": 0.1,
        "verbose": -1,
    }
    model = lgb.train(params, train_data, num_boost_round=10)
    
    # Benchmark batch prediction (50 UEs)
    batch_samples = np.random.randn(50, n_features)
    
    def predict_batch():
        return model.predict(batch_samples)
    
    return benchmark_function(
        name="LightGBM Batch Prediction (50 samples)",
        func=predict_batch,
        iterations=100,
        threshold_ms=5.0,
    )


def benchmark_statistical_tests() -> SingleBenchmark:
    """Benchmark statistical tests used in analysis."""
    try:
        from scipy import stats
    except ImportError:
        logger.warning("scipy not installed - skipping statistical tests benchmark")
        return SingleBenchmark(
            name="Statistical Tests (n=100)",
            iterations=0,
            mean_time_ms=0,
            std_time_ms=0,
            min_time_ms=0,
            max_time_ms=0,
            ops_per_second=0,
            passed=False,
            threshold_ms=None,
        )
    
    n = 100  # Sample size per condition
    
    def stat_tests():
        a = np.random.randn(n)
        b = np.random.randn(n) + 0.5  # Slightly shifted
        
        # Paired t-test
        t_stat, t_p = stats.ttest_rel(a, b)
        
        # Wilcoxon
        w_stat, w_p = stats.wilcoxon(a, b)
        
        # Effect size (Cohen's d)
        diff = a - b
        d = np.mean(diff) / np.std(diff)
        
        return t_p, w_p, d
    
    return benchmark_function(
        name="Statistical Tests (n=100)",
        func=stat_tests,
        iterations=100,
        threshold_ms=10.0,
    )


def benchmark_simulation_timestep() -> SingleBenchmark:
    """Benchmark a typical simulation timestep."""
    n_ues = 30
    n_cells = 8
    
    # State
    ue_positions = np.random.rand(n_ues, 2) * 1000
    ue_velocities = np.random.rand(n_ues, 2) * 30
    cell_positions = np.random.rand(n_cells, 2) * 1000
    
    def timestep():
        nonlocal ue_positions
        
        dt = 0.1  # 100ms timestep
        
        # Update positions
        ue_positions = ue_positions + ue_velocities * dt
        
        # Calculate distances
        distances = np.sqrt(
            np.sum(
                (ue_positions[:, np.newaxis, :] - cell_positions[np.newaxis, :, :]) ** 2,
                axis=2
            )
        )
        
        # RSRP calculation
        path_loss = 35.0 * np.log10(distances + 10) + 25.0
        rsrp = 23.0 - path_loss
        
        # Add fading
        shadowing = np.random.randn(n_ues, n_cells) * 8.0
        fading = np.random.exponential(1.0, (n_ues, n_cells))
        
        rsrp_total = rsrp + shadowing + 10 * np.log10(fading + 0.01)
        
        # Determine best cells
        best_cells = np.argmax(rsrp_total, axis=1)
        
        return best_cells
    
    return benchmark_function(
        name="Simulation Timestep (30 UEs × 8 cells)",
        func=timestep,
        iterations=1000,
        threshold_ms=2.0,  # Need < 2ms for 100ms real-time
    )


# =============================================================================
# MAIN BENCHMARK SUITE
# =============================================================================

def run_benchmark_suite(
    output_path: Optional[Path] = None,
) -> BenchmarkSuite:
    """Run complete benchmark suite.
    
    Args:
        output_path: Optional path to save results
        
    Returns:
        BenchmarkSuite with all results
    """
    suite = BenchmarkSuite(
        timestamp=datetime.now().isoformat(),
        system_info=SystemInfo.collect(),
    )
    
    print("Running performance benchmarks...")
    print("-" * 40)
    
    # Run all benchmarks
    benchmarks = [
        benchmark_numpy_operations,
        benchmark_rsrp_calculation,
        benchmark_ml_prediction,
        benchmark_ml_batch_prediction,
        benchmark_statistical_tests,
        benchmark_simulation_timestep,
    ]
    
    for bench_func in benchmarks:
        print(f"  Running {bench_func.__name__}...")
        result = bench_func()
        suite.add(result)
        
        status = "✓" if result.passed else "✗"
        print(f"    {status} {result.mean_time_ms:.2f} ms")
    
    print("-" * 40)
    
    # Save if path provided
    if output_path:
        suite.save(output_path)
    
    return suite


def validate_system_performance(
    min_requirement: str = "standard",
) -> Tuple[bool, str]:
    """Validate system meets minimum performance requirements.
    
    Args:
        min_requirement: 'standard' or 'high'
        
    Returns:
        (passed, message)
    """
    suite = run_benchmark_suite()
    
    # Check all benchmarks passed
    if not suite.overall_passed:
        failed = [b.name for b in suite.benchmarks if not b.passed]
        return False, f"Failed benchmarks: {', '.join(failed)}"
    
    # Additional checks for high performance
    if min_requirement == "high":
        sim_bench = next(
            (b for b in suite.benchmarks if "Timestep" in b.name), None
        )
        if sim_bench and sim_bench.mean_time_ms > 1.0:
            return False, f"Simulation timestep too slow for high-performance: {sim_bench.mean_time_ms:.2f} ms"
    
    return True, "System meets performance requirements"


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    'SystemInfo',
    'SingleBenchmark',
    'BenchmarkSuite',
    'run_benchmark_suite',
    'validate_system_performance',
    'benchmark_function',
    'run_timed_iterations',
]


if __name__ == "__main__":
    # Run benchmarks and print summary
    output = Path("thesis_results") / "benchmarks" / f"benchmark_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    suite = run_benchmark_suite(output_path=output)
    print(suite.summary())
