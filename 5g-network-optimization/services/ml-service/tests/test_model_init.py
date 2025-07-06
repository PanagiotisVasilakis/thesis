from ml_service.app.initialization import model_init
from ml_service.app.models.antenna_selector import AntennaSelector
from ml_service.app.models.lightgbm_selector import LightGBMSelector
from ml_service.app.utils import synthetic_data

initialize_model = model_init.initialize_model


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
    assert model_init._model_instance is model

    # Second call should load without retraining
    loaded = initialize_model(str(model_path))
    assert call_count["train"] == 1
    assert isinstance(loaded.model, DummyModel)


def test_get_model_returns_singleton(monkeypatch):
    model_init._model_instance = None
    created = []

    class DummySelector:
        def __init__(self, model_path=None):
            created.append(model_path)

    monkeypatch.setattr(model_init, "LightGBMSelector", DummySelector)

    first = model_init.get_model("foo")
    second = model_init.get_model("bar")

    assert first is second
    assert created == ["foo"]


def test_get_model_uses_env_path(monkeypatch):
    model_init._model_instance = None
    created = []

    class DummySelector:
        def __init__(self, model_path=None):
            created.append(model_path)

    monkeypatch.setattr(model_init, "LightGBMSelector", DummySelector)
    monkeypatch.setenv("MODEL_PATH", "env.joblib")

    model_init.get_model()
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


def test_initialize_model_passes_lgbm_params(monkeypatch, tmp_path):
    path = tmp_path / "model.joblib"
    captured = {}

    class DummySelector:
        def __init__(self, model_path=None, **params):
            captured.update(params)
            self.model = DummyModel()

        def predict(self, _):
            raise Exception()

        def train(self, data):
            return {"samples": len(data)}

        def save(self, p=None):
            pass

    monkeypatch.setattr(model_init, "LightGBMSelector", DummySelector)
    monkeypatch.setattr(model_init, "generate_synthetic_training_data", lambda n: [{}] * n)

    monkeypatch.setenv("LGBM_N_ESTIMATORS", "123")
    monkeypatch.setenv("LGBM_MAX_DEPTH", "7")
    monkeypatch.setenv("LGBM_NUM_LEAVES", "50")
    monkeypatch.setenv("LGBM_LEARNING_RATE", "0.3")
    monkeypatch.setenv("LGBM_FEATURE_FRACTION", "0.9")

    initialize_model(str(path))

    assert captured == {
        "n_estimators": 123,
        "max_depth": 7,
        "num_leaves": 50,
        "learning_rate": 0.3,
        "feature_fraction": 0.9,
    }
