import importlib.util
import sys

try:
    import seaborn  # noqa: F401
except ImportError:  # pragma: no cover - optional dependency
    sys.modules["seaborn"] = importlib.util.module_from_spec(
        importlib.util.spec_from_loader("seaborn", loader=None)
    )

from ml_service.initialization import model_init
from ml_service.models.antenna_selector import AntennaSelector
from ml_service.utils import synthetic_data

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
    monkeypatch.setattr(model_init, "generate_synthetic_training_data", lambda n: [{}] * n)

    monkeypatch.setattr(synthetic_data, "generate_synthetic_training_data", lambda n: [{}] * n)
    # First call should train and create the file
    model = initialize_model(str(model_path))
    assert call_count["train"] == 1
    assert model_path.exists()
    assert isinstance(model.model, DummyModel)

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

    monkeypatch.setattr(model_init, "AntennaSelector", DummySelector)

    first = model_init.get_model("foo")
    second = model_init.get_model("bar")

    assert first is second
    assert created == ["foo"]




