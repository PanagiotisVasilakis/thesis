import numpy as np
import logging
import threading
import pytest

from ml_service.app.models.lightgbm_selector import LightGBMSelector
from ml_service.app.models.antenna_selector import (
    FALLBACK_ANTENNA_ID,
    FALLBACK_CONFIDENCE,
)
from ml_service.app.models import antenna_selector
from ml_service.app.features import pipeline


def test_extract_features_defaults():
    model = LightGBMSelector()
    features, n_count, names = pipeline.build_model_features(
        {},
        base_feature_names=model.base_feature_names,
        neighbor_count=0,
    )
    assert n_count == 0
    assert names == model.base_feature_names

    assert features == {
        "latitude": 0,
        "longitude": 0,
        "altitude": 0,
        "speed": 0,
        "heading_change_rate": 0,
        "path_curvature": 0,
        "velocity": 0,
        "acceleration": 0,
        "cell_load": 0,
        "handover_count": 0,
        "time_since_handover": 0,
        "signal_trend": 0,
        "environment": 0,
        "rsrp_stddev": 0,
        "sinr_stddev": 0,
        "direction_x": 0,
        "direction_y": 0,
        "rsrp_current": -120,
        "sinr_current": 0,
        "rsrq_current": -30,
        "best_rsrp_diff": 0,
        "best_sinr_diff": 0,
        "best_rsrq_diff": 0,
    }


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


def test_train_metrics_and_prediction_flow(tmp_path):
    data = _tiny_dataset()

    model = LightGBMSelector()
    sample_features = model.extract_features(data[0])
    assert "rsrp_a1" in sample_features
    assert "best_rsrp_diff" in sample_features
    assert "rsrq_a1" in sample_features
    assert "neighbor_cell_load_a1" in sample_features
    assert "best_rsrq_diff" in sample_features

    # Simulate untrained state
    model.model = object()
    default_pred = model.predict(sample_features)
    assert default_pred == {
        "antenna_id": FALLBACK_ANTENNA_ID,
        "confidence": FALLBACK_CONFIDENCE,
    }

    model._initialize_model()
    metrics = model.train(data)
    assert metrics["samples"] == len(data)
    assert metrics["classes"] == 2

    metrics = model.train(data)
    assert metrics["samples"] == len(data)
    assert metrics["classes"] == 2

    trained_pred = model.predict(sample_features)
    assert trained_pred["antenna_id"] in {"a1", "a2"}
    assert 0.0 <= trained_pred["confidence"] <= 1.0

    save_path = tmp_path / "model.joblib"
    assert model.save(save_path)
    assert save_path.exists()

    new_model = LightGBMSelector()
    assert new_model.load(save_path)
    after_load_pred = new_model.predict(sample_features)
    assert after_load_pred["antenna_id"] in {"a1", "a2"}


class DummyModel:
    classes_ = ["other", "mock_ant"]

    def predict(self, X):
        return ["mock_ant"]

    def predict_proba(self, X):
        return [[0.2, 0.8]]

    feature_importances_ = np.zeros(10)


def test_predict_with_mock_and_persistence(tmp_path):
    model = LightGBMSelector()
    model.model = DummyModel()

    features = {
        "latitude": 1,
        "longitude": 2,
        "altitude": 3,
        "speed": 0,
        "heading_change_rate": 0,
        "path_curvature": 0,
        "velocity": 0,
        "acceleration": 0,
        "cell_load": 0,
        "handover_count": 0,
        "time_since_handover": 0,
        "signal_trend": 0,
        "environment": 0,
        "rsrp_stddev": 0,
        "sinr_stddev": 0,
        "direction_x": 0,
        "direction_y": 1,
        "rsrp_current": -80,
        "sinr_current": 10,
        "rsrq_current": -30,
        "best_rsrp_diff": 0,
        "best_sinr_diff": 0,
        "best_rsrq_diff": 0,
    }

    result = model.predict(features)
    assert result == {"antenna_id": "mock_ant", "confidence": 0.8}

    path = tmp_path / "mock.joblib"
    assert model.save(path)
    assert path.exists()

    loaded = LightGBMSelector()
    assert loaded.load(path)
    assert isinstance(loaded.model, DummyModel)
    assert loaded.predict(features) == result


def test_predict_rejects_out_of_range():
    model = LightGBMSelector()
    model.model = DummyModel()
    features = antenna_selector.DEFAULT_TEST_FEATURES.copy()
    features["latitude"] = -5  # below configured min

    with pytest.raises(ValueError):
        model.predict(features)


