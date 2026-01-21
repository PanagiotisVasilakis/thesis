"""Unit tests for reproducibility module.

Tests thread safety, seed propagation, and UE RNG caching.
"""
import os
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np


class TestReproducibility(unittest.TestCase):
    """Tests for reproducibility utilities."""
    
    def setUp(self):
        """Reset state before each test."""
        # Import here to get fresh module state
        from scripts.core.reproducibility import clear_all_ue_rngs, setup_reproducibility
        clear_all_ue_rngs()
        # Clear environment
        if "EXPERIMENT_SEED" in os.environ:
            del os.environ["EXPERIMENT_SEED"]
    
    def test_setup_reproducibility_returns_seed(self):
        """setup_reproducibility should return the seed used."""
        from scripts.core.reproducibility import setup_reproducibility
        
        result = setup_reproducibility(seed=42)
        self.assertEqual(result, 42)
    
    def test_setup_reproducibility_default_seed(self):
        """setup_reproducibility should default to 42 when no seed given."""
        from scripts.core.reproducibility import setup_reproducibility
        
        result = setup_reproducibility()
        self.assertEqual(result, 42)
    
    def test_setup_reproducibility_from_env(self):
        """setup_reproducibility should read from EXPERIMENT_SEED env var."""
        from scripts.core.reproducibility import setup_reproducibility
        
        os.environ["EXPERIMENT_SEED"] = "123"
        result = setup_reproducibility()
        self.assertEqual(result, 123)
    
    def test_numpy_reproducibility(self):
        """NumPy sequences should be identical with same seed."""
        from scripts.core.reproducibility import setup_reproducibility
        
        setup_reproducibility(seed=42)
        seq1 = [np.random.random() for _ in range(10)]
        
        setup_reproducibility(seed=42)
        seq2 = [np.random.random() for _ in range(10)]
        
        self.assertEqual(seq1, seq2)
    
    def test_ue_rng_deterministic(self):
        """UE RNGs should be deterministic based on UE ID and seed."""
        from scripts.core.reproducibility import get_rng_for_ue, clear_all_ue_rngs
        
        clear_all_ue_rngs()
        rng1 = get_rng_for_ue("ue001", base_seed=42)
        seq1 = [rng1.random() for _ in range(5)]
        
        clear_all_ue_rngs()
        rng2 = get_rng_for_ue("ue001", base_seed=42)
        seq2 = [rng2.random() for _ in range(5)]
        
        self.assertEqual(seq1, seq2)
    
    def test_different_ues_get_different_rngs(self):
        """Different UE IDs should produce different RNG sequences."""
        from scripts.core.reproducibility import get_rng_for_ue, clear_all_ue_rngs
        
        clear_all_ue_rngs()
        rng1 = get_rng_for_ue("ue001", base_seed=42)
        rng2 = get_rng_for_ue("ue002", base_seed=42)
        
        seq1 = [rng1.random() for _ in range(5)]
        seq2 = [rng2.random() for _ in range(5)]
        
        self.assertNotEqual(seq1, seq2)
    
    def test_ue_rng_caching(self):
        """Requesting same UE RNG twice should return same object."""
        from scripts.core.reproducibility import get_rng_for_ue, clear_all_ue_rngs
        
        clear_all_ue_rngs()
        rng1 = get_rng_for_ue("ue001", base_seed=42)
        rng2 = get_rng_for_ue("ue001", base_seed=42)
        
        self.assertIs(rng1, rng2)
    
    def test_clear_ue_rng(self):
        """clear_ue_rng should remove cached RNG for specific UE."""
        from scripts.core.reproducibility import (
            get_rng_for_ue, clear_ue_rng, clear_all_ue_rngs, get_reproducibility_state
        )
        
        clear_all_ue_rngs()
        get_rng_for_ue("ue001", base_seed=42)
        get_rng_for_ue("ue002", base_seed=42)
        
        self.assertEqual(get_reproducibility_state()["ue_count"], 2)
        
        clear_ue_rng("ue001")
        self.assertEqual(get_reproducibility_state()["ue_count"], 1)
    
    def test_verify_reproducibility(self):
        """verify_reproducibility should return True for working system."""
        from scripts.core.reproducibility import verify_reproducibility
        
        result = verify_reproducibility(seed=42)
        self.assertTrue(result)
    
    def test_thread_safety_concurrent_ue_creation(self):
        """Multiple threads creating UE RNGs should not cause race conditions."""
        from scripts.core.reproducibility import (
            get_rng_for_ue, clear_all_ue_rngs, setup_reproducibility, get_reproducibility_state
        )
        
        setup_reproducibility(seed=42)
        clear_all_ue_rngs()
        
        n_threads = 10
        n_ues_per_thread = 50
        errors = []
        
        def create_ue_rngs(thread_id):
            try:
                for i in range(n_ues_per_thread):
                    ue_id = f"ue_t{thread_id}_{i}"
                    rng = get_rng_for_ue(ue_id, base_seed=42)
                    # Consume some random numbers
                    _ = [rng.random() for _ in range(5)]
            except Exception as e:
                errors.append(str(e))
        
        threads = []
        for i in range(n_threads):
            t = threading.Thread(target=create_ue_rngs, args=(i,))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        self.assertEqual(errors, [])
        # Should have all UEs created
        state = get_reproducibility_state()
        self.assertEqual(state["ue_count"], n_threads * n_ues_per_thread)
    
    def test_get_experiment_seed_returns_configured(self):
        """get_experiment_seed should return seed from setup_reproducibility."""
        from scripts.core.reproducibility import setup_reproducibility, get_experiment_seed
        
        setup_reproducibility(seed=999)
        self.assertEqual(get_experiment_seed(), 999)


class TestReproducibilityEdgeCases(unittest.TestCase):
    """Edge case tests for reproducibility module."""
    
    def test_invalid_env_seed_uses_default(self):
        """Invalid EXPERIMENT_SEED should fall back to 42."""
        from scripts.core.reproducibility import setup_reproducibility, clear_all_ue_rngs
        
        clear_all_ue_rngs()
        os.environ["EXPERIMENT_SEED"] = "not_a_number"
        result = setup_reproducibility()
        self.assertEqual(result, 42)
    
    def test_seed_zero(self):
        """Seed 0 should be handled (some systems treat 0 specially)."""
        from scripts.core.reproducibility import setup_reproducibility, clear_all_ue_rngs
        
        clear_all_ue_rngs()
        result = setup_reproducibility(seed=0)
        self.assertEqual(result, 0)
        
        # Verify sequences are reproducible with seed 0
        seq1 = [np.random.random() for _ in range(5)]
        setup_reproducibility(seed=0)
        seq2 = [np.random.random() for _ in range(5)]
        self.assertEqual(seq1, seq2)
    
    def test_large_seed(self):
        """Large seed values should be handled."""
        from scripts.core.reproducibility import setup_reproducibility
        
        large_seed = 2**31 - 1
        result = setup_reproducibility(seed=large_seed)
        self.assertEqual(result, large_seed)


if __name__ == "__main__":
    unittest.main()
