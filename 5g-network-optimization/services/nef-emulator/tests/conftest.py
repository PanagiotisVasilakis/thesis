import pytest
import os
import sys
import importlib.util
import types
from datetime import datetime, timedelta
from types import SimpleNamespace

from fastapi.testclient import TestClient as FastAPITestClient
from httpx import ASGITransport

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


# ============================================================================
# SHARED TEST FIXTURES - Consolidating duplication across test files (#51-#96)
# ============================================================================

class TestClient(FastAPITestClient):
    """Shared TestClient subclass for all API tests (#53)."""
    def __init__(self, *, transport: ASGITransport, **kwargs):
        super().__init__(transport.app, **kwargs)


class DummyAntenna:
    """Shared DummyAntenna for handover tests (#96)."""
    def __init__(self, rsrp: float):
        self._rsrp = rsrp

    def rsrp_dbm(self, pos):
        return self._rsrp


def make_utc_datetime(base: datetime = None, offset_seconds: float = 0) -> datetime:
    """Create datetime for time patching (#59)."""
    if base is None:
        base = datetime(2025, 1, 1)
    return base + timedelta(seconds=offset_seconds)


def patch_handover_time(monkeypatch, times: list):
    """Shared time patching for handover engine tests (#59)."""
    import backend.app.app.handover.engine as eng
    it = iter(times)

    class FakeDT(datetime):
        @classmethod
        def utcnow(cls):
            return next(it)
    monkeypatch.setattr(eng, 'datetime', FakeDT)


@pytest.fixture
def dummy_antenna_factory():
    """Factory fixture for creating DummyAntenna instances."""
    def _create(rsrp: float) -> DummyAntenna:
        return DummyAntenna(rsrp)
    return _create


@pytest.fixture
def mock_user():
    """Default mock user for API tests (#56)."""
    return SimpleNamespace(id=1, is_superuser=False)


@pytest.fixture
def mock_superuser():
    """Mock superuser for API tests requiring elevated privileges."""
    return SimpleNamespace(id=1, is_superuser=True)


# Test constants (#93)
TEST_ADMIN_EMAIL = "admin@test.com"
TEST_USER_EMAIL = "user@test.com"
TEST_PASSWORD = "testpassword123"
