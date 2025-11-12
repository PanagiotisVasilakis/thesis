"""Phase 7: Tests for new monitoring metrics.

Validates that model health metrics are tracked correctly and don't produce NaN values.
"""
from __future__ import annotations

import pytest
from ml_service.app.monitoring import metrics


class TestPhase7Metrics:
    """Tests for Phase 7 monitoring improvements."""
    
    def test_model_health_score_calculation(self):
        """Model health score should be composite of diversity, fallback, geo override rates."""
        # Perfect health: high diversity, low fallback, low override
        health = metrics.update_model_health(
            diversity_ratio=0.5,  # 50% diversity (target: >40%)
            fallback_rate=0.05,   # 5% fallback (target: <10%)
            geographic_override_rate=0.02,  # 2% override (target: <5%)
        )
        
        # Should be reasonably high (diversity component is 50% / 40% * 50% = 0.625)
        assert 0.7 <= health <= 1.0, f"Expected high health score, got {health}"
        
        # Check gauge was updated
        gauge_value = metrics.MODEL_HEALTH_SCORE._value.get()
        assert gauge_value == health
    
    def test_model_health_score_poor_diversity(self):
        """Poor diversity should lower health score."""
        # Poor health: low diversity
        health = metrics.update_model_health(
            diversity_ratio=0.1,  # Only 10% diversity (target: >40%)
            fallback_rate=0.05,
            geographic_override_rate=0.02,
        )
        
        # Should be lower due to poor diversity (50% weight)
        assert 0.2 <= health <= 0.6, f"Expected medium health score, got {health}"
    
    def test_model_health_score_high_fallback(self):
        """High fallback rate should lower health score."""
        # Poor health: high fallback
        health = metrics.update_model_health(
            diversity_ratio=0.5,
            fallback_rate=0.3,  # 30% fallback (target: <10%)
            geographic_override_rate=0.02,
        )
        
        # Should be lower due to high fallback (30% weight)
        assert 0.5 <= health <= 0.8, f"Expected medium-high health score, got {health}"
    
    def test_model_health_score_high_geo_override(self):
        """High geographic override rate should lower health score."""
        # Poor health: high geographic overrides
        health = metrics.update_model_health(
            diversity_ratio=0.5,
            fallback_rate=0.05,
            geographic_override_rate=0.2,  # 20% override (target: <5%)
        )
        
        # Should be lower due to high overrides (20% weight)
        assert 0.6 <= health <= 0.9, f"Expected medium-high health score, got {health}"
    
    def test_model_health_score_bounds(self):
        """Health score should be bounded between 0 and 1."""
        # Test extreme values
        health_min = metrics.update_model_health(
            diversity_ratio=0.0,
            fallback_rate=1.0,
            geographic_override_rate=1.0,
        )
        assert 0.0 <= health_min <= 1.0
        
        health_max = metrics.update_model_health(
            diversity_ratio=1.0,
            fallback_rate=0.0,
            geographic_override_rate=0.0,
        )
        assert 0.0 <= health_max <= 1.0
        assert health_max >= 0.9  # Should be near perfect
    
    def test_prediction_distribution_update(self):
        """Prediction distribution should track percentages per antenna."""
        prediction_counts = {
            "antenna_1": 25,
            "antenna_2": 25,
            "antenna_3": 25,
            "antenna_4": 25,
        }
        
        metrics.update_prediction_distribution(prediction_counts)
        
        # Each antenna should have 25% of predictions
        for antenna_id in prediction_counts:
            gauge_value = metrics.PREDICTION_DISTRIBUTION.labels(antenna_id=antenna_id)._value.get()
            assert abs(gauge_value - 25.0) < 0.01, f"{antenna_id}: expected 25%, got {gauge_value}%"
    
    def test_prediction_distribution_imbalanced(self):
        """Prediction distribution should reflect imbalanced predictions."""
        prediction_counts = {
            "antenna_1": 70,  # 70%
            "antenna_2": 10,  # 10%
            "antenna_3": 10,  # 10%
            "antenna_4": 10,  # 10%
        }
        
        metrics.update_prediction_distribution(prediction_counts)
        
        # antenna_1 should have 70%
        gauge_value = metrics.PREDICTION_DISTRIBUTION.labels(antenna_id="antenna_1")._value.get()
        assert abs(gauge_value - 70.0) < 0.01, f"Expected 70%, got {gauge_value}%"
        
        # Others should have 10%
        for antenna_id in ["antenna_2", "antenna_3", "antenna_4"]:
            gauge_value = metrics.PREDICTION_DISTRIBUTION.labels(antenna_id=antenna_id)._value.get()
            assert abs(gauge_value - 10.0) < 0.01, f"{antenna_id}: expected 10%, got {gauge_value}%"
    
    def test_prediction_distribution_empty(self):
        """Empty prediction counts should not crash."""
        prediction_counts = {}
        
        # Should not raise exception
        metrics.update_prediction_distribution(prediction_counts)
    
    def test_prediction_diversity_ratio_gauge(self):
        """Prediction diversity ratio gauge should be settable."""
        # Set diversity ratio
        metrics.PREDICTION_DIVERSITY_RATIO.set(0.42)
        
        # Check value
        value = metrics.PREDICTION_DIVERSITY_RATIO._value.get()
        assert value == 0.42
    
    def test_histogram_buckets_configured(self):
        """Histograms should have appropriate buckets for sparse data."""
        # Check prediction latency buckets
        assert hasattr(metrics.PREDICTION_LATENCY, '_buckets')
        # Buckets should include sub-second values
        assert any(b < 1.0 for b in metrics.PREDICTION_LATENCY._upper_bounds if b != float('inf'))
        
        # Check handover interval buckets
        assert hasattr(metrics.HANDOVER_INTERVAL, '_buckets')
        # Buckets should include both short and long intervals
        assert any(b < 10.0 for b in metrics.HANDOVER_INTERVAL._upper_bounds if b != float('inf'))
        assert any(b > 60.0 for b in metrics.HANDOVER_INTERVAL._upper_bounds if b != float('inf'))
    
    def test_coverage_loss_counter_exists(self):
        """Coverage loss counter should exist in NEF metrics."""
        # Skip if NEF not available (ML service tests only)
        pytest.importorskip("app.monitoring.metrics", reason="NEF module not available")
        
        from app.monitoring import metrics as nef_metrics
        
        # Should have coverage loss counter
        assert hasattr(nef_metrics, 'COVERAGE_LOSS_HANDOVERS')
        
        # Should be a Counter
        assert hasattr(nef_metrics.COVERAGE_LOSS_HANDOVERS, 'inc')
        
        # Test incrementing
        before = nef_metrics.COVERAGE_LOSS_HANDOVERS._value.get()
        nef_metrics.COVERAGE_LOSS_HANDOVERS.inc()
        after = nef_metrics.COVERAGE_LOSS_HANDOVERS._value.get()
        
        assert after == before + 1
    
    def test_model_health_metrics_exported(self):
        """Model health metrics should be exported in registry."""
        # Check metrics are in registry
        metric_names = [m.name for m in metrics.REGISTRY.collect()]
        
        assert 'ml_model_health_score' in metric_names
        assert 'ml_prediction_diversity_ratio' in metric_names
        assert 'ml_prediction_distribution_percent' in metric_names
    
    def test_geographic_override_counter_exists(self):
        """Geographic override counter should exist."""
        assert hasattr(metrics, 'GEOGRAPHIC_OVERRIDES')
        
        # Should be a Counter
        assert hasattr(metrics.GEOGRAPHIC_OVERRIDES, 'inc')
        
        # Test incrementing
        before = metrics.GEOGRAPHIC_OVERRIDES._value.get()
        metrics.GEOGRAPHIC_OVERRIDES.inc()
        after = metrics.GEOGRAPHIC_OVERRIDES._value.get()
        
        assert after == before + 1
    
    def test_low_diversity_warning_counter_exists(self):
        """Low diversity warning counter should exist."""
        assert hasattr(metrics, 'LOW_DIVERSITY_WARNINGS')
        
        # Should be a Counter
        assert hasattr(metrics.LOW_DIVERSITY_WARNINGS, 'inc')
        
        # Test incrementing
        before = metrics.LOW_DIVERSITY_WARNINGS._value.get()
        metrics.LOW_DIVERSITY_WARNINGS.inc()
        after = metrics.LOW_DIVERSITY_WARNINGS._value.get()
        
        assert after == before + 1


