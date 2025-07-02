from ml_service.app.models.lightgbm_selector import LightGBMSelector


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


def test_lightgbm_train_and_predict(tmp_path):
    data = _tiny_dataset()

    model = LightGBMSelector()
    sample_features = model.extract_features(data[0])
    assert 'rsrp_a1' in sample_features

    metrics = model.train(data)
    assert metrics['samples'] == len(data)

    pred = model.predict(sample_features)
    assert pred['antenna_id'] in {'a1', 'a2'}
    assert 0.0 <= pred['confidence'] <= 1.0

    save_path = tmp_path / 'lgbm.joblib'
    assert model.save(save_path)
    assert save_path.exists()

    loaded = LightGBMSelector()
    assert loaded.load(save_path)
    loaded_pred = loaded.predict(sample_features)
    assert loaded_pred['antenna_id'] in {'a1', 'a2'}


