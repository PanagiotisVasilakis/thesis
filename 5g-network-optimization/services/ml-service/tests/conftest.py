import importlib.util
from pathlib import Path
import pytest

APP_INIT = Path(__file__).resolve().parents[1] / "app" / "__init__.py"
spec = importlib.util.spec_from_file_location("ml_app", APP_INIT)
ml_app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ml_app)
create_app = ml_app.create_app

@pytest.fixture
def app():
    app = create_app({'TESTING': True})
    return app

@pytest.fixture
def client(app):
    return app.test_client()
