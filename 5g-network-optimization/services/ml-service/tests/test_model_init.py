import importlib.util
import importlib
import sys
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]

# Load the app package dynamically so relative imports work
spec = importlib.util.spec_from_file_location(
    "app",
    SERVICE_ROOT / "app" / "__init__.py",
    submodule_search_locations=[str(SERVICE_ROOT / "app")],
)
app_module = importlib.util.module_from_spec(spec)
for name in list(sys.modules.keys()):
    if name == "app" or name.startswith("app."):
        del sys.modules[name]
sys.modules["app"] = app_module
sys.modules.setdefault(
    "seaborn",
    importlib.util.module_from_spec(importlib.util.spec_from_loader("seaborn", loader=None)),
)
spec.loader.exec_module(app_module)

from app.initialization import model_init
from app.models.antenna_selector import AntennaSelector
from app.utils import synthetic_data

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


def teardown_module(module):
    """Remove dynamically loaded ``app`` modules after tests."""
    for name in list(sys.modules.keys()):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]

