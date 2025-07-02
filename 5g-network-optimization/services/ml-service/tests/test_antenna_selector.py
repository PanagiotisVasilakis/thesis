import numpy as np

from ml_service.app.models.lightgbm_selector import LightGBMSelector


def test_extract_features_defaults():
    model = LightGBMSelector()
    features = model.extract_features({})

    assert features == {
        'latitude': 0,
        'longitude': 0,
        'speed': 0,
        'direction_x': 0,
        'direction_y': 0,
        'rsrp_current': -120,
        'sinr_current': 0,
        'best_rsrp_diff': 0,
        'best_sinr_diff': 0,
    }


def _tiny_dataset():
    return [
        {
            'ue_id': '1',
            'latitude': 0,
            'longitude': 0,
            'speed': 1.0,
            'direction': [1, 0, 0],
            'connected_to': 'a1',
            'rf_metrics': {
                'a1': {'rsrp': -70, 'sinr': 10},
                'a2': {'rsrp': -80, 'sinr': 5},
            },
            'optimal_antenna': 'a1',
        },
        {
            'ue_id': '2',
            'latitude': 0,
            'longitude': 100,
            'speed': 1.0,
            'direction': [0, 1, 0],
            'connected_to': 'a2',
            'rf_metrics': {
                'a1': {'rsrp': -75, 'sinr': 7},
                'a2': {'rsrp': -65, 'sinr': 12},
            },
            'optimal_antenna': 'a2',
        },
        {
            'ue_id': '3',
            'latitude': 50,
            'longitude': 50,
            'speed': 1.0,
            'direction': [1, 1, 0],
            'connected_to': 'a1',
            'rf_metrics': {
                'a1': {'rsrp': -80, 'sinr': 8},
                'a2': {'rsrp': -70, 'sinr': 9},
            },
            'optimal_antenna': 'a1',
        },
    ]


def test_train_metrics_and_prediction_flow(tmp_path):
    data = _tiny_dataset()

    model = LightGBMSelector()
    sample_features = model.extract_features(data[0])
    assert 'rsrp_a1' in sample_features
    assert 'best_rsrp_diff' in sample_features

    # Simulate untrained state
    model.model = object()
    default_pred = model.predict(sample_features)
    assert default_pred == {'antenna_id': 'antenna_1', 'confidence': 0.5}

    model._initialize_model()
    metrics = model.train(data)
    assert metrics['samples'] == len(data)
    assert metrics['classes'] == 2

    metrics = model.train(data)
    assert metrics['samples'] == len(data)
    assert metrics['classes'] == 2

    trained_pred = model.predict(sample_features)
    assert trained_pred['antenna_id'] in {'a1', 'a2'}
    assert 0.0 <= trained_pred['confidence'] <= 1.0

    save_path = tmp_path / 'model.joblib'
    assert model.save(save_path)
    assert save_path.exists()

    new_model = LightGBMSelector()
    assert new_model.load(save_path)
    after_load_pred = new_model.predict(sample_features)
    assert after_load_pred['antenna_id'] in {'a1', 'a2'}


class DummyModel:
    def predict(self, X):
        return ['mock_ant']

    def predict_proba(self, X):
        return [[0.2, 0.8]]

    feature_importances_ = np.zeros(9)


def test_predict_with_mock_and_persistence(tmp_path):
    model = LightGBMSelector()
    model.model = DummyModel()

    features = {
        'latitude': 1,
        'longitude': 2,
        'speed': 0,
        'direction_x': 0,
        'direction_y': 1,
        'rsrp_current': -80,
        'sinr_current': 10,
        'best_rsrp_diff': 0,
        'best_sinr_diff': 0,
    }

    result = model.predict(features)
    assert result == {'antenna_id': 'mock_ant', 'confidence': 0.8}

    path = tmp_path / 'mock.joblib'
    assert model.save(path)
    assert path.exists()

    loaded = LightGBMSelector()
    assert loaded.load(path)
    assert isinstance(loaded.model, DummyModel)
    assert loaded.predict(features) == result

