"""Unit tests for channel model module.

Tests AR1 shadowing, Doppler fading, and RSRP calculations.
"""
import math
import unittest

import numpy as np

# Import paths are configured by conftest.py


class TestChannelModel(unittest.TestCase):
    """Tests for ChannelModel class."""
    
    def setUp(self):
        """Create fresh channel model for each test."""
        from rf_models.channel_model import ChannelModel
        
        # Create with explicit RNG for reproducibility
        self.rng = np.random.RandomState(42)
        self.channel = ChannelModel(
            ue_id="test_ue",
            carrier_frequency_ghz=3.5,
            sigma_sf=4.0,
            decorr_distance_m=37.0,
            rng=self.rng
        )
    
    def test_initial_shadowing_from_distribution(self):
        """First shadowing value should be drawn from N(0, sigma_SF)."""
        from rf_models.channel_model import ChannelModel
        
        # Run many trials to verify distribution
        samples = []
        for i in range(1000):
            rng = np.random.RandomState(i)
            channel = ChannelModel(
                ue_id=f"ue_{i}",
                sigma_sf=4.0,
                rng=rng
            )
            shadow = channel.update_shadowing((0, 0, 0))
            samples.append(shadow)
        
        # Mean should be close to 0
        self.assertAlmostEqual(np.mean(samples), 0.0, delta=0.5)
        # Std should be close to sigma_sf
        self.assertAlmostEqual(np.std(samples), 4.0, delta=0.5)
    
    def test_ar1_correlation_with_distance(self):
        """Shadowing should be correlated over short distances."""
        # Initial position
        shadow1 = self.channel.update_shadowing((0, 0, 0))
        
        # Move a small distance (10m, should be highly correlated)
        shadow2 = self.channel.update_shadowing((10, 0, 0))
        
        # Correlation coefficient: exp(-10/37) ≈ 0.76
        # Second value should be close to first
        self.assertAlmostEqual(shadow2, shadow1, delta=5.0)
    
    def test_ar1_decorrelation_with_large_distance(self):
        """Shadowing should decorrelate over large distances."""
        from rf_models.channel_model import ChannelModel
        
        # Run many trials
        differences = []
        for i in range(100):
            rng = np.random.RandomState(i)
            channel = ChannelModel(ue_id=f"ue_{i}", sigma_sf=4.0, rng=rng)
            
            shadow1 = channel.update_shadowing((0, 0, 0))
            # Move 5x decorrelation distance
            shadow2 = channel.update_shadowing((185, 0, 0))
            differences.append(shadow2 - shadow1)
        
        # After 5x decorr distance, correlation ≈ exp(-5) ≈ 0.007
        # Std of differences should be close to sqrt(2) * sigma_sf
        expected_std = math.sqrt(2) * 4.0
        self.assertAlmostEqual(np.std(differences), expected_std, delta=1.5)
    
    def test_stationary_ue_uses_large_coherence_time(self):
        """Stationary UEs should have 10-second coherence time."""
        from rf_models.channel_model import STATIONARY_COHERENCE_TIME_S
        
        # Update with velocity below threshold
        self.channel.update_fast_fading(velocity_mps=0.05, current_time_s=0.0)
        
        self.assertEqual(
            self.channel.state.coherence_time_s,
            STATIONARY_COHERENCE_TIME_S
        )
    
    def test_moving_ue_doppler_coherence_time(self):
        """Moving UEs should have Doppler-based coherence time."""
        # Update with 30 m/s velocity (highway speed)
        self.channel.update_fast_fading(velocity_mps=30.0, current_time_s=0.0)
        
        # Expected: T_c = 9 / (16π × f_d)
        # f_d = 30 × 3.5e9 / 3e8 = 350 Hz
        # T_c ≈ 9 / (16π × 350) ≈ 0.5 ms
        self.assertLess(self.channel.state.coherence_time_s, 0.01)
    
    def test_fading_regenerates_after_coherence_time(self):
        """Fading coefficient should regenerate after coherence time."""
        from rf_models.channel_model import ChannelModel
        
        rng = np.random.RandomState(42)
        channel = ChannelModel(ue_id="test", rng=rng)
        
        # First update
        fading1 = channel.update_fast_fading(velocity_mps=30.0, current_time_s=0.0)
        
        # Update after long time (10 seconds)
        fading2 = channel.update_fast_fading(velocity_mps=30.0, current_time_s=10.0)
        
        # Should have different fading
        self.assertNotEqual(fading1, fading2)
    
    def test_get_total_channel_loss_sign_convention(self):
        """Total channel loss should use correct sign convention."""
        # Set known shadowing
        self.channel.update_shadowing((0, 0, 0))
        
        path_loss = 100.0  # dB
        total_loss = self.channel.get_total_channel_loss(path_loss, include_fading=False)
        
        # Total should be path_loss + shadowing
        expected = path_loss + self.channel.state.shadowing_db
        self.assertAlmostEqual(total_loss, expected, places=3)
    
    def test_fading_mean_compensation(self):
        """Fading loss should be approximately 0 dB on average."""
        from rf_models.channel_model import ChannelModel
        
        fading_samples = []
        for i in range(1000):
            rng = np.random.RandomState(i)
            channel = ChannelModel(ue_id=f"ue_{i}", rng=rng)
            channel._generate_new_fading()
            fading_samples.append(channel.get_fading_loss())
        
        # Mean should be close to 0 dB
        self.assertAlmostEqual(np.mean(fading_samples), 0.0, delta=0.5)


