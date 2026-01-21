"""Unit tests for statistical analysis module.

Tests Cohen's d_z, bootstrap CI, paired comparisons, and Bonferroni correction.
"""
import unittest

import numpy as np

# Import paths are configured by conftest.py


class TestCohensD(unittest.TestCase):
    """Tests for Cohen's d_z calculation."""
    
    def setUp(self):
        """Import the function under test."""
        from scripts.analysis.statistical_analysis import calculate_cohens_d_z
        self.calculate_cohens_d_z = calculate_cohens_d_z
    
    def test_zero_effect_size(self):
        """d_z should be 0 when differences are all zero."""
        differences = np.array([0.0, 0.0, 0.0, 0.0, 0.0])
        d_z, interpretation = self.calculate_cohens_d_z(differences)
        
        self.assertEqual(d_z, 0.0)
        self.assertEqual(interpretation, "negligible")
    
    def test_large_effect_size(self):
        """d_z should be large when mean >> std."""
        differences = np.array([10.0, 10.1, 9.9, 10.0, 10.0])
        d_z, interpretation = self.calculate_cohens_d_z(differences)
        
        self.assertGreater(abs(d_z), 1.2)
        self.assertEqual(interpretation, "very large")
    
    def test_small_effect_size(self):
        """d_z should be small when mean is small relative to std."""
        differences = np.array([0.1, -0.2, 0.15, -0.1, 0.05])
        d_z, interpretation = self.calculate_cohens_d_z(differences)
        
        self.assertLess(abs(d_z), 0.5)
    
    def test_empty_array_returns_zero(self):
        """Empty array should return 0 with negligible interpretation."""
        differences = np.array([])
        d_z, interpretation = self.calculate_cohens_d_z(differences)
        
        self.assertEqual(d_z, 0.0)
        self.assertEqual(interpretation, "negligible")
    
    def test_single_element_handled(self):
        """Single element should be handled without error."""
        differences = np.array([5.0])
        d_z, interpretation = self.calculate_cohens_d_z(differences)
        
        # With single element, we can't estimate variance
        # Function should handle this gracefully
        self.assertIn("n=1", interpretation)


class TestBootstrapCI(unittest.TestCase):
    """Tests for bootstrap confidence interval calculation."""
    
    def setUp(self):
        """Import the function under test."""
        from scripts.analysis.statistical_analysis import bootstrap_ci
        self.bootstrap_ci = bootstrap_ci
    
    def test_ci_contains_true_value(self):
        """CI should contain the true improvement for large samples."""
        np.random.seed(42)
        n = 100
        
        # A3 values
        a3 = np.random.normal(10.0, 2.0, n)
        # ML values (5% improvement on average)
        ml = a3 * 0.95 + np.random.normal(0, 0.5, n)
        
        lower, upper = self.bootstrap_ci(a3, ml, seed=42)
        
        # True improvement is about 5%
        self.assertLess(lower, 5.0)
        self.assertGreater(upper, 5.0)
    
    def test_ci_respects_seed(self):
        """Same seed should produce same CI."""
        a3 = np.array([10, 11, 12, 13, 14])
        ml = np.array([9, 10, 11, 12, 13])
        
        ci1 = self.bootstrap_ci(a3, ml, seed=42)
        ci2 = self.bootstrap_ci(a3, ml, seed=42)
        
        self.assertEqual(ci1, ci2)
    
    def test_empty_arrays_return_zeros(self):
        """Empty arrays should return (0, 0)."""
        lower, upper = self.bootstrap_ci(np.array([]), np.array([]))
        
        self.assertEqual(lower, 0.0)
        self.assertEqual(upper, 0.0)


