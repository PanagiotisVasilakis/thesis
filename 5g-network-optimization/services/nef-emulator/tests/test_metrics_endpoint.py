from fastapi import FastAPI, Response
from fastapi.testclient import TestClient
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from backend.app.app.monitoring import metrics


def create_app():
    app = FastAPI()

    @app.get("/metrics")
    def metrics_route() -> Response:
        return Response(generate_latest(metrics.REGISTRY), media_type=CONTENT_TYPE_LATEST)

    return app


def test_metrics_endpoint_returns_data():
    app = create_app()
    client = TestClient(app)
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert "nef_request_duration_seconds" in resp.text
