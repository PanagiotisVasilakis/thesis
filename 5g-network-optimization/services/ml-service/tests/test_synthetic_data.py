import pytest
from ml_service.app.utils.synthetic_data import generate_synthetic_training_data


def test_rf_metrics_entries_per_antenna():
    data = generate_synthetic_training_data(1, num_antennas=3)
    assert len(data) == 1
    sample = data[0]
    assert 'rf_metrics' in sample
    assert len(sample['rf_metrics']) == 3
    for metrics in sample['rf_metrics'].values():
        assert 'rsrp' in metrics
        assert 'sinr' in metrics
        assert 'rsrq' in metrics


def test_rsrq_value_range():
    data = generate_synthetic_training_data(5, num_antennas=2)
    for sample in data:
        for metrics in sample['rf_metrics'].values():
            assert -30 <= metrics['rsrq'] <= -3
