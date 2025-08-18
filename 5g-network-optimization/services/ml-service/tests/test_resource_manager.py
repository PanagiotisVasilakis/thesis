"""Tests for the ResourceManager utility."""

import logging
import threading

from ml_service.app.utils.resource_manager import ResourceManager, ResourceType


class DummyResource:
    """Simple resource implementing cleanup for testing."""

    def __init__(self):
        self.cleaned = False

    def cleanup(self):
        self.cleaned = True

    def is_active(self):
        return True


def create_manager():
    """Create a ResourceManager instance without background threads."""
    return ResourceManager(cleanup_interval=0, enable_gc_monitoring=False)


def test_unregister_existing_resource():
    """Resources are removed and cleaned when unregistered."""
    manager = create_manager()
    resource = DummyResource()
    resource_id = manager.register_resource(resource, ResourceType.OTHER)

    assert resource_id in manager._resources

    result = manager.unregister_resource(resource_id)

    assert result is True
    assert resource_id not in manager._resources
    assert resource.cleaned is True


def test_unregister_missing_resource_logs_warning(caplog):
    """Unregistering a missing resource returns False and logs a warning."""
    manager = create_manager()

    with caplog.at_level(logging.WARNING):
        result = manager.unregister_resource("missing-id")

    assert result is False
    assert any(
        "Resource missing-id not found for unregistration" in record.message
        for record in caplog.records
    )


def test_concurrent_unregistration_thread_safety():
    """Unregistering multiple resources from different threads is safe."""
    manager = create_manager()

    # Register multiple resources
    resources = [DummyResource() for _ in range(10)]
    resource_ids = [manager.register_resource(r, ResourceType.OTHER) for r in resources]

    results = []
    def worker(rid):
        results.append(manager.unregister_resource(rid))

    threads = [threading.Thread(target=worker, args=(rid,)) for rid in resource_ids]

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert all(results)
    assert manager._resources == {}
