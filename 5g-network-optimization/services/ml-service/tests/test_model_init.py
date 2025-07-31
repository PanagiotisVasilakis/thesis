from ml_service.app.initialization import model_init
from ml_service.app.initialization.model_init import ModelManager
from ml_service.app.models.antenna_selector import AntennaSelector
from ml_service.app.models.lightgbm_selector import LightGBMSelector
from ml_service.app.utils import synthetic_data
import numpy as np
import pytest
import logging

initialize_model = ModelManager.initialize


class DummyModel:
    classes_ = ["a1", "a2"]

    def predict(self, X):
        return ["a1"] * len(X)

    def predict_proba(self, X):
        """Return a fixed two-class probability distribution."""
        return np.tile([0.6, 0.4], (len(X), 1))


def test_initialize_model_trains_and_loads(tmp_path, monkeypatch):
    model_path = tmp_path / "model.joblib"
    call_count = {"train": 0}

    def dummy_train(self, data):
        call_count["train"] += 1
        self.model = DummyModel()
        return {"samples": len(data)}

    monkeypatch.setattr(AntennaSelector, "train", dummy_train)
    monkeypatch.setattr(LightGBMSelector, "train", dummy_train)
    monkeypatch.setattr(model_init, "generate_synthetic_training_data", lambda n: [{}] * n)
    monkeypatch.setitem(model_init.MODEL_CLASSES, "lightgbm", LightGBMSelector)

    monkeypatch.setattr(synthetic_data, "generate_synthetic_training_data", lambda n: [{}] * n)
    # First call should train and create the file
    model = initialize_model(str(model_path))
    assert call_count["train"] == 1
    assert model_path.exists()
    assert isinstance(model.model, DummyModel)
    assert (model_path.parent / "model.joblib.meta.json").exists()
    # initialize_model should store the trained instance for reuse
    assert ModelManager.get_instance() is model

    # Second call should load without retraining
    loaded = initialize_model(str(model_path))
    assert call_count["train"] == 1
    assert isinstance(loaded.model, DummyModel)


def test_get_model_returns_singleton(monkeypatch):
    ModelManager._model_instance = None
    created = []

    class DummySelector:
        def __init__(self, model_path=None, **_):
            created.append(model_path)

    monkeypatch.setitem(model_init.MODEL_CLASSES, "lightgbm", DummySelector)

    first = ModelManager.get_instance("foo")
    second = ModelManager.get_instance("bar")

    assert first is second
    assert created == ["foo"]


def test_get_model_uses_env_path(monkeypatch):
    ModelManager._model_instance = None
    created = []

    class DummySelector:
        def __init__(self, model_path=None, **_):
            created.append(model_path)

    monkeypatch.setitem(model_init.MODEL_CLASSES, "lightgbm", DummySelector)
    monkeypatch.setenv("MODEL_PATH", "env.joblib")

    ModelManager.get_instance()
    assert created == ["env.joblib"]





def test_initialize_model_with_tuning(monkeypatch, tmp_path):
    model_path = tmp_path / "model.joblib"
    called = {"tune": 0}

    def dummy_tune(model, data, n_iter=10, cv=3):
        called["tune"] += 1
        model.model = DummyModel()
        return {"samples": len(data), "best_params": {}}

    monkeypatch.setattr(model_init, "tune_and_train", dummy_tune)
    monkeypatch.setattr(model_init, "generate_synthetic_training_data", lambda n: [{}] * n)
    monkeypatch.setenv("LIGHTGBM_TUNE", "1")
    monkeypatch.setitem(model_init.MODEL_CLASSES, "lightgbm", LightGBMSelector)
    monkeypatch.setitem(model_init.MODEL_CLASSES, "lightgbm", LightGBMSelector)

    model = initialize_model(str(model_path))
    assert called["tune"] == 1
    assert isinstance(model.model, DummyModel)


