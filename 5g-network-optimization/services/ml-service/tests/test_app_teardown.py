from unittest.mock import MagicMock

from ml_service.app import create_app


def test_metrics_collector_stops_on_teardown(monkeypatch):
    collector = MagicMock()
    # ensure start/stop can be called
    collector.start = MagicMock()
    collector.stop = MagicMock()
    monkeypatch.setattr("ml_service.app.MetricsCollector", lambda: collector)

    app = create_app({"TESTING": True})
    with app.app_context():
        pass
    collector.stop.assert_called_once()
