import numpy as np
from pathlib import Path
from ml_service.app.models.lightgbm_selector import LightGBMSelector


def _tiny_dataset():
    return [
        {
            "ue_id": "1",
            "latitude": 0,
            "longitude": 0,
            "speed": 1.0,
            "heading_change_rate": 0.0,
            "path_curvature": 0.0,
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
            "heading_change_rate": 0.0,
            "path_curvature": 0.0,
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
            "latitude": 50,
            "longitude": 50,
            "speed": 1.0,
            "heading_change_rate": 0.0,
            "path_curvature": 0.0,
            "direction": [1, 1, 0],
            "connected_to": "a1",
            "rf_metrics": {
                "a1": {"rsrp": -80, "sinr": 8},
                "a2": {"rsrp": -70, "sinr": 9},
            },
            "optimal_antenna": "a1",
        },
    ]


def test_scaler_persistence(tmp_path):
    data = _tiny_dataset()
    model = LightGBMSelector()
    model.train(data)
    sample_features = model.extract_features(data[0])
    baseline = model.scaler.transform(
        [[sample_features[name] for name in model.feature_names]]
    )[0]

    path = tmp_path / "model.joblib"
    assert model.save(path)

    scaler_path = Path(str(path) + ".scaler")
    assert scaler_path.exists(), "Scaler file was not saved separately"

    loaded = LightGBMSelector()
    assert loaded.load(path)
    loaded_features = loaded.scaler.transform(
        [[sample_features[name] for name in loaded.feature_names]]
    )[0]

    assert np.allclose(baseline, loaded_features)

