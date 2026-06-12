import pytest


def test_create_app_requires_runtime_config(monkeypatch):
    from ml_service.app import create_app

    for key in (
        "NEF_API_URL",
        "SECRET_KEY",
        "JWT_SECRET",
        "JWT_REFRESH_SECRET",
        "AUTH_USERNAME",
        "AUTH_PASSWORD",
    ):
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(ValueError, match="Missing required runtime configuration"):
        create_app()


def test_create_app_uses_runtime_env(monkeypatch):
    from ml_service.app import create_app
    from ml_service.app.initialization.model_init import ModelManager

    monkeypatch.setenv("NEF_API_URL", "http://nef-emulator:80")
    monkeypatch.setenv("SECRET_KEY", "runtime-secret-key-for-tests-000001")
    monkeypatch.setenv("JWT_SECRET", "runtime-jwt-secret-for-tests-000001")
    monkeypatch.setenv("JWT_REFRESH_SECRET", "runtime-refresh-secret-for-tests-000001")
    monkeypatch.setenv("AUTH_USERNAME", "ml-admin")
    monkeypatch.setenv("AUTH_PASSWORD", "MlPassword123")
    monkeypatch.setenv("RATELIMIT_PREDICT", "3000 per minute")
    monkeypatch.setenv("RATELIMIT_FEEDBACK", "3000 per minute")
    monkeypatch.setattr(ModelManager, "initialize", lambda *args, **kwargs: None)

    app = create_app()

    assert app.config["NEF_API_URL"] == "http://nef-emulator:80"
    assert app.config["JWT_SECRET"] == "runtime-jwt-secret-for-tests-000001"
    assert app.config["JWT_REFRESH_SECRET"] == "runtime-refresh-secret-for-tests-000001"
    assert app.config["RATE_LIMITS"]["predict"] == "3000 per minute"
    assert app.config["RATE_LIMITS"]["feedback"] == "3000 per minute"
