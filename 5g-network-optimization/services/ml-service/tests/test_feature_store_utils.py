import importlib
import sys
from pathlib import Path
from types import SimpleNamespace, ModuleType


def _reload_module(monkeypatch, dummy_class):
    dummy_feast = ModuleType("feast")
    dummy_feast.FeatureStore = dummy_class
    dummy_feast.Field = object
    types_mod = ModuleType("feast.types")
    types_mod.Float32 = object
    types_mod.String = object
    dummy_feast.types = types_mod

    monkeypatch.setitem(sys.modules, "feast", dummy_feast)
    monkeypatch.setitem(sys.modules, "feast.types", types_mod)

    # Ensure the repository root is importable so ``mlops`` can be found.
    root = Path(__file__).resolve().parents[4]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    import ml_service.app.data.feature_store_utils as module
    return importlib.reload(module)


class DummyStore:
    def __init__(self, path):
        self.path = path


def test_store_uses_default_repo(monkeypatch):
    module = _reload_module(monkeypatch, DummyStore)
    monkeypatch.delenv("FEAST_REPO_PATH", raising=False)
    store = module._store()
    assert isinstance(store, DummyStore)
    assert store.path == str(module.REPO_PATH)


def test_store_uses_env_repo(monkeypatch, tmp_path):
    module = _reload_module(monkeypatch, DummyStore)
    custom = tmp_path / "feast_repo"
    monkeypatch.setenv("FEAST_REPO_PATH", str(custom))
    store = module._store()
    assert isinstance(store, DummyStore)
    assert store.path == str(custom)
