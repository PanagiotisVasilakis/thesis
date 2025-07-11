from unittest.mock import MagicMock, patch


def test_predict_route(client):
    mock_model = MagicMock()
    mock_model.extract_features.return_value = {"f": 1}
    mock_model.predict.return_value = {"antenna_id": "antenna_1", "confidence": 0.9}

    with patch("ml_service.app.api.routes.load_model", return_value=mock_model) as mock_get, \
         patch("ml_service.app.api.routes.track_prediction") as mock_track:
        resp = client.post("/api/predict", json={"ue_id": "u1"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["predicted_antenna"] == "antenna_1"
        assert data["confidence"] == 0.9
        mock_get.assert_called_once_with(client.application.config["MODEL_PATH"])
        mock_track.assert_called_once_with("antenna_1", 0.9)


def test_predict_invalid_request(client):
    mock_model = MagicMock()
    with patch("ml_service.app.api.routes.load_model", return_value=mock_model):
        resp = client.post("/api/predict", json={})
        assert resp.status_code == 400


def test_train_route(client):
    mock_model = MagicMock()
    mock_model.train.return_value = {"samples": 1, "classes": 1}
    mock_model.save.return_value = True

    with patch("ml_service.app.api.routes.load_model", return_value=mock_model) as mock_get, \
         patch("ml_service.app.api.routes.track_training") as mock_track:
        resp = client.post("/api/train", json=[{"optimal_antenna": "a1"}])
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["metrics"]["samples"] == 1
        mock_model.train.assert_called_once()
        mock_model.save.assert_called_once()
        mock_get.assert_called_once_with(client.application.config["MODEL_PATH"])
        mock_track.assert_called_once()


def test_train_invalid_request(client):
    resp = client.post("/api/train", json={"foo": "bar"})
    assert resp.status_code == 400

    resp = client.post("/api/train", json=[{"foo": "bar"}])
    assert resp.status_code == 400


def test_nef_status(client):
    mock_response = MagicMock(status_code=200, headers={"X-API-Version": "v1"})
    with patch("ml_service.app.api.routes.requests.get", return_value=mock_response) as mock_get:
        resp = client.get("/api/nef-status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data == {"status": "connected", "nef_version": "v1"}
        mock_get.assert_called_once()


def test_collect_data_route(client, monkeypatch):
    collector = MagicMock()
    collector.login.return_value = True
    collector.get_ue_movement_state.return_value = {"ue": {}}
    collector.collect_training_data.return_value = [1, 2]
    monkeypatch.setattr("ml_service.app.api.routes.NEFDataCollector", lambda **kw: collector)

    resp = client.post(
        "/api/collect-data",
        json={"username": "u", "password": "p", "duration": 1, "interval": 1},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["samples"] == 2
    collector.login.assert_called_once()
    collector.collect_training_data.assert_called_once()