class TestMetricsNoNaN:
    """Tests ensuring metrics don't produce NaN values."""
    
    def test_histogram_observations_no_nan(self):
        """Histogram observations should never produce NaN."""
        # Observe some values
        metrics.PREDICTION_LATENCY.observe(0.05)
        metrics.PREDICTION_LATENCY.observe(0.1)
        metrics.PREDICTION_LATENCY.observe(0.2)
        
        # Check samples exist
        samples = list(metrics.PREDICTION_LATENCY.collect())[0].samples
        
        # No sample value should be NaN
        for sample in samples:
            assert sample.value is not None
            if isinstance(sample.value, float):
                import math
                assert not math.isnan(sample.value), f"Sample {sample.name} is NaN"
    
    def test_gauge_values_no_nan(self):
        """Gauge values should never be NaN."""
        import math
        
        # Set some gauge values
        metrics.MODEL_HEALTH_SCORE.set(0.85)
        metrics.PREDICTION_DIVERSITY_RATIO.set(0.42)
        
        # Check values
        health = metrics.MODEL_HEALTH_SCORE._value.get()
        diversity = metrics.PREDICTION_DIVERSITY_RATIO._value.get()
        
        assert not math.isnan(health), "Health score is NaN"
        assert not math.isnan(diversity), "Diversity ratio is NaN"
    
    def test_counter_values_no_nan(self):
        """Counter values should never be NaN."""
        import math
        
        # Increment counters
        metrics.GEOGRAPHIC_OVERRIDES.inc()
        metrics.LOW_DIVERSITY_WARNINGS.inc()
        
        # Check values
        overrides = metrics.GEOGRAPHIC_OVERRIDES._value.get()
        warnings = metrics.LOW_DIVERSITY_WARNINGS._value.get()
        
        assert not math.isnan(overrides), "Geographic overrides is NaN"
        assert not math.isnan(warnings), "Low diversity warnings is NaN"