def test_initialize_model_uses_env_parameters(monkeypatch, tmp_path):
    model_path = tmp_path / "model.joblib"
    seen = {}

    def dummy_tune(model, data, n_iter=10, cv=3):
        seen["n_iter"] = n_iter
        seen["cv"] = cv
        model.model = DummyModel()
        return {"samples": len(data), "best_params": {}}

    monkeypatch.setattr(model_init, "tune_and_train", dummy_tune)
    monkeypatch.setattr(model_init, "generate_synthetic_training_data", lambda n: [{}] * n)
    monkeypatch.setenv("LIGHTGBM_TUNE", "1")
    monkeypatch.setenv("LIGHTGBM_TUNE_N_ITER", "5")
    monkeypatch.setenv("LIGHTGBM_TUNE_CV", "4")

    initialize_model(str(model_path))
    assert seen["n_iter"] == 5
    assert seen["cv"] == 4


def test_initialize_model_uses_neighbor_env(monkeypatch, tmp_path):
    """NEIGHBOR_COUNT environment variable should preallocate features."""
    model_path = tmp_path / "model.joblib"

    def dummy_train(self, data):
        self.model = DummyModel()
        return {"samples": len(data)}

    monkeypatch.setattr(model_init, "generate_synthetic_training_data", lambda n: [{}] * n)
    monkeypatch.setitem(model_init.MODEL_CLASSES, "lightgbm", LightGBMSelector)
    monkeypatch.setattr(LightGBMSelector, "train", dummy_train)
    monkeypatch.setenv("NEIGHBOR_COUNT", "3")

    model = initialize_model(str(model_path))

    assert model.neighbor_count == 3
    assert "rsrp_a3" in model.feature_names


def test_initialize_model_type_mismatch(monkeypatch):
    """Initializing with mismatched metadata should raise ModelError."""

    monkeypatch.setattr(model_init, "_load_metadata", lambda p: {"model_type": "lstm", "version": model_init.MODEL_VERSION})
    with pytest.raises(model_init.ModelError):
        ModelManager.initialize("foo", model_type="lightgbm")


def test_initialize_model_version_warning(monkeypatch, caplog, tmp_path):
    """A warning is logged when metadata version differs."""

    model_path = tmp_path / "model.joblib"
    monkeypatch.setattr(model_init, "_load_metadata", lambda p: {"model_type": "lightgbm", "version": "0.0"})

    def dummy_train(self, data):
        self.model = DummyModel()
        return {"samples": len(data)}

    monkeypatch.setattr(model_init, "generate_synthetic_training_data", lambda n: [{}] * n)
    monkeypatch.setattr(LightGBMSelector, "train", dummy_train)
    caplog.set_level(logging.WARNING)

    ModelManager.initialize(str(model_path))
    assert any("version" in record.getMessage() for record in caplog.records)


def test_initialize_restores_on_train_failure(monkeypatch, tmp_path):
    """Previous model should be restored if training fails."""
    model_path = tmp_path / "new.joblib"

    prev_model = LightGBMSelector()
    ModelManager._model_instance = prev_model
    ModelManager._last_good_model_path = "prev.joblib"

    monkeypatch.setattr(model_init, "generate_synthetic_training_data", lambda n: [{}] * n)

    def fail_train(self, data):
        raise RuntimeError("boom")

    monkeypatch.setattr(LightGBMSelector, "train", fail_train)

    with pytest.raises(RuntimeError):
        ModelManager.initialize(str(model_path))

    assert ModelManager.get_instance() is prev_model


def test_initialize_restores_on_load_failure(monkeypatch, tmp_path):
    """Previous model should be restored if loading fails."""
    model_path = tmp_path / "new.joblib"
    model_path.touch()

    prev_model = LightGBMSelector()
    ModelManager._model_instance = prev_model
    ModelManager._last_good_model_path = "prev.joblib"

    def fail_load(self, path=None):
        raise RuntimeError("load fail")

    monkeypatch.setattr(LightGBMSelector, "load", fail_load)

    with pytest.raises(RuntimeError):
        ModelManager.initialize(str(model_path))

    assert ModelManager.get_instance() is prev_model
