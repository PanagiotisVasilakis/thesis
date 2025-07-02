from ml_service.app.models.lightgbm_selector import LightGBMSelector
from ml_service.app.utils.tuning import tune_and_train


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
        {
            "ue_id": "3",
            "latitude": 10,
            "longitude": 0,
            "speed": 1.0,
            "direction": [1, 0, 0],
            "connected_to": "a1",
            "rf_metrics": {
                "a1": {"rsrp": -72, "sinr": 9},
                "a2": {"rsrp": -82, "sinr": 4},
            },
            "optimal_antenna": "a1",
        },
        {
            "ue_id": "4",
            "latitude": 10,
            "longitude": 100,
            "speed": 1.0,
            "direction": [0, 1, 0],
            "connected_to": "a2",
            "rf_metrics": {
                "a1": {"rsrp": -78, "sinr": 6},
                "a2": {"rsrp": -68, "sinr": 11},
            },
            "optimal_antenna": "a2",
        },
    ]


def test_tune_and_train_returns_best_params():
    data = _tiny_dataset()
    model = LightGBMSelector()
    metrics = tune_and_train(model, data, n_iter=1, cv=2)
    assert metrics["samples"] == len(data)
    assert "best_params" in metrics
    assert hasattr(model.model, "predict")
