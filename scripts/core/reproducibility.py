"""Reproducibility utilities for experiment determinism.

This module implements Fix #1 from the thesis implementation plan:
Random Seed Propagation Strategy.

The random seed must be set in FOUR places to ensure true reproducibility:
1. NumPy's global generator - Used by channel model calculations
2. Python's random module - Used by any list shuffling or random.choice calls
3. LightGBM's internal RNG - Used during model training/prediction (via seed param)
4. Channel model instance RNG - Maintains separate state for each UE

This is the SHARED version that can be imported from either:
- scripts.core.reproducibility (for standalone scripts)
- app.core.reproducibility (within nef-emulator service)

Usage:
    from scripts.core.reproducibility import setup_reproducibility, get_rng_for_ue
    
    # At experiment start
    setup_reproducibility(seed=42)
    
    # For per-UE channel model RNG
    ue_rng = get_rng_for_ue(ue_id="ue001", base_seed=42)
"""

from __future__ import annotations

import hashlib
import logging
import os
import random
import threading
from typing import Dict, Optional

import numpy as np

logger = logging.getLogger(__name__)

# Thread-safe lock for reproducibility state access
_state_lock = threading.RLock()

# Global state for tracking reproducibility setup
# Protected by _state_lock for thread safety
_reproducibility_state: Dict[str, object] = {
    "initialized": False,
    "seed": None,
    "ue_rngs": {},  # Per-UE RandomState objects for channel models
}


def setup_reproducibility(seed: Optional[int] = None) -> int:
    """Initialize all random number generators for reproducibility.
    
    Thread-safe: Uses lock to protect global state.
    
    This function propagates the seed to:
    1. NumPy's global generator
    2. Python's random module
    3. Environment variable for LightGBM (ML_RANDOM_SEED)
    
    Args:
        seed: The random seed to use. If None, reads from EXPERIMENT_SEED env var,
              defaults to 42 if not set.
              
    Returns:
        The seed that was used.
        
    Note:
        For LightGBM, the seed is passed as a parameter during model creation.
        This function sets the ML_RANDOM_SEED env var which the ML service reads.
    """
    if seed is None:
        seed_env = os.getenv("EXPERIMENT_SEED", "42")
        try:
            seed = int(seed_env)
        except ValueError:
            logger.warning(
                "Invalid EXPERIMENT_SEED '%s', using default 42", seed_env
            )
            seed = 42
    
    # 1. NumPy global generator
    np.random.seed(seed)
    logger.info("NumPy random seed set to %d", seed)
    
    # 2. Python's random module
    random.seed(seed)
    logger.info("Python random seed set to %d", seed)
    
    # 3. Set environment variable for LightGBM (read by ML service)
    os.environ["ML_RANDOM_SEED"] = str(seed)
    logger.info("ML_RANDOM_SEED environment variable set to %d", seed)
    
    # 4. Clear any existing per-UE RNGs (they'll be recreated with new seed)
    # Thread-safe state update
    with _state_lock:
        _reproducibility_state["ue_rngs"].clear()
        _reproducibility_state["initialized"] = True
        _reproducibility_state["seed"] = seed
    
    logger.info(
        "Reproducibility setup complete with seed=%d. "
        "Run same experiment twice to verify bit-for-bit identical results.",
        seed
    )
    
    return seed


def get_rng_for_ue(ue_id: str, base_seed: Optional[int] = None) -> np.random.RandomState:
    """Get a dedicated RandomState for a specific UE's channel model.
    
    Thread-safe: Uses lock to protect cache access.
    
    Each UE gets its own independent RNG to avoid global state contamination.
    The RNG is deterministically derived from the base seed and UE ID,
    ensuring reproducibility while maintaining per-UE independence.
    
    Args:
        ue_id: The unique identifier for the UE
        base_seed: Base seed to derive from. If None, uses the seed from
                   setup_reproducibility() or EXPERIMENT_SEED env var.
                   
    Returns:
        A numpy RandomState object for this UE's channel calculations.
        
    Example:
        >>> rng = get_rng_for_ue("ue001", base_seed=42)
        >>> shadowing = rng.normal(0, 4)  # 4 dB std dev
    """
    # Determine base seed
    if base_seed is None:
        with _state_lock:
            if _reproducibility_state["seed"] is not None:
                base_seed = _reproducibility_state["seed"]
        
        if base_seed is None:
            seed_env = os.getenv("EXPERIMENT_SEED", "42")
            try:
                base_seed = int(seed_env)
            except ValueError:
                base_seed = 42
    
    cache_key = f"{ue_id}_{base_seed}"
    
    # Thread-safe cache lookup and creation
    with _state_lock:
        if cache_key in _reproducibility_state["ue_rngs"]:
            return _reproducibility_state["ue_rngs"][cache_key]
        
        # Derive a unique seed for this UE using hash
        # This ensures different UEs get different but deterministic sequences
        hash_input = f"{base_seed}_{ue_id}".encode()
        ue_seed = int(hashlib.sha256(hash_input).hexdigest()[:8], 16)
        
        # Create and cache the RandomState
        rng = np.random.RandomState(ue_seed)
        _reproducibility_state["ue_rngs"][cache_key] = rng
        
        logger.debug(
            "Created RandomState for UE %s with derived seed %d (base=%d)",
            ue_id, ue_seed, base_seed
        )
    
    return rng