def test_extract_features_neighbor_padding():
    model = LightGBMSelector()

    first_sample = {
        "connected_to": "a1",
        "rf_metrics": {
            "a1": {"rsrp": -60, "sinr": 15},
            "a2": {"rsrp": -65, "sinr": 10},
            "a3": {"rsrp": -70, "sinr": 5},
            "a4": {"rsrp": -80, "sinr": 3},
        },
    }

    many_features = model.extract_features(first_sample)

    assert model.neighbor_count == 3
    assert "rsrp_a3" in many_features
    assert "rsrp_a3" in model.feature_names
    assert "rsrq_a3" in many_features

    second_sample = {
        "connected_to": "a1",
        "rf_metrics": {
            "a1": {"rsrp": -60, "sinr": 10},
            "a2": {"rsrp": -70, "sinr": 8},
        },
    }

    few_features = model.extract_features(second_sample)

    assert model.neighbor_count == 3
    assert {
        key
        for key in (
            "rsrp_a1",
            "rsrp_a2",
            "rsrp_a3",
            "sinr_a1",
            "sinr_a2",
            "sinr_a3",
            "rsrq_a1",
            "rsrq_a2",
            "rsrq_a3",
            "neighbor_cell_load_a1",
            "neighbor_cell_load_a2",
            "neighbor_cell_load_a3",
        )
    } <= few_features.keys()
    assert few_features["rsrp_a1"] == -70
    assert few_features["sinr_a1"] == 8
    assert few_features["rsrq_a1"] == -30
    assert few_features["rsrp_a2"] == -120
    assert few_features["sinr_a2"] == 0
    assert few_features["rsrq_a2"] == -30
    assert few_features["rsrp_a3"] == -120
    assert few_features["sinr_a3"] == 0
    assert few_features["rsrq_a3"] == -30
    assert few_features["neighbor_cell_load_a1"] == 0
    assert few_features["neighbor_cell_load_a2"] == 0
    assert few_features["neighbor_cell_load_a3"] == 0


def test_altitude_feature_in_training():
    data = _tiny_dataset()
    for i, sample in enumerate(data, start=1):
        sample["altitude"] = float(i)

    model = LightGBMSelector()
    metrics = model.train(data)

    assert "altitude" in model.base_feature_names
    assert "time_since_handover" in model.base_feature_names
    assert "rsrp_stddev" in model.base_feature_names
    assert "sinr_stddev" in model.base_feature_names
    assert "altitude" in model.feature_names
    assert metrics["samples"] == len(data)
    extracted = model.extract_features(data[0])
    assert extracted["altitude"] == 1.0
    assert "time_since_handover" in extracted
    assert "rsrp_stddev" in extracted
    assert "sinr_stddev" in extracted


def test_default_prediction_unfitted_model(tmp_path, caplog):
    """Predict on a fresh model without prior training."""
    model_path = tmp_path / "untrained.joblib"
    model = LightGBMSelector(model_path=str(model_path))

    features = model.extract_features({})
    features["ue_id"] = "u1"
    caplog.set_level(logging.WARNING)
    prediction = model.predict(features)

    assert prediction == {
        "antenna_id": FALLBACK_ANTENNA_ID,
        "confidence": FALLBACK_CONFIDENCE,
    }

    assert any(
        "default antenna" in rec.getMessage().lower() and "u1" in rec.getMessage()
        for rec in caplog.records
    )

    if model_path.exists():
        model_path.unlink()


def test_extract_features_thread_safe():
    """Concurrent calls should not duplicate feature names."""
    model = LightGBMSelector()

    sample = {
        "connected_to": "a1",
        "rf_metrics": {
            "a1": {"rsrp": -60, "sinr": 15},
            "a2": {"rsrp": -65, "sinr": 10},
            "a3": {"rsrp": -70, "sinr": 5},
        },
    }

    results = []

    def worker():
        results.append(model.extract_features(sample))

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert model.neighbor_count == 2
    assert len(model.feature_names) == len(set(model.feature_names))


def test_custom_feature_config(tmp_path):
    import yaml

    cfg = {
        "base_features": [
            {"name": "latitude", "transform": "float"},
            {"name": "longitude", "transform": "float"},
        ]
    }
    path = tmp_path / "features.yaml"
    path.write_text(yaml.safe_dump(cfg))

    model = LightGBMSelector(config_path=str(path))

    assert model.base_feature_names == ["latitude", "longitude"]


def test_missing_feature_config_falls_back(tmp_path):
    missing = tmp_path / "missing.yaml"
    model = LightGBMSelector(config_path=str(missing))
    assert model.base_feature_names == antenna_selector._FALLBACK_FEATURES


def test_feature_transforms_applied(tmp_path):
    import yaml

    cfg = {
        "base_features": [
            {"name": "latitude", "transform": "math.sqrt"},
            {"name": "handover_count", "transform": "int"},
        ]
    }
    path = tmp_path / "features.yaml"
    path.write_text(yaml.safe_dump(cfg))

    model = LightGBMSelector(config_path=str(path))

    data = {
        "latitude": 25,
        "longitude": 0,
        "handover_count": "7",
        "connected_to": "a1",
        "rf_metrics": {"a1": {"rsrp": -70, "sinr": 5}},
    }

    feats = model.extract_features(data, include_neighbors=False)
    assert feats["latitude"] == 5.0
    assert feats["handover_count"] == 7


def test_register_transform_via_code():
    from ml_service.app.features.transform_registry import (
        register_feature_transform,
        clear_feature_transforms,
    )

    try:
        register_feature_transform("latitude", lambda v: float(v) * 10)
        feats, n_count, names = pipeline.build_model_features(
            {"latitude": "1"},
            base_feature_names=["latitude"],
            neighbor_count=0,
        )
        assert feats["latitude"] == 10.0
        assert n_count == 0
        assert names == ["latitude"]
    finally:
        clear_feature_transforms()
