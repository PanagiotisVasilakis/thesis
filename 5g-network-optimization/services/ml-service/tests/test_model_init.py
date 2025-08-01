import json
import logging
import time
from datetime import datetime

import numpy as np
import pytest
from ml_service.app.initialization import model_init
from ml_service.app.initialization.model_init import ModelManager
from ml_service.app.models.antenna_selector import AntennaSelector
from ml_service.app.models.lightgbm_selector import LightGBMSelector
from ml_service.app.utils import synthetic_data


def initialize_model(*args, **kwargs):
    kwargs.setdefault("background", False)
    return ModelManager.initialize(*args, **kwargs)


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
    meta_file = model_path.parent / "model.joblib.meta.json"
    assert meta_file.exists()
    with open(meta_file, "r", encoding="utf-8") as f:
        meta = json.load(f)
    assert "trained_at" in meta
    datetime.fromisoformat(meta["trained_at"])
    assert meta["version"] == "1.0.0"
    # initialize_model should store the trained instance for reuse
    assert ModelManager.get_instance() is model

    assert ModelManager._last_good_model_path == str(model_path)

    # Second call should load without retraining
    loaded = initialize_model(str(model_path))
    assert call_count["train"] == 1
    assert isinstance(loaded.model, DummyModel)
    assert ModelManager._last_good_model_path == str(model_path)


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
        ModelManager.initialize("foo", model_type="lightgbm", background=False)


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

    ModelManager.initialize(str(model_path), background=False)
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
        ModelManager.initialize(str(model_path), background=False)

    assert ModelManager.get_instance() is prev_model
    assert ModelManager._last_good_model_path == "prev.joblib"


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
        ModelManager.initialize(str(model_path), background=False)

    assert ModelManager.get_instance() is prev_model
    assert ModelManager._last_good_model_path == "prev.joblib"


