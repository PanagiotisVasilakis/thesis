import math

from ml_service.app.features import pipeline


def test_extract_rf_environment_and_mobility_features():
    feature_vector = {
        "neighbor_rsrp_dbm": {"a1": -80, "a2": -90},
        "neighbor_sinrs": {"a1": 10, "a2": 5},
        "neighbor_rsrqs": {"a1": -10},
        "neighbor_cell_loads": {"a1": 0.5},
        "cell_load": 0.3,
        "environment": 2.0,
        "signal_trend": -1.5,
        "speed": 3.0,
        "velocity": 4.0,
        "acceleration": 0.1,
        "heading_change_rate": 0.2,
        "path_curvature": 0.3,
        "direction": [3, 4, 0],
    }

    rf = pipeline.extract_rf_features(feature_vector)
    assert rf == {
        "a1": {"rsrp": -80, "sinr": 10, "rsrq": -10, "cell_load": 0.5},
        "a2": {"rsrp": -90, "sinr": 5},
    }

    env = pipeline.extract_environment_features(feature_vector)
    assert env == {"cell_load": 0.3, "environment": 2.0, "signal_trend": -1.5}

    mobility = pipeline.extract_mobility_features(feature_vector)
    assert mobility["speed"] == 3.0
    assert mobility["velocity"] == 4.0
    assert mobility["acceleration"] == 0.1
    assert math.isclose(mobility["direction_x"], 0.6, rel_tol=1e-5)
    assert math.isclose(mobility["direction_y"], 0.8, rel_tol=1e-5)