class TestChannelModelManager(unittest.TestCase):
    """Tests for ChannelModelManager class."""
    
    def setUp(self):
        """Create fresh manager for each test."""
        from rf_models.channel_model import ChannelModelManager
        self.manager = ChannelModelManager()
    
    def test_get_channel_creates_new(self):
        """get_channel should create a new channel model for unknown UE."""
        channel = self.manager.get_channel("new_ue")
        self.assertIsNotNone(channel)
    
    def test_get_channel_returns_same_instance(self):
        """get_channel should return same instance for same UE ID."""
        channel1 = self.manager.get_channel("ue001")
        channel2 = self.manager.get_channel("ue001")
        self.assertIs(channel1, channel2)
    
    def test_update_ue_returns_shadowing_and_fading(self):
        """update_ue should return tuple of (shadowing, fading)."""
        result = self.manager.update_ue(
            ue_id="ue001",
            position=(100, 200, 1.5),
            velocity_mps=10.0,
            current_time_s=0.0
        )
        
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        shadowing, fading = result
        self.assertIsInstance(shadowing, float)
        self.assertIsInstance(fading, float)
    
    def test_remove_ue(self):
        """remove_ue should delete the channel model."""
        self.manager.get_channel("ue001")
        self.manager.remove_ue("ue001")
        
        # Getting again should create a new instance
        channel = self.manager.get_channel("ue001")
        self.assertFalse(channel.state.is_initialized)
    
    def test_get_stats_returns_shadowing_statistics(self):
        """get_stats should return shadowing statistics."""
        # Add some channels
        for i in range(10):
            channel = self.manager.get_channel(f"ue_{i}")
            channel.update_shadowing((i * 100, 0, 0))
        
        stats = self.manager.get_stats()
        
        self.assertEqual(stats["count"], 10)
        self.assertIn("shadowing_mean", stats)
        self.assertIn("shadowing_std", stats)


class TestChannelModelConstants(unittest.TestCase):
    """Test that constants are properly defined."""
    
    def test_constants_exist(self):
        """Required constants should be defined."""
        from rf_models.channel_model import (
            MIN_VELOCITY_THRESHOLD_MPS,
            STATIONARY_COHERENCE_TIME_S,
            SPEED_OF_LIGHT_MPS,
            EPSILON,
            RAYLEIGH_MEAN_COMPENSATION_DB,
        )
        
        self.assertEqual(MIN_VELOCITY_THRESHOLD_MPS, 0.1)
        self.assertEqual(STATIONARY_COHERENCE_TIME_S, 10.0)
        self.assertEqual(SPEED_OF_LIGHT_MPS, 3e8)
        self.assertEqual(EPSILON, 1e-10)
        # Exact value from Euler-Mascheroni constant: 10 * 0.5772156649 / ln(10)
        self.assertAlmostEqual(RAYLEIGH_MEAN_COMPENSATION_DB, 2.5066, places=4)


if __name__ == "__main__":
    unittest.main()
