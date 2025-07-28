import ml_service.app.clients.nef_client as nef_client
from ml_service.app.clients.nef_client import NEFClient
import requests
import pytest


def test_get_headers_without_token():
    client = NEFClient(base_url="http://nef")
    headers = client.get_headers()
    assert headers == {"Content-Type": "application/json"}


def test_get_headers_with_token():
    client = NEFClient(base_url="http://nef")
    client.token = "tok"
    headers = client.get_headers()
    assert headers["Authorization"] == "Bearer tok"
    assert headers["Content-Type"] == "application/json"


def test_login_success(monkeypatch):
    client = NEFClient(base_url="http://nef", username="u", password="p")

    class MockResp:
        status_code = 200
        text = ""

        def json(self):
            return {"access_token": "tok"}

    def mock_post(url, data, timeout):
        return MockResp()

    monkeypatch.setattr(nef_client.requests, "post", mock_post)
    assert client.login() is True
    assert client.token == "tok"


def test_login_failure(monkeypatch):
    client = NEFClient(base_url="http://nef", username="u", password="p")

    class MockResp:
        status_code = 401
        text = "error"

        def json(self):
            return {}

    monkeypatch.setattr(nef_client.requests, "post", lambda *a, **k: MockResp())
    assert client.login() is False
    assert client.token is None


def test_login_request_error(monkeypatch):
    client = NEFClient(base_url="http://nef", username="u", password="p")

    def raise_exc(*a, **k):
        raise requests.exceptions.RequestException("boom")

    monkeypatch.setattr(nef_client.requests, "post", raise_exc)
    assert client.login() is False


def test_login_unexpected_error(monkeypatch):
    client = NEFClient(base_url="http://nef", username="u", password="p")

    def raise_exc(*a, **k):
        raise ValueError("boom")

    monkeypatch.setattr(nef_client.requests, "post", raise_exc)
    with pytest.raises(ValueError):
        client.login()


def test_generate_mobility_pattern_success(monkeypatch):
    client = NEFClient(base_url="http://nef")

    class MockResp:
        status_code = 200

        def json(self):
            return [{"x": 1}]

    def mock_post(url, json, headers, timeout):
        return MockResp()

    monkeypatch.setattr(nef_client.requests, "post", mock_post)
    result = client.generate_mobility_pattern("linear", "u1", {"speed": 1})
    assert result == [{"x": 1}]


def test_generate_mobility_pattern_failure(monkeypatch):
    client = NEFClient(base_url="http://nef")

    class MockResp:
        status_code = 400
        text = "bad"

    monkeypatch.setattr(nef_client.requests, "post", lambda *a, **k: MockResp())
    result = client.generate_mobility_pattern("linear", "u1", {"speed": 1})
    assert result is None


def test_generate_mobility_pattern_request_error(monkeypatch):
    client = NEFClient(base_url="http://nef")

    def raise_exc(*a, **k):
        raise requests.exceptions.RequestException("boom")

    monkeypatch.setattr(nef_client.requests, "post", raise_exc)
    result = client.generate_mobility_pattern("linear", "u1", {"speed": 1})
    assert result is None


def test_generate_mobility_pattern_unexpected_error(monkeypatch):
    client = NEFClient(base_url="http://nef")

    def raise_exc(*a, **k):
        raise ValueError("boom")

    monkeypatch.setattr(nef_client.requests, "post", raise_exc)
    with pytest.raises(ValueError):
        client.generate_mobility_pattern("linear", "u1", {"speed": 1})


def test_get_ue_movement_state_success(monkeypatch):
    client = NEFClient(base_url="http://nef")

    class MockResp:
        status_code = 200

        def json(self):
            return {"u1": {"x": 1}}

    def mock_get(url, headers, timeout):
        return MockResp()

    monkeypatch.setattr(nef_client.requests, "get", mock_get)
    result = client.get_ue_movement_state()
    assert result == {"u1": {"x": 1}}


def test_get_ue_movement_state_failure(monkeypatch):
    client = NEFClient(base_url="http://nef")

    class MockResp:
        status_code = 500
        text = "err"

    monkeypatch.setattr(nef_client.requests, "get", lambda *a, **k: MockResp())
    result = client.get_ue_movement_state()
    assert result == {}


def test_get_ue_movement_state_request_error(monkeypatch):
    client = NEFClient(base_url="http://nef")

    def raise_exc(*a, **k):
        raise requests.exceptions.RequestException("boom")

    monkeypatch.setattr(nef_client.requests, "get", raise_exc)
    result = client.get_ue_movement_state()
    assert result == {}


def test_get_ue_movement_state_unexpected_error(monkeypatch):
    client = NEFClient(base_url="http://nef")

    def raise_exc(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(nef_client.requests, "get", raise_exc)
    with pytest.raises(RuntimeError):
        client.get_ue_movement_state()


def test_get_feature_vector_success(monkeypatch):
    client = NEFClient(base_url="http://nef")

    class MockResp:
        status_code = 200

        def json(self):
            return {"neighbor_rsrp_dbm": {"A": -80}}

    monkeypatch.setattr(nef_client.requests, "get", lambda *a, **k: MockResp())
    result = client.get_feature_vector("ue1")
    assert result == {"neighbor_rsrp_dbm": {"A": -80}}


def test_get_feature_vector_failure(monkeypatch):
    client = NEFClient(base_url="http://nef")

    class MockResp:
        status_code = 404
        text = "err"

    monkeypatch.setattr(nef_client.requests, "get", lambda *a, **k: MockResp())
    result = client.get_feature_vector("ue1")
    assert result == {}


def test_get_feature_vector_request_error(monkeypatch):
    client = NEFClient(base_url="http://nef")

    def raise_exc(*a, **k):
        raise requests.exceptions.RequestException("boom")

    monkeypatch.setattr(nef_client.requests, "get", raise_exc)
    result = client.get_feature_vector("ue1")
    assert result == {}


def test_get_feature_vector_unexpected_error(monkeypatch):
    client = NEFClient(base_url="http://nef")

    def raise_exc(*a, **k):
        raise ZeroDivisionError()

    monkeypatch.setattr(nef_client.requests, "get", raise_exc)
    with pytest.raises(ZeroDivisionError):
        client.get_feature_vector("ue1")
