"""Unit tests for sample collector module.

Tests sample collection, pairing, and validation.
"""
import unittest

import numpy as np

# Import paths are configured by conftest.py


class TestExperimentResult(unittest.TestCase):
    """Tests for ExperimentResult dataclass."""
    
    def setUp(self):
        """Import the class under test."""
        from scripts.analysis.sample_collector import ExperimentResult
        self.ExperimentResult = ExperimentResult
    
    def test_create_result(self):
        """Should create ExperimentResult with all fields."""
        result = self.ExperimentResult(
            seed=42,
            algorithm="ml",
            scenario="highway",
            metrics={"handover_count": 15, "pingpong_rate": 0.1}
        )
        
        self.assertEqual(result.seed, 42)
        self.assertEqual(result.algorithm, "ml")
        self.assertEqual(result.scenario, "highway")
        self.assertEqual(result.get_metric("handover_count"), 15)
    
    def test_to_dict_and_from_dict(self):
        """Should serialize and deserialize correctly."""
        original = self.ExperimentResult(
            seed=42,
            algorithm="a3",
            scenario="urban",
            metrics={"rlf_count": 2}
        )
        
        as_dict = original.to_dict()
        restored = self.ExperimentResult.from_dict(as_dict)
        
        self.assertEqual(original.seed, restored.seed)
        self.assertEqual(original.algorithm, restored.algorithm)
        self.assertEqual(original.metrics, restored.metrics)


class TestSampleCollector(unittest.TestCase):
    """Tests for SampleCollector class."""
    
    def setUp(self):
        """Import the class under test."""
        from scripts.analysis.sample_collector import SampleCollector, ExperimentResult
        self.SampleCollector = SampleCollector
        self.ExperimentResult = ExperimentResult
    
    def test_add_ml_result(self):
        """Should add ML result correctly."""
        collector = self.SampleCollector(scenario="highway")
        collector.add_ml_result(seed=42, metrics={"handover_count": 10})
        
        self.assertEqual(len(collector.ml_results), 1)
        self.assertIn(42, collector.ml_results)
    
    def test_add_a3_result(self):
        """Should add A3 result correctly."""
        collector = self.SampleCollector(scenario="highway")
        collector.add_a3_result(seed=42, metrics={"handover_count": 15})
        
        self.assertEqual(len(collector.a3_results), 1)
        self.assertIn(42, collector.a3_results)
    
    def test_get_paired_seeds(self):
        """Should return seeds with both ML and A3 results."""
        collector = self.SampleCollector(scenario="highway")
        
        collector.add_ml_result(seed=1, metrics={})
        collector.add_ml_result(seed=2, metrics={})
        collector.add_ml_result(seed=3, metrics={})
        
        collector.add_a3_result(seed=2, metrics={})
        collector.add_a3_result(seed=3, metrics={})
        collector.add_a3_result(seed=4, metrics={})
        
        paired = collector.get_paired_seeds()
        self.assertEqual(paired, [2, 3])
    
    def test_get_unpaired_seeds(self):
        """Should identify seeds missing a pair."""
        collector = self.SampleCollector(scenario="highway")
        
        collector.add_ml_result(seed=1, metrics={})
        collector.add_ml_result(seed=2, metrics={})
        
        collector.add_a3_result(seed=2, metrics={})
        collector.add_a3_result(seed=3, metrics={})
        
        unpaired = collector.get_unpaired_seeds()
        self.assertEqual(unpaired["ml_only"], [1])
        self.assertEqual(unpaired["a3_only"], [3])
    
    def test_get_paired_samples(self):
        """Should return PairedSamples with matched data."""
        collector = self.SampleCollector(scenario="highway")
        
        for seed in [1, 2, 3]:
            collector.add_ml_result(
                seed=seed,
                metrics={"handover_count": seed * 2}
            )
            collector.add_a3_result(
                seed=seed,
                metrics={"handover_count": seed * 3}
            )
        
        paired = collector.get_paired_samples(metrics=["handover_count"])
        
        self.assertEqual(paired.n_pairs, 3)
        self.assertEqual(len(paired.ml_values["handover_count"]), 3)
        self.assertEqual(len(paired.a3_values["handover_count"]), 3)
    
    def test_duplicate_warning(self):
        """Should warn about duplicate results."""
        collector = self.SampleCollector(scenario="highway")
        
        collector.add_ml_result(seed=42, metrics={})
        collector.add_ml_result(seed=42, metrics={})  # Duplicate
        
        status = collector.get_collection_status()
        self.assertGreater(len(status["warnings"]), 0)


