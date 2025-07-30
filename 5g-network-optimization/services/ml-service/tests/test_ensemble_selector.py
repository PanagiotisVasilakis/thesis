from ml_service.app.models.ensemble_selector import EnsembleSelector


def _tiny_dataset():
    return [
        {
            "ue_id": "1",
            "latitude": 0,
            "longitude": 0,
            "speed": 1.0,
            "direction": [1, 0, 0],
            "connected_to": "a1",
            "rf_metrics": {
                "a1": {"rsrp": -70, "sinr": 10},
                "a2": {"rsrp": -80, "sinr": 5},
            },
            "optimal_antenna": "a1",
        },
        {
            "ue_id": "2",
            "latitude": 0,
            "longitude": 100,
            "speed": 1.0,
            "direction": [0, 1, 0],
            "connected_to": "a2",
            "rf_metrics": {
                "a1": {"rsrp": -75, "sinr": 7},
                "a2": {"rsrp": -65, "sinr": 12},
            },
            "optimal_antenna": "a2",
        },
    ]


def test_ensemble_predict(tmp_path):
    data = _tiny_dataset()
    model = EnsembleSelector()
    metrics = model.train(data, validation_split=0)
    assert set(metrics.keys()) == {"LightGBMSelector", "LSTMSelector"}

    features = model.models[0].extract_features(data[0])
    pred = model.predict(features)
    assert pred["antenna_id"] in {"a1", "a2"}
    assert 0.0 <= pred["confidence"] <= 1.0


