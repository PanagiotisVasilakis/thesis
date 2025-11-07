from app import crud
import importlib.util
import os
import sys
import types
from types import SimpleNamespace
from pathlib import Path

try:
    import sqlalchemy
except ImportError:  # pragma: no cover - optional dependency
    sqlalchemy = types.ModuleType("sqlalchemy")
    sys.modules["sqlalchemy"] = sqlalchemy
    sqlalchemy.orm = types.ModuleType("sqlalchemy.orm")
    sqlalchemy.orm.Session = object
    sys.modules["sqlalchemy.orm"] = sqlalchemy.orm

try:
    import pymongo
except ImportError:  # pragma: no cover - optional dependency
    pymongo = types.ModuleType("pymongo")
    sys.modules["pymongo"] = pymongo
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.testclient import TestClient as FastAPITestClient
from httpx import ASGITransport


class TestClient(FastAPITestClient):
    def __init__(self, *, transport: ASGITransport, **kwargs):
        super().__init__(transport.app, **kwargs)

# Stub external dependencies before importing the application
openssl = types.ModuleType("OpenSSL")
openssl.crypto = SimpleNamespace(
    FILETYPE_PEM=None,
    load_certificate=lambda *a, **k: SimpleNamespace(get_pubkey=lambda: None),
    dump_publickey=lambda *a, **k: None,
)
sys.modules.setdefault("OpenSSL", openssl)

pymongo.MongoClient = lambda *a, **k: None
sqlalchemy.create_engine = lambda *a, **k: None

# Load environment variables required by app.core.config
PROJECT_ROOT = Path(__file__).resolve().parents[4]
load_dotenv(PROJECT_ROOT / ".env")
os.environ.setdefault("USE_PUBLIC_KEY_VERIFICATION", "false")

# Remove any previously loaded ``app`` modules to avoid cross-test interference
for name in list(sys.modules.keys()):
    if name == "app" or name.startswith("app."):
        del sys.modules[name]

# Dynamically load the ``app`` package so the real routers are available
BACKEND_ROOT = PROJECT_ROOT / "services" / "nef-emulator" / "backend"
APP_ROOT = BACKEND_ROOT / "app"
spec = importlib.util.spec_from_file_location(
    "app", APP_ROOT / "app" / "__init__.py", submodule_search_locations=[str(APP_ROOT / "app")]
)
app_pkg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app_pkg)
sys.modules["app"] = app_pkg
crud_module = types.ModuleType("app.crud")
crud_module.user = SimpleNamespace(
    authenticate=lambda *a, **k: None,
    is_active=lambda u: True,
    get_by_email=lambda *a, **k: None,
)
crud_module.crud_mongo = SimpleNamespace()
crud_module.ue = SimpleNamespace()
crud_module.gnb = SimpleNamespace()
sys.modules["app.crud"] = crud_module
crud = crud_module

# Import after stubbing
login_path = APP_ROOT / "app" / "api" / "api_v1" / "endpoints" / "login.py"
spec_login = importlib.util.spec_from_file_location(
    "login_endpoints", login_path)
login_endpoints = importlib.util.module_from_spec(spec_login)
spec_login.loader.exec_module(login_endpoints)

# Build FastAPI app with dependency overrides
app = FastAPI()
app.include_router(login_endpoints.router, prefix="/api/v1")


def override_get_db():
    class DummyDB:
        def add(self, obj):
            pass

        def commit(self):
            pass

        def close(self):
            pass

    yield DummyDB()


app.dependency_overrides[login_endpoints.deps.get_db] = override_get_db


class FakeUser(SimpleNamespace):
    pass


def test_login_access_token_success(monkeypatch):
    user = FakeUser(id=1)
    monkeypatch.setattr(crud.user, "authenticate",
                        lambda db, email, password: user)
    monkeypatch.setattr(crud.user, "is_active", lambda u: True)
    monkeypatch.setattr(login_endpoints.security, "create_access_token",
                        lambda uid, expires_delta=None: "tok")
    monkeypatch.setattr(login_endpoints.settings,
                        "ACCESS_TOKEN_EXPIRE_MINUTES", 15, raising=False)

    client = TestClient(transport=ASGITransport(app=app))
    response = client.post("/api/v1/login/access-token",
                           data={"username": "user@example.com", "password": "secret"})
    assert response.status_code == 200
    assert response.json() == {"access_token": "tok", "token_type": "bearer"}


def test_login_access_token_bad_credentials(monkeypatch):
    monkeypatch.setattr(crud.user, "authenticate",
                        lambda db, email, password: None)

    client = TestClient(transport=ASGITransport(app=app))
    response = client.post("/api/v1/login/access-token",
                           data={"username": "user@example.com", "password": "wrong"})
    assert response.status_code == 400
    assert response.json()["detail"] == "Incorrect email or password"


def test_login_access_token_inactive_user(monkeypatch):
    user = FakeUser(id=1)
    monkeypatch.setattr(crud.user, "authenticate",
                        lambda db, email, password: user)
    monkeypatch.setattr(crud.user, "is_active", lambda u: False)

    client = TestClient(transport=ASGITransport(app=app))
    response = client.post("/api/v1/login/access-token",
                           data={"username": "user@example.com", "password": "secret"})
    assert response.status_code == 400
    assert response.json()["detail"] == "Inactive user"


def teardown_module(module):
    """Clean up dynamically loaded ``app`` modules after tests."""
    for name in list(sys.modules.keys()):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]
