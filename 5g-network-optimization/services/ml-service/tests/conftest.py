import importlib.util
import sys

import matplotlib
import pytest

matplotlib.use("Agg")

try:
    import seaborn  # noqa: F401
except ImportError:  # pragma: no cover - optional dependency
    sys.modules["seaborn"] = importlib.util.module_from_spec(
        importlib.util.spec_from_loader("seaborn", loader=None)
    )

from ml_service import create_app


@pytest.fixture
def app():
    yield create_app({"TESTING": True})


@pytest.fixture
def client(app):
    return app.test_client()
