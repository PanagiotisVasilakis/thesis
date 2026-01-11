"""Optimization utilities for the ML service.

This package provides performance optimizations:
- warmup: Model warm-up for reducing cold-start latency
- fast_scaler: Pre-computed scaling for faster feature normalization
"""

from .warmup import (
    warm_up_model,
    warm_up_all_models,
    generate_synthetic_features,
    ModelWarmer,
)
from .fast_scaler import FastScaler

__all__ = [
    "warm_up_model",
    "warm_up_all_models",
    "generate_synthetic_features",
    "ModelWarmer",
    "FastScaler",
]
