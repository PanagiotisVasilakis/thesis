import types
from unittest.mock import MagicMock

from ml_service.app.initialization.model_init import ModelManager, FEEDBACK_BUFFER_LIMIT


def test_feedback_buffer_limit(monkeypatch):
    # Ensure a clean state
    ModelManager._feedback_data = []

    dummy_model = MagicMock()
    dummy_model.update = MagicMock()
    dummy_model.drift_detected.return_value = False
    dummy_model.retrain = MagicMock()

    # Avoid loading a real model instance
    monkeypatch.setattr(ModelManager, "get_instance", lambda *a, **k: dummy_model)

    # Feed more samples than the buffer limit
    for i in range(FEEDBACK_BUFFER_LIMIT + 5):
        ModelManager.feed_feedback({"optimal_antenna": "a", "seq": i}, success=True)

    assert len(ModelManager._feedback_data) == FEEDBACK_BUFFER_LIMIT
    # The oldest entries should have been discarded
    assert ModelManager._feedback_data[0]["seq"] == 5
