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
    assert 'best_rsrp_diff' in sample_features

    metrics = model.train(data)
    assert metrics['samples'] == len(data)
    assert 0.0 <= metrics['val_accuracy'] <= 1.0
    assert 0.0 <= metrics['val_f1'] <= 1.0

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



def test_lightgbm_custom_params():
    model = LightGBMSelector(num_leaves=64, learning_rate=0.05, feature_fraction=0.8)
    params = model.model.get_params()
    assert params["num_leaves"] == 64
    assert abs(params["learning_rate"] - 0.05) < 1e-6
    assert abs(params["feature_fraction"] - 0.8) < 1e-6


def test_lightgbm_env_params(monkeypatch):
    monkeypatch.setenv("LGBM_N_ESTIMATORS", "150")
    monkeypatch.setenv("LGBM_MAX_DEPTH", "5")
    monkeypatch.setenv("LGBM_NUM_LEAVES", "40")
    monkeypatch.setenv("LGBM_LEARNING_RATE", "0.2")
    monkeypatch.setenv("LGBM_FEATURE_FRACTION", "0.7")

    model = LightGBMSelector()
    params = model.model.get_params()
    assert params["n_estimators"] == 150
    assert params["max_depth"] == 5
    assert params["num_leaves"] == 40
    assert abs(params["learning_rate"] - 0.2) < 1e-6
    assert abs(params["feature_fraction"] - 0.7) < 1e-6
