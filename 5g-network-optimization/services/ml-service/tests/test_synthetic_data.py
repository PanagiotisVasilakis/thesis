import math
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
        assert 'cell_load' in metrics


def test_rsrq_value_range():
    data = generate_synthetic_training_data(5, num_antennas=2)
    for sample in data:
        for metrics in sample['rf_metrics'].values():
            assert -30 <= metrics['rsrq'] <= -3


def test_additional_metrics_presence_and_range():
    data = generate_synthetic_training_data(10, num_antennas=3)
    for sample in data:
        assert 'stability' in sample
        assert 0.0 <= sample['stability'] <= 1.0

        assert 'time_since_handover' in sample
        assert sample['time_since_handover'] >= 0.0

        assert 'heading_change_rate' in sample
        assert 0.0 <= sample['heading_change_rate'] <= math.pi

        assert 'path_curvature' in sample
        assert 0.0 <= sample['path_curvature'] <= 1.0

        for metrics in sample['rf_metrics'].values():
            assert 'cell_load' in metrics
            assert 0.0 <= metrics['cell_load'] <= 1.0
