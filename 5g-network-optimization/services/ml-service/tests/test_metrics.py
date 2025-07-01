from flask import Flask

from ml_service.monitoring import metrics
from ml_service.monitoring.metrics import MetricsMiddleware, track_prediction, track_training


def test_metrics_middleware_counts_success():
    app = Flask(__name__)

    @app.route("/api/test")
    def _test():
        return "ok"

    app.wsgi_app = MetricsMiddleware(app.wsgi_app)
    client = app.test_client()

    before = metrics.PREDICTION_REQUESTS.labels(status="success")._value.get()
    resp = client.get("/api/test")
    assert resp.status_code == 200
    after = metrics.PREDICTION_REQUESTS.labels(status="success")._value.get()
    assert after == before + 1


def test_track_prediction_updates_metrics():
    before = metrics.ANTENNA_PREDICTIONS.labels(antenna_id="a1")._value.get()
    track_prediction("a1", 0.5)
    after = metrics.ANTENNA_PREDICTIONS.labels(antenna_id="a1")._value.get()
    confidence = metrics.PREDICTION_CONFIDENCE.labels(antenna_id="a1")._value.get()
    assert after == before + 1
    assert confidence == 0.5


def test_track_training_updates_metrics():
    sum_before = metrics.MODEL_TRAINING_DURATION._sum.get()
    track_training(1.2, 10, accuracy=0.9)
    sum_after = metrics.MODEL_TRAINING_DURATION._sum.get()
    samples = metrics.MODEL_TRAINING_SAMPLES._value.get()
    accuracy = metrics.MODEL_TRAINING_ACCURACY._value.get()
    assert sum_after == sum_before + 1.2
    assert samples == 10
    assert accuracy == 0.9