class TestPairedComparison(unittest.TestCase):
    """Tests for paired comparison function."""
    
    def setUp(self):
        """Import the function under test."""
        from scripts.analysis.statistical_analysis import run_paired_comparison
        self.run_paired_comparison = run_paired_comparison
    
    def test_result_contains_all_fields(self):
        """Result should contain all expected fields."""
        a3 = np.array([10, 11, 12, 13, 14, 15, 16, 17, 18, 19])
        ml = np.array([9, 10, 11, 12, 13, 14, 15, 16, 17, 18])
        
        result = self.run_paired_comparison(
            a3_values=a3,
            ml_values=ml,
            metric_name="test_metric"
        )
        
        self.assertEqual(result.metric_name, "test_metric")
        self.assertIsNotNone(result.a3_mean)
        self.assertIsNotNone(result.ml_mean)
        self.assertIsNotNone(result.p_value_raw)
        self.assertIsNotNone(result.cohens_d_z)
        self.assertIsNotNone(result.is_significant)
    
    def test_significant_difference_detected(self):
        """Large consistent difference should be significant."""
        np.random.seed(42)
        n = 50
        
        a3 = np.random.normal(100, 5, n)
        ml = a3 - 20  # 20 units improvement
        
        result = self.run_paired_comparison(a3, ml, "test")
        
        self.assertTrue(result.is_significant)
        self.assertLess(result.p_value_raw, 0.05)
    
    def test_no_difference_not_significant(self):
        """When groups are similar, should not be significant."""
        np.random.seed(42)
        n = 30
        
        a3 = np.random.normal(100, 10, n)
        ml = np.random.normal(100, 10, n)  # Same distribution
        
        result = self.run_paired_comparison(a3, ml, "test")
        
        # Not necessarily always true, but with high probability
        self.assertGreater(result.p_value_raw, 0.01)


class TestBonferroniCorrection(unittest.TestCase):
    """Tests for Bonferroni correction."""
    
    def setUp(self):
        """Import the function under test."""
        from scripts.analysis.statistical_analysis import apply_bonferroni_correction_scalar
        self.apply_bonferroni_correction = apply_bonferroni_correction_scalar
    
    def test_correction_multiplies_p_value(self):
        """Bonferroni should multiply p-value by number of comparisons."""
        corrected = self.apply_bonferroni_correction(0.01, n_comparisons=5)
        self.assertEqual(corrected, 0.05)
    
    def test_correction_caps_at_one(self):
        """Corrected p-value should not exceed 1.0."""
        corrected = self.apply_bonferroni_correction(0.5, n_comparisons=5)
        self.assertEqual(corrected, 1.0)
    
    def test_single_comparison_unchanged(self):
        """Single comparison should not change p-value."""
        corrected = self.apply_bonferroni_correction(0.03, n_comparisons=1)
        self.assertEqual(corrected, 0.03)


class TestMultipleComparisons(unittest.TestCase):
    """Tests for running multiple comparisons."""
    
    def setUp(self):
        """Import the function under test."""
        from scripts.analysis.statistical_analysis import run_multi_metric_comparison
        self.run_multiple_comparisons = run_multi_metric_comparison
    
    def test_runs_comparison_for_each_metric(self):
        """Should run comparison for each common metric."""
        np.random.seed(42)
        n = 20
        
        a3_results = {
            "metric1": np.random.normal(100, 5, n),
            "metric2": np.random.normal(50, 3, n),
        }
        ml_results = {
            "metric1": np.random.normal(95, 5, n),
            "metric2": np.random.normal(48, 3, n),
        }
        
        results = self.run_multiple_comparisons(a3_results, ml_results)
        
        self.assertEqual(len(results), 2)
        self.assertIn("metric1", results)
        self.assertIn("metric2", results)
    
    def test_applies_bonferroni_to_all(self):
        """Should apply Bonferroni correction to all comparisons."""
        np.random.seed(42)
        n = 20
        
        a3_results = {
            "metric1": np.random.normal(100, 5, n),
            "metric2": np.random.normal(50, 3, n),
        }
        ml_results = {
            "metric1": np.random.normal(95, 5, n),
            "metric2": np.random.normal(48, 3, n),
        }
        
        results = self.run_multiple_comparisons(a3_results, ml_results)
        
        for result in results.values():
            # Corrected p-value should be >= raw p-value
            self.assertGreaterEqual(
                result.p_value_corrected,
                result.p_value_raw
            )


if __name__ == "__main__":
    unittest.main()
