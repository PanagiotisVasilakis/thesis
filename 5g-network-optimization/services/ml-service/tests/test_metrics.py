from flask import Flask
import json
import logging

from ml_service.app.monitoring import metrics
from ml_service.app.monitoring.metrics import (
    MetricsMiddleware,
    track_prediction,
    track_training,
    DataDriftMonitor,
    MetricsCollector,
)


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


def test_track_training_updates_metrics(tmp_path):
    sum_before = metrics.MODEL_TRAINING_DURATION._sum.get()
    feature_importance = {"f1": 0.25, "f2": 0.75}
    out_file = tmp_path / "fi.json"
    track_training(
        1.2,
        10,
        accuracy=0.9,
        feature_importance=feature_importance,
        store_path=str(out_file),
    )
    sum_after = metrics.MODEL_TRAINING_DURATION._sum.get()
    samples = metrics.MODEL_TRAINING_SAMPLES._value.get()
    accuracy = metrics.MODEL_TRAINING_ACCURACY._value.get()
    assert sum_after == sum_before + 1.2
    assert samples == 10
    assert accuracy == 0.9
    assert (
        metrics.FEATURE_IMPORTANCE.labels(feature="f1")._value.get() == 0.25
    )
    assert (
        metrics.FEATURE_IMPORTANCE.labels(feature="f2")._value.get() == 0.75
    )
    assert json.loads(out_file.read_text()) == feature_importance


def test_metrics_endpoint_exposes_counters(app):
    client = app.test_client()
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert b"ml_prediction_requests_total" in resp.data


def test_drift_monitor_detects_change():
    monitor = DataDriftMonitor(window_size=2)
    monitor.update({"f1": 1.0})
    monitor.update({"f1": 1.0})
    assert monitor.compute_drift() == 0.0  # establishes baseline
    monitor.update({"f1": 2.0})
    monitor.update({"f1": 2.0})
    drift = monitor.compute_drift()
    assert drift == 1.0


def test_drift_monitor_triggers_alert(caplog):
    monitor = DataDriftMonitor(window_size=2, thresholds={"f1": 0.5})

    monitor.update({"f1": 1.0})
    monitor.update({"f1": 1.0})
    monitor.compute_drift()  # establish baseline

    with caplog.at_level(logging.WARNING):
        monitor.update({"f1": 3.0})
        monitor.update({"f1": 3.0})
        monitor.compute_drift()

    assert any("f1" in r.message for r in caplog.records)


def test_metrics_collector_updates_error_rate(monkeypatch):
    collector = MetricsCollector(interval=0.01)
    collector.start()
    # simulate two successful requests
    metrics.PREDICTION_REQUESTS.labels(status="success").inc(2)
    # simulate one error
    metrics.PREDICTION_REQUESTS.labels(status="error").inc()
    collector._update_error_rate()
    assert metrics.ERROR_RATE._value.get() == 1 / 3
    collector.stop()
