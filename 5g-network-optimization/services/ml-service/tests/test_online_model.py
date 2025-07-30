import pytest
from ml_service.app.models.online_handover_model import OnlineHandoverModel


def _tiny_dataset():
    return [
        {
            "latitude": 0,
            "longitude": 0,
            "speed": 1.0,
            "direction": [1, 0, 0],
            "connected_to": "a1",
            "rf_metrics": {"a1": {"rsrp": -70, "sinr": 10}, "a2": {"rsrp": -80, "sinr": 5}},
            "optimal_antenna": "a1",
        },
        {
            "latitude": 0,
            "longitude": 100,
            "speed": 1.0,
            "direction": [0, 1, 0],
            "connected_to": "a2",
            "rf_metrics": {"a1": {"rsrp": -75, "sinr": 7}, "a2": {"rsrp": -65, "sinr": 12}},
            "optimal_antenna": "a2",
        },
    ]


def test_online_model_train_update_and_drift():
    data = _tiny_dataset()
    model = OnlineHandoverModel(drift_window=3, drift_threshold=0.5)
    metrics = model.train(data)
    assert metrics["samples"] == len(data)

    # Feed successful feedback should not trigger drift
    for sample in data:
        model.update(sample, success=True)
    assert not model.drift_detected()

    # Feed failures to trigger drift
    for _ in range(3):
        model.update(data[0], success=False)
    assert model.drift_detected()