class TestPairedSamples(unittest.TestCase):
    """Tests for PairedSamples dataclass."""
    
    def setUp(self):
        """Import the class under test."""
        from scripts.analysis.sample_collector import PairedSamples
        self.PairedSamples = PairedSamples
    
    def test_get_differences(self):
        """Should calculate differences correctly."""
        paired = self.PairedSamples(
            scenario="test",
            seeds=[1, 2, 3],
            ml_values={"metric": np.array([10, 20, 30])},
            a3_values={"metric": np.array([15, 25, 35])}
        )
        
        diff = paired.get_differences("metric")
        
        np.testing.assert_array_equal(diff, np.array([-5, -5, -5]))
    
    def test_is_valid_for_analysis_insufficient_pairs(self):
        """Should fail validation with too few pairs."""
        paired = self.PairedSamples(
            scenario="test",
            seeds=[1, 2],  # Only 2 pairs
            ml_values={"metric": np.array([10, 20])},
            a3_values={"metric": np.array([15, 25])}
        )
        
        is_valid, msg = paired.is_valid_for_analysis()
        self.assertFalse(is_valid)
        self.assertIn("Insufficient", msg)
    
    def test_is_valid_for_analysis_nan_detection(self):
        """Should fail validation when NaN present."""
        paired = self.PairedSamples(
            scenario="test",
            seeds=list(range(15)),
            ml_values={"metric": np.array([float('nan')] + [1.0] * 14)},
            a3_values={"metric": np.ones(15)}
        )
        
        is_valid, msg = paired.is_valid_for_analysis()
        self.assertFalse(is_valid)
        self.assertIn("NaN", msg)
    
    def test_serialization(self):
        """Should serialize and deserialize correctly."""
        original = self.PairedSamples(
            scenario="highway",
            seeds=[1, 2, 3],
            ml_values={"metric": np.array([10, 20, 30])},
            a3_values={"metric": np.array([15, 25, 35])}
        )
        
        as_dict = original.to_dict()
        restored = self.PairedSamples.from_dict(as_dict)
        
        self.assertEqual(original.scenario, restored.scenario)
        self.assertEqual(original.seeds, restored.seeds)
        np.testing.assert_array_equal(
            original.ml_values["metric"],
            restored.ml_values["metric"]
        )


class TestSampleValidation(unittest.TestCase):
    """Tests for sample validation function."""
    
    def setUp(self):
        """Import the function under test."""
        from scripts.analysis.sample_collector import (
            validate_samples, PairedSamples, MIN_SAMPLE_SIZE
        )
        self.validate_samples = validate_samples
        self.PairedSamples = PairedSamples
        self.MIN_SAMPLE_SIZE = MIN_SAMPLE_SIZE
    
    def test_valid_samples_pass(self):
        """Valid samples should pass validation."""
        n = 30
        paired = self.PairedSamples(
            scenario="test",
            seeds=list(range(n)),
            ml_values={"metric": np.random.normal(10, 2, n)},
            a3_values={"metric": np.random.normal(15, 2, n)}
        )
        
        result = self.validate_samples(paired)
        self.assertTrue(result.is_valid)
    
    def test_power_analysis_included(self):
        """Validation should include power analysis."""
        n = 30
        paired = self.PairedSamples(
            scenario="test",
            seeds=list(range(n)),
            ml_values={"metric": np.random.normal(10, 2, n)},
            a3_values={"metric": np.random.normal(15, 2, n)}
        )
        
        result = self.validate_samples(paired)
        self.assertIn("metric", result.power_analysis)
    
    def test_outlier_detection(self):
        """Validation should detect outliers."""
        n = 30
        ml = np.random.normal(10, 1, n)
        a3 = np.random.normal(15, 1, n)
        
        # Add outlier
        ml[0] = 100  # Extreme outlier
        
        paired = self.PairedSamples(
            scenario="test",
            seeds=list(range(n)),
            ml_values={"metric": ml},
            a3_values={"metric": a3}
        )
        
        result = self.validate_samples(paired)
        self.assertIn("metric", result.outlier_info)


class TestRequiredSampleSize(unittest.TestCase):
    """Tests for sample size calculation."""
    
    def setUp(self):
        """Import the function under test."""
        from scripts.analysis.sample_collector import calculate_required_sample_size
        self.calculate_required_sample_size = calculate_required_sample_size
    
    def test_larger_effect_needs_fewer_samples(self):
        """Larger effect size should require fewer samples."""
        n_large_effect = self.calculate_required_sample_size(effect_size=0.8)
        n_small_effect = self.calculate_required_sample_size(effect_size=0.3)
        
        self.assertLess(n_large_effect, n_small_effect)
    
    def test_higher_power_needs_more_samples(self):
        """Higher power should require more samples."""
        n_low_power = self.calculate_required_sample_size(power=0.7)
        n_high_power = self.calculate_required_sample_size(power=0.9)
        
        self.assertLess(n_low_power, n_high_power)
    
    def test_medium_effect_standard_values(self):
        """Medium effect (d=0.5) at 80% power should need ~34 pairs."""
        n = self.calculate_required_sample_size(effect_size=0.5, power=0.8)
        
        # Standard result is approximately 34 for paired t-test
        self.assertGreater(n, 25)
        self.assertLess(n, 45)


if __name__ == "__main__":
    unittest.main()
