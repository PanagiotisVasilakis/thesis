import importlib.util
import sys
from unittest.mock import MagicMock

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


@pytest.fixture
def auth_header(client):
    import os
    # Use environment variables for test credentials with secure defaults
    test_username = os.getenv("TEST_AUTH_USERNAME", "test_user")
    test_password = os.getenv("TEST_AUTH_PASSWORD", "test_secure_password_123!")
    
    resp = client.post(
        "/api/login",
        json={"username": test_username, "password": test_password},
    )
    assert resp.status_code == 200
    token = resp.get_json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def mock_nef_client():
    """Provide a preconfigured mock for :class:`NEFClient` interactions.

    The fixture returns a :class:`~unittest.mock.MagicMock` instance with
    sensible defaults for the methods most tests rely on. Each test may
    override these defaults as needed.

    Returns:
        MagicMock: Mocked NEF client with common methods stubbed out.
    """

    mock = MagicMock()
    # Simulate a healthy NEF service by default
    mock.get_status.return_value = MagicMock(status_code=200)
    mock.login.return_value = True
    mock.token = "test-token"
    mock.get_headers.return_value = {"Authorization": "Bearer test-token"}
    mock.get_ue_movement_state.return_value = {}
    mock.get_feature_vector.return_value = {}
    return mock
