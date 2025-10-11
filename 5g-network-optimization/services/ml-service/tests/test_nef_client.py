import pytest
import requests
from requests.adapters import HTTPAdapter

from ml_service.app.clients.nef_client import NEFClient, NEFClientError


def test_get_headers_without_token(dummy_http_client):
    client = NEFClient(base_url="http://nef", http_client=dummy_http_client)
    assert client.get_headers() == {"Content-Type": "application/json"}


def test_get_headers_with_token(dummy_http_client):
    client = NEFClient(base_url="http://nef", http_client=dummy_http_client)
    client.token = "tok"
    headers = client.get_headers()
    assert headers["Authorization"] == "Bearer tok"
    assert headers["Content-Type"] == "application/json"


def test_login_success(dummy_http_client):
    client = NEFClient(base_url="http://nef", username="u", password="p", http_client=dummy_http_client)

    class MockResp:
        status_code = 200
        text = ""

        def json(self):
            return {"access_token": "tok"}

    def mock_post(url, data=None, timeout=None):
        return MockResp()

    dummy_http_client.post = mock_post
    assert client.login() is True
    assert client.token == "tok"


def test_login_failure(dummy_http_client):
    client = NEFClient(base_url="http://nef", username="u", password="p", http_client=dummy_http_client)

    class MockResp:
        status_code = 401
        text = "error"

        def json(self):
            return {}

    dummy_http_client.post = lambda url, data=None, timeout=None: MockResp()
    assert client.login() is False
    assert client.token is None


def test_login_request_error(dummy_http_client):
    client = NEFClient(base_url="http://nef", username="u", password="p", http_client=dummy_http_client)

    def raise_exc(*_args, **_kwargs):
        raise requests.exceptions.RequestException("boom")

    dummy_http_client.post = raise_exc
    with pytest.raises(NEFClientError):
        client.login()


def test_login_unexpected_error(dummy_http_client):
    client = NEFClient(base_url="http://nef", username="u", password="p", http_client=dummy_http_client)

    def raise_exc(*_args, **_kwargs):
        raise ValueError("boom")

    dummy_http_client.post = raise_exc
    with pytest.raises(ValueError) as exc_info:
        client.login()
    assert str(exc_info.value) == "boom"


def test_generate_mobility_pattern_success(dummy_http_client):
    client = NEFClient(base_url="http://nef", http_client=dummy_http_client)

    class MockResp:
        status_code = 200

        def json(self):
            return [{"x": 1}]

    def mock_post(url, json=None, headers=None, timeout=None):
        return MockResp()

    dummy_http_client.post = mock_post
    result = client.generate_mobility_pattern("linear", "u1", {"speed": 1})
    assert result == [{"x": 1}]


def test_generate_mobility_pattern_failure(dummy_http_client):
    client = NEFClient(base_url="http://nef", http_client=dummy_http_client)

    class MockResp:
        status_code = 400
        text = "bad"

    dummy_http_client.post = lambda *_args, **_kwargs: MockResp()
    result = client.generate_mobility_pattern("linear", "u1", {"speed": 1})
    assert result is None


def test_generate_mobility_pattern_request_error(dummy_http_client):
    client = NEFClient(base_url="http://nef", http_client=dummy_http_client)

    def raise_exc(*_args, **_kwargs):
        raise requests.exceptions.RequestException("boom")

    dummy_http_client.post = raise_exc
    with pytest.raises(NEFClientError):
        client.generate_mobility_pattern("linear", "u1", {"speed": 1})


def test_generate_mobility_pattern_unexpected_error(dummy_http_client):
    client = NEFClient(base_url="http://nef", http_client=dummy_http_client)

    def raise_exc(*_args, **_kwargs):
        raise ValueError("boom")

    dummy_http_client.post = raise_exc
    with pytest.raises(ValueError) as exc_info:
        client.generate_mobility_pattern("linear", "u1", {"speed": 1})
    assert str(exc_info.value) == "boom"


def test_get_ue_movement_state_success(dummy_http_client):
    client = NEFClient(base_url="http://nef", http_client=dummy_http_client)

    class MockResp:
        status_code = 200

        def json(self):
            return {"u1": {"x": 1}}

    def mock_get(url, headers=None, timeout=None):
        return MockResp()

    dummy_http_client.get = mock_get
    result = client.get_ue_movement_state()
    assert result == {"u1": {"x": 1}}


def test_get_ue_movement_state_failure(dummy_http_client):
    client = NEFClient(base_url="http://nef", http_client=dummy_http_client)

    class MockResp:
        status_code = 500
        text = "err"

    dummy_http_client.get = lambda *_args, **_kwargs: MockResp()
    result = client.get_ue_movement_state()
    assert result == {}


def test_get_ue_movement_state_request_error(dummy_http_client):
    client = NEFClient(base_url="http://nef", http_client=dummy_http_client)

    def raise_exc(*_args, **_kwargs):
        raise requests.exceptions.RequestException("boom")

    dummy_http_client.get = raise_exc
    with pytest.raises(NEFClientError):
        client.get_ue_movement_state()


def test_get_ue_movement_state_unexpected_error(dummy_http_client):
    client = NEFClient(base_url="http://nef", http_client=dummy_http_client)

    def raise_exc(*_args, **_kwargs):
        raise RuntimeError("boom")

    dummy_http_client.get = raise_exc
    with pytest.raises(RuntimeError) as exc_info:
        client.get_ue_movement_state()
    assert str(exc_info.value) == "boom"


def test_get_feature_vector_success(dummy_http_client):
    client = NEFClient(base_url="http://nef", http_client=dummy_http_client)

    class MockResp:
        status_code = 200

        def json(self):
            return {"neighbor_rsrp_dbm": {"A": -80}}

    dummy_http_client.get = lambda *_args, **_kwargs: MockResp()
    result = client.get_feature_vector("ue1")
    assert result == {"neighbor_rsrp_dbm": {"A": -80}}


def test_get_feature_vector_failure(dummy_http_client):
    client = NEFClient(base_url="http://nef", http_client=dummy_http_client)

    class MockResp:
        status_code = 404
        text = "err"

    dummy_http_client.get = lambda *_args, **_kwargs: MockResp()
    result = client.get_feature_vector("ue1")
    assert result == {}


def test_get_feature_vector_request_error(dummy_http_client):
    client = NEFClient(base_url="http://nef", http_client=dummy_http_client)

    def raise_exc(*_args, **_kwargs):
        raise requests.exceptions.RequestException("boom")

    dummy_http_client.get = raise_exc
    with pytest.raises(NEFClientError):
        client.get_feature_vector("ue1")


def test_get_feature_vector_unexpected_error(dummy_http_client):
    client = NEFClient(base_url="http://nef", http_client=dummy_http_client)

    def raise_exc(*_args, **_kwargs):
        raise ZeroDivisionError()

    dummy_http_client.get = raise_exc
    with pytest.raises(ZeroDivisionError) as exc_info:
        client.get_feature_vector("ue1")
    assert exc_info.value.args == ()


def test_default_client_configures_connection_pooling():
    client = NEFClient(base_url="http://nef")
    try:
        assert isinstance(client.session, requests.Session)
        adapter = client.session.get_adapter("http://nef")
        assert isinstance(adapter, HTTPAdapter)
    finally:
        client.close()
