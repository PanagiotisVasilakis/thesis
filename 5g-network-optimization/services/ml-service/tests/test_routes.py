from unittest.mock import MagicMock, patch
from datetime import datetime, timezone
from ml_service.app.clients.nef_client import NEFClientError


def test_predict_route(client, auth_header):
    mock_model = MagicMock()
    mock_model.extract_features.return_value = {"f": 1}
    mock_model.predict.return_value = {"antenna_id": "antenna_1", "confidence": 0.9}

    with patch(
        "ml_service.app.api.routes.load_model", return_value=mock_model
    ) as mock_get, patch(
        "ml_service.app.api.routes.track_prediction"
    ) as mock_track:
        resp = client.post("/api/predict", json={"ue_id": "u1"}, headers=auth_header)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["predicted_antenna"] == "antenna_1"
        assert data["confidence"] == 0.9
        mock_get.assert_called_once_with(client.application.config["MODEL_PATH"])
        mock_track.assert_called_once_with("antenna_1", 0.9)


def test_predict_invalid_request(client, auth_header):
    mock_model = MagicMock()
    with patch("ml_service.app.api.routes.load_model", return_value=mock_model):
        resp = client.post("/api/predict", json={}, headers=auth_header)
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["type"] == "RequestValidationError"
        assert data["correlation_id"]


def test_train_route(client, auth_header):
    mock_model = MagicMock()
    mock_model.train.return_value = {"samples": 1, "classes": 1}
    mock_model.save.return_value = True

    with patch(
        "ml_service.app.api.routes.load_model", return_value=mock_model
    ) as mock_get, patch(
        "ml_service.app.api.routes.track_training"
    ) as mock_track:
        resp = client.post("/api/train", json=[{"optimal_antenna": "a1"}], headers=auth_header)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["metrics"]["samples"] == 1
        mock_model.train.assert_called_once()
        mock_model.save.assert_called_once()
        mock_get.assert_called_once_with(client.application.config["MODEL_PATH"])
        mock_track.assert_called_once()


def test_train_invalid_request(client, auth_header):
    resp = client.post("/api/train", json={"foo": "bar"}, headers=auth_header)
    assert resp.status_code == 400
    assert resp.get_json()["type"] == "RequestValidationError"

    resp = client.post("/api/train", json=[{"foo": "bar"}], headers=auth_header)
    assert resp.status_code == 400
    assert resp.get_json()["type"] == "RequestValidationError"


def test_nef_status(client, auth_header):
    mock_client = MagicMock()
    mock_response = MagicMock(status_code=200, headers={"X-API-Version": "v1"})
    mock_client.get_status.return_value = mock_response
    with patch("ml_service.app.api.routes.NEFClient", return_value=mock_client):
        resp = client.get("/api/nef-status", headers=auth_header)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data == {"status": "connected", "nef_version": "v1"}
        mock_client.get_status.assert_called_once()


def test_nef_status_request_error(client, auth_header):
    mock_client = MagicMock()
    mock_client.get_status.side_effect = NEFClientError("boom")
    with patch("ml_service.app.api.routes.NEFClient", return_value=mock_client):
        resp = client.get("/api/nef-status", headers=auth_header)
        assert resp.status_code == 502
        data = resp.get_json()
        assert data["type"] == "NEFConnectionError"
        assert data["correlation_id"]


from unittest.mock import AsyncMock


def test_collect_data_route(client, auth_header, monkeypatch):
    collector = MagicMock()
    collector.login.return_value = True
    collector.get_ue_movement_state.return_value = {"ue": {}}
    collector.collect_training_data = AsyncMock(return_value=[1, 2])
    monkeypatch.setattr("ml_service.app.api.routes.NEFDataCollector", lambda **kw: collector)

    resp = client.post(
        "/api/collect-data",
        json={"username": "u", "password": "p", "duration": 1, "interval": 1},
        headers=auth_header,
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["samples"] == 2
    collector.login.assert_called_once()
    collector.collect_training_data.assert_awaited_once()


def test_collect_data_oserror(client, auth_header, monkeypatch):
    collector = MagicMock()
    collector.login.return_value = True
    collector.get_ue_movement_state.return_value = {"ue": {}}
    collector.collect_training_data = AsyncMock(return_value=[])
    collector.data_dir = "path"
    monkeypatch.setattr("ml_service.app.api.routes.NEFDataCollector", lambda **kw: collector)

    def raise_oserror(*a, **k):
        raise OSError("err")
    monkeypatch.setattr("ml_service.app.api.routes.Path.glob", raise_oserror)

    resp = client.post(
        "/api/collect-data",
        json={"username": "u", "password": "p"},
        headers=auth_header,
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["file"] is None
    collector.collect_training_data.assert_awaited_once()


def test_feedback_route(client, auth_header, monkeypatch):
    called = {}

    def fake_feed(sample, success=True):
        called.setdefault('count', 0)
        called['count'] += 1
        return False
    monkeypatch.setattr("ml_service.app.api.routes.ModelManager.feed_feedback", fake_feed)

    resp = client.post("/api/feedback", json={"optimal_antenna": "a1", "success": True}, headers=auth_header)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["samples"] == 1
    assert called['count'] == 1


def test_model_health(client, monkeypatch):
    ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr("ml_service.app.api.routes.ModelManager.is_ready", lambda: True)
    monkeypatch.setattr(
        "ml_service.app.api.routes.ModelManager.get_metadata",
        lambda: {"trained_at": ts.isoformat(), "metrics": {"samples": 5}, "version": "1.0"},
    )

    resp = client.get("/api/model-health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ready"] is True
    assert data["metadata"]["version"] == "1.0"
    assert data["metadata"]["metrics"] == {"samples": 5}
    assert data["metadata"]["trained_at"] == ts.isoformat()
