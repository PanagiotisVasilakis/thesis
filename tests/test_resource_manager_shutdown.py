import importlib.util
import pathlib
import pytest


# Import the module directly from its path to avoid pulling in the full
# ml_service package, which requires heavy optional dependencies (e.g.
# LightGBM).  This keeps the test environment lightweight while still
# exercising the ResourceManager logic.
MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / (
    "5g-network-optimization/services/ml-service/ml_service/app/utils/resource_manager.py"
)
spec = importlib.util.spec_from_file_location(
    "ml_service.app.utils.resource_manager", MODULE_PATH
)
resource_manager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resource_manager)

ResourceManager = resource_manager.ResourceManager


def test_shutdown_handles_keyboardinterrupt(monkeypatch):
    """ResourceManager.shutdown should swallow KeyboardInterrupt and
    still terminate the background thread."""

    mgr = ResourceManager(cleanup_interval=0)
    mgr.start_background_cleanup()

    # Ensure the cleanup thread is running
    assert mgr._cleanup_thread and mgr._cleanup_thread.is_alive()

    original_join = mgr._cleanup_thread.join
    call_count = {"count": 0}

    def flaky_join(timeout=None):  # pragma: no cover - behaviour tested via call_count
        call_count["count"] += 1
        if call_count["count"] == 1:
            raise KeyboardInterrupt()
        return original_join(timeout)

    monkeypatch.setattr(mgr._cleanup_thread, "join", flaky_join)

    # Should not raise despite the KeyboardInterrupt from join
    mgr.shutdown()

    # Join should have been attempted more than once
    assert call_count["count"] >= 2
    # Cleanup thread reference is cleared after shutdown
    assert mgr._cleanup_thread is None
