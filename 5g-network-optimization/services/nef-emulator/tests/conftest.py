import pytest
import os
import sys
import importlib.util
import types

# Ensure the NEF emulator root is on sys.path for all tests
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
BACKEND_ROOT = os.path.join(ROOT, 'backend')
APP_ROOT = os.path.join(BACKEND_ROOT, 'app')
ML_ROOT_PARENT = os.path.abspath(os.path.join(ROOT, '..'))

for path in [ML_ROOT_PARENT, ROOT, BACKEND_ROOT, APP_ROOT]:
    if path not in sys.path:
        sys.path.insert(0, path)

# Ensure the NEF emulator package is accessible as ``app`` to avoid
# conflicts with the ML service tests that also register a module named
# ``app``.
# Provide a lightweight ``app.network.state_manager`` package so that modules
# can import it without requiring the full ML service package.
state_mgr_spec = importlib.util.spec_from_file_location(
    "app.network.state_manager",
    os.path.join(APP_ROOT, "app", "network", "state_manager.py"),
)
state_mgr = importlib.util.module_from_spec(state_mgr_spec)
state_mgr_spec.loader.exec_module(state_mgr)

app_pkg = types.ModuleType("app")
network_pkg = types.ModuleType("app.network")
network_pkg.state_manager = state_mgr
app_pkg.network = network_pkg
sys.modules.setdefault("app", app_pkg)
sys.modules.setdefault("app.network", network_pkg)
sys.modules.setdefault("app.network.state_manager", state_mgr)


@pytest.fixture(autouse=True)
def clear_ml_local(monkeypatch):
    monkeypatch.delenv("ML_LOCAL", raising=False)
    yield
    monkeypatch.delenv("ML_LOCAL", raising=False)