def clear_ue_rng(ue_id: str) -> None:
    """Clear the cached RNG for a specific UE.
    
    Thread-safe: Uses lock to protect cache modification.
    
    Call this when a UE is removed from simulation to free memory.
    """
    with _state_lock:
        keys_to_remove = [
            k for k in _reproducibility_state["ue_rngs"] 
            if k.startswith(f"{ue_id}_")
        ]
        for key in keys_to_remove:
            del _reproducibility_state["ue_rngs"][key]


def clear_all_ue_rngs() -> None:
    """Clear all cached UE RNGs.
    
    Thread-safe: Uses lock to protect cache modification.
    
    Call this when resetting the simulation topology.
    """
    with _state_lock:
        _reproducibility_state["ue_rngs"].clear()
    logger.debug("Cleared all UE-specific RNGs")


def get_reproducibility_state() -> Dict[str, object]:
    """Get current reproducibility state for debugging/validation.
    
    Thread-safe: Returns a copy of the state.
    
    Returns:
        Dict with 'initialized', 'seed', and 'ue_count' keys.
    """
    with _state_lock:
        return {
            "initialized": _reproducibility_state["initialized"],
            "seed": _reproducibility_state["seed"],
            "ue_count": len(_reproducibility_state["ue_rngs"]),
        }


def verify_reproducibility(seed: int = 42, n_samples: int = 10) -> bool:
    """Verify that reproducibility is working correctly.
    
    This runs a quick test to ensure seeds are properly propagated.
    
    Args:
        seed: Seed to test with
        n_samples: Number of samples to generate for comparison
        
    Returns:
        True if reproducibility is verified, False otherwise.
    """
    # First run
    setup_reproducibility(seed)
    numpy_samples_1 = [np.random.random() for _ in range(n_samples)]
    python_samples_1 = [random.random() for _ in range(n_samples)]
    
    # Create fresh RNG for UE test (not from cache)
    clear_all_ue_rngs()
    ue_rng_1 = get_rng_for_ue("test_ue", seed)
    ue_samples_1 = [ue_rng_1.random() for _ in range(n_samples)]
    
    # Reset and second run
    setup_reproducibility(seed)
    numpy_samples_2 = [np.random.random() for _ in range(n_samples)]
    python_samples_2 = [random.random() for _ in range(n_samples)]
    
    # Create fresh RNG again (cache was cleared by setup_reproducibility)
    ue_rng_2 = get_rng_for_ue("test_ue", seed)
    ue_samples_2 = [ue_rng_2.random() for _ in range(n_samples)]
    
    # Verify
    numpy_match = numpy_samples_1 == numpy_samples_2
    python_match = python_samples_1 == python_samples_2
    ue_match = ue_samples_1 == ue_samples_2
    
    if numpy_match and python_match and ue_match:
        logger.info("✓ Reproducibility verified: all RNG sequences match")
        return True
    else:
        logger.error(
            "✗ Reproducibility FAILED: numpy=%s, python=%s, ue_rng=%s",
            numpy_match, python_match, ue_match
        )
        return False


def get_experiment_seed() -> int:
    """Get the current experiment seed.
    
    Thread-safe: Uses lock to read state.
    
    Returns the seed from setup_reproducibility() if called,
    otherwise reads from EXPERIMENT_SEED env var (default 42).
    """
    with _state_lock:
        if _reproducibility_state["seed"] is not None:
            return _reproducibility_state["seed"]
    
    seed_env = os.getenv("EXPERIMENT_SEED", "42")
    try:
        return int(seed_env)
    except ValueError:
        return 42
