from ml_service.app.initialization import model_init
from ml_service.app.initialization.model_init import ModelManager
from ml_service.app.models.antenna_selector import AntennaSelector
from ml_service.app.models.lightgbm_selector import LightGBMSelector
from ml_service.app.utils import synthetic_data

initialize_model = ModelManager.initialize


class DummyModel:
    def predict(self, X):
        return ["a1"]

    def predict_proba(self, X):
        return [[0.6, 0.4]]


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

    monkeypatch.setattr(synthetic_data, "generate_synthetic_training_data", lambda n: [{}] * n)
    # First call should train and create the file
    model = initialize_model(str(model_path))
    assert call_count["train"] == 1
    assert model_path.exists()
    assert isinstance(model.model, DummyModel)
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
        def __init__(self, model_path=None):
            created.append(model_path)

    monkeypatch.setattr(model_init, "LightGBMSelector", DummySelector)

    first = ModelManager.get_instance("foo")
    second = ModelManager.get_instance("bar")

    assert first is second
    assert created == ["foo"]


def test_get_model_uses_env_path(monkeypatch):
    ModelManager._model_instance = None
    created = []

    class DummySelector:
        def __init__(self, model_path=None):
            created.append(model_path)

    monkeypatch.setattr(model_init, "LightGBMSelector", DummySelector)
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
