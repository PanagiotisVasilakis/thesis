from pathlib import Path
import importlib.util
import sys
import pytest

# Ensure the service package can be imported as ``app`` before test collection.
SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))
# Remove potential alias from other test suites
sys.modules.pop("app", None)


def load_create_app():
    """Dynamically load the ``create_app`` factory without polluting ``sys.modules``.

    ``create_app`` expects imports from the ``app`` package.  To satisfy these
    while avoiding conflicts with other tests that also provide a package named
    ``app``, we temporarily register the loaded module under that name and
    clean it up afterwards.
    """

    spec = importlib.util.spec_from_file_location(
        "app",
        SERVICE_ROOT / "app" / "__init__.py",
        submodule_search_locations=[str(SERVICE_ROOT / "app")],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["app"] = module
    # Stub optional visualization dependency not present in test environment
    sys.modules.setdefault("seaborn", importlib.util.module_from_spec(importlib.util.spec_from_loader("seaborn", loader=None)))
    spec.loader.exec_module(module)
    create_app_fn = module.create_app

    def cleanup():
        for name in list(sys.modules.keys()):
            if name == "app" or name.startswith("app."):
                del sys.modules[name]

    return create_app_fn, cleanup

@pytest.fixture
def app():
    create_app, cleanup = load_create_app()
    app = create_app({'TESTING': True})
    try:
        yield app
    finally:
        cleanup()

@pytest.fixture
def client(app):
    return app.test_client()