def test_switch_version_loads_registered_model(monkeypatch, tmp_path):
    version1 = "1.0.0"
    version2 = "2.0.0"
    path1 = tmp_path / f"model_v{version1}.joblib"
    path2 = tmp_path / f"model_v{version2}.joblib"
    path1.touch()
    path2.touch()
    meta = {"model_type": "lightgbm", "version": model_init.MODEL_VERSION}
    for p in (path1, path2):
        with open(p.with_suffix(p.suffix + ".meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f)

    loads = []

    def dummy_load(self, path=None):
        loads.append(path)
        return True

    monkeypatch.setattr(LightGBMSelector, "load", dummy_load)

    ModelManager._model_paths = {}
    ModelManager.initialize(str(path1), background=False)
    ModelManager._model_paths[version2] = str(path2)

    ModelManager.switch_version(version2)
    assert loads[-1] == str(path2)
    assert ModelManager._last_good_model_path == str(path2)


def test_discovered_versions_switchable(monkeypatch, tmp_path):
    """Versions found on disk should be loadable immediately."""
    version1 = "1.0.0"
    version2 = "2.0.0"
    path1 = tmp_path / f"model_v{version1}.joblib"
    path2 = tmp_path / f"model_v{version2}.joblib"
    for p in (path1, path2):
        p.touch()
        with open(p.with_suffix(f"{p.suffix}.meta.json"), "w", encoding="utf-8") as f:
            json.dump({"model_type": "lightgbm", "version": model_init.MODEL_VERSION}, f)

    loads = []

    def dummy_load(self, path=None):
        loads.append(path)
        return True

    monkeypatch.setattr(LightGBMSelector, "load", dummy_load)

    ModelManager._model_instance = None
    ModelManager._model_paths = {}

    ModelManager.initialize(str(path1), background=False)

    assert ModelManager._model_paths[version1] == str(path1)
    assert ModelManager._model_paths[version2] == str(path2)

    ModelManager.switch_version(version2)
    assert loads[-1] == str(path2)
    assert ModelManager._last_good_model_path == str(path2)


def test_switch_version_fallback(monkeypatch, tmp_path):
    version1 = "1.0.0"
    version2 = "2.0.0"
    path1 = tmp_path / f"model_v{version1}.joblib"
    path1.touch()
    with open(path1.with_suffix(path1.suffix + ".meta.json"), "w", encoding="utf-8") as f:
        json.dump({"model_type": "lightgbm", "version": model_init.MODEL_VERSION}, f)

    monkeypatch.setattr(LightGBMSelector, "load", lambda self, path=None: True)
    ModelManager._model_paths = {}
    ModelManager.initialize(str(path1), background=False)
    prev_model = ModelManager.get_instance()

    path2 = tmp_path / f"model_v{version2}.joblib"
    path2.touch()
    with open(path2.with_suffix(path2.suffix + ".meta.json"), "w", encoding="utf-8") as f:
        json.dump({"model_type": "lightgbm", "version": model_init.MODEL_VERSION}, f)

    def fail_load(self, path=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(LightGBMSelector, "load", fail_load)
    ModelManager._model_paths[version2] = str(path2)

    ModelManager.switch_version(version2)
    assert ModelManager.get_instance() is prev_model
    assert ModelManager._last_good_model_path == str(path1)

def test_initialize_background_returns_placeholder(monkeypatch, tmp_path):
    """Initialization with background=True should return a placeholder immediately."""
    model_path = tmp_path / "model.joblib"
    model_path.touch()
    with open(model_path.with_suffix(f"{model_path.suffix}.meta.json"), "w", encoding="utf-8") as f:
        json.dump({"model_type": "lightgbm", "version": model_init.MODEL_VERSION}, f)

    final_model = DummyModel()

    def dummy_initialize_sync(*args, **kwargs):
        time.sleep(0.05)
        ModelManager._model_instance = final_model
        ModelManager._last_good_model_path = str(model_path)
        ModelManager._init_event.set()
        return final_model

    monkeypatch.setattr(ModelManager, "_initialize_sync", dummy_initialize_sync)
    ModelManager._model_instance = None
    ModelManager._init_thread = None
    ModelManager._init_event.clear()

    placeholder = ModelManager.initialize(str(model_path), background=True)

    assert placeholder is ModelManager.get_instance()
    assert placeholder is not final_model
    thread = ModelManager._init_thread
    assert thread is not None and thread.is_alive()
    thread.join(timeout=1)
    assert ModelManager.get_instance() is final_model


@pytest.mark.parametrize("fail", [False, True])
def test_switch_version(monkeypatch, tmp_path, fail):
    """switch_version loads the requested version and falls back on failure."""
    version1 = "1.0.0"
    version2 = "2.0.0"
    path1 = tmp_path / f"model_v{version1}.joblib"
    path2 = tmp_path / f"model_v{version2}.joblib"
    path1.touch()
    path2.touch()
    meta = {"model_type": "lightgbm", "version": model_init.MODEL_VERSION}
    for p in (path1, path2):
        with open(p.with_suffix(f"{p.suffix}.meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f)

    load_calls = []

    def dummy_load(self, path=None):
        load_calls.append(path)
        if path == str(path2) and fail:
            raise RuntimeError("fail")
        return True

    monkeypatch.setattr(LightGBMSelector, "load", dummy_load)
    ModelManager._model_paths = {}
    ModelManager.initialize(str(path1), background=False)
    prev_model = ModelManager.get_instance()

    ModelManager._model_paths[version2] = str(path2)
    ModelManager.switch_version(version2)

    assert load_calls[-1] == str(path2)

    # Test switching to a non-existent version
    import pytest
    non_existent_version = "non-existent-version"
    with pytest.raises(ValueError):
        ModelManager.switch_version(non_existent_version)
    if fail:
        assert ModelManager.get_instance() is prev_model
        assert ModelManager._last_good_model_path == str(path1)
    else:
        assert ModelManager.get_instance() is not prev_model
        assert ModelManager._last_good_model_path == str(path2)
