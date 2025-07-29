import importlib
import sys

ENV = {
    "SERVER_NAME": "test",
    "SERVER_HOST": "localhost",
    "POSTGRES_SERVER": "localhost",
    "POSTGRES_USER": "user",
    "POSTGRES_PASSWORD": "pass",
    "POSTGRES_DB": "db",
    "MONGO_CLIENT": "mongodb://localhost",
    "CAPIF_HOST": "localhost",
    "CAPIF_HTTP_PORT": "8080",
    "CAPIF_HTTPS_PORT": "8443",
    "FIRST_SUPERUSER": "admin@example.com",
    "FIRST_SUPERUSER_PASSWORD": "pass",
    "USE_PUBLIC_KEY_VERIFICATION": "0",
    "BACKEND_CORS_ORIGINS": "[\"http://localhost\", \"http://example.com\"]",
}


def _load_config():
    module_name = "backend.app.app.core.config"
    if module_name in sys.modules:
        return importlib.reload(sys.modules[module_name])
    return importlib.import_module(module_name)


def test_settings_parsing(monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)

    config = _load_config()
    settings = config.Settings()

    assert (
        settings.SQLALCHEMY_DATABASE_URI
        == "postgresql://user:pass@localhost/db"
    )
    assert settings.BACKEND_CORS_ORIGINS == [
        "http://localhost",
        "http://example.com",
    ]


def test_qos_settings_import(monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)

    config = _load_config()
    qos = config.QoSSettings()
    data = qos.retrieve_settings()

    assert "5qi" in data
    assert isinstance(data["5qi"], list)
    assert any("value" in entry for entry in data["5qi"])


def test_multiple_settings_import(monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)

    cfg1 = _load_config()
    settings1 = cfg1.Settings()

    cfg2 = _load_config()
    settings2 = cfg2.Settings()

    assert (
        settings2.SQLALCHEMY_DATABASE_URI
        == settings1.SQLALCHEMY_DATABASE_URI
    )
