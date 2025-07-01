import importlib.util
import sys
import pytest
import matplotlib

matplotlib.use("Agg")


def load_create_app():
    """Return the ``create_app`` factory from the installed package."""

    # Stub optional visualization dependency not present in test environment
    sys.modules.setdefault(
        "seaborn",
        importlib.util.module_from_spec(importlib.util.spec_from_loader("seaborn", loader=None)),
    )

    from ml_service.app import create_app

    return create_app, lambda: None

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
