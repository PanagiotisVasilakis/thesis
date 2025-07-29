from app.core import security
from app import crud
from app.api import deps
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
from fastapi.testclient import TestClient
from pydantic import BaseModel

# Stub external dependencies before importing the application
sys.modules.setdefault("emails", types.ModuleType("emails"))
sys.modules.setdefault("emails.message", types.ModuleType("emails.message"))
tmpl_mod = types.ModuleType("emails.template")
tmpl_mod.JinjaTemplate = lambda x: x
sys.modules.setdefault("emails.template", tmpl_mod)
sys.modules["emails"].Message = lambda *a, **k: SimpleNamespace(
    send=lambda **kw: None)

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

# Fix mismatched response models


class SimpleMsg(BaseModel):
    msg: str


for route in login_endpoints.router.routes:
    if route.name in {"recover_password", "reset_password"}:
        route.response_model = SimpleMsg

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

    client = TestClient(app)
    response = client.post("/api/v1/login/access-token",
                           data={"username": "user@example.com", "password": "secret"})
    assert response.status_code == 200
    assert response.json() == {"access_token": "tok", "token_type": "bearer"}


def test_login_access_token_bad_credentials(monkeypatch):
    monkeypatch.setattr(crud.user, "authenticate",
                        lambda db, email, password: None)

    client = TestClient(app)
    response = client.post("/api/v1/login/access-token",
                           data={"username": "user@example.com", "password": "wrong"})
    assert response.status_code == 400
    assert response.json()["detail"] == "Incorrect email or password"


def test_login_access_token_inactive_user(monkeypatch):
    user = FakeUser(id=1)
    monkeypatch.setattr(crud.user, "authenticate",
                        lambda db, email, password: user)
    monkeypatch.setattr(crud.user, "is_active", lambda u: False)

    client = TestClient(app)
    response = client.post("/api/v1/login/access-token",
                           data={"username": "user@example.com", "password": "secret"})
    assert response.status_code == 400
    assert response.json()["detail"] == "Inactive user"


def test_recover_password(monkeypatch):
    user = FakeUser(email="user@example.com")
    monkeypatch.setattr(crud.user, "get_by_email", lambda db, email: user)
    monkeypatch.setattr(
        login_endpoints, "generate_password_reset_token", lambda *a, **k: "tok")
    monkeypatch.setattr(
        login_endpoints, "send_reset_password_email", lambda **kw: None)

    client = TestClient(app)
    response = client.post("/api/v1/password-recovery/user@example.com")
    assert response.status_code == 200
    assert response.json() == {"msg": "Password recovery email sent"}


def test_recover_password_user_not_found(monkeypatch):
    monkeypatch.setattr(crud.user, "get_by_email", lambda db, email: None)

    client = TestClient(app)
    response = client.post("/api/v1/password-recovery/none@example.com")
    assert response.status_code == 404
    assert response.json()[
        "detail"] == "The user with this username does not exist in the system."


def test_reset_password(monkeypatch):
    user = FakeUser(email="user@example.com",
                    hashed_password="old", is_active=True)
    monkeypatch.setattr(
        login_endpoints, "verify_password_reset_token", lambda token: "user@example.com")
    monkeypatch.setattr(crud.user, "get_by_email", lambda db, email: user)
    monkeypatch.setattr(login_endpoints, "get_password_hash",
                        lambda pw: f"hashed-{pw}")

    client = TestClient(app)
    response = client.post("/api/v1/reset-password/",
                           json={"token": "tok", "new_password": "new"})
    assert response.status_code == 200
    assert response.json() == {"msg": "Password updated successfully"}
    assert user.hashed_password == "hashed-new"


def test_reset_password_invalid_token(monkeypatch):
    monkeypatch.setattr(
        login_endpoints, "verify_password_reset_token", lambda token: None)

    client = TestClient(app)
    response = client.post("/api/v1/reset-password/",
                           json={"token": "bad", "new_password": "x"})
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid token"


def test_reset_password_user_not_found(monkeypatch):
    monkeypatch.setattr(
        login_endpoints, "verify_password_reset_token", lambda token: "user@example.com")
    monkeypatch.setattr(crud.user, "get_by_email", lambda db, email: None)

    client = TestClient(app)
    response = client.post("/api/v1/reset-password/",
                           json={"token": "tok", "new_password": "pass"})
    assert response.status_code == 404
    assert response.json()[
        "detail"] == "The user with this username does not exist in the system."


def test_reset_password_inactive_user(monkeypatch):
    user = FakeUser(email="user@example.com", is_active=False)
    monkeypatch.setattr(
        login_endpoints, "verify_password_reset_token", lambda token: "user@example.com")
    monkeypatch.setattr(crud.user, "get_by_email", lambda db, email: user)
    monkeypatch.setattr(crud.user, "is_active", lambda u: False)

    client = TestClient(app)
    response = client.post("/api/v1/reset-password/",
                           json={"token": "tok", "new_password": "pass"})
    assert response.status_code == 400
    assert response.json()["detail"] == "Inactive user"


def teardown_module(module):
    """Clean up dynamically loaded ``app`` modules after tests."""
    for name in list(sys.modules.keys()):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]
