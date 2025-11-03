import pytest

from ml_service.app.api_lib import predict
from ml_service.app.monitoring import metrics


def test_predict_includes_qos_compliance(monkeypatch):
    # Create a minimal dummy model with predictable behavior
    class DummyModel:
        def extract_features(self, data):
            return {"ue_id": data.get("ue_id", "u1")}

        def predict(self, features):
            # Return a fixed high-confidence result
            return {"antenna_id": "a1", "confidence": 0.9}

    dummy = DummyModel()

    # QoS with high priority should require higher threshold; with
    # confidence=0.9 it should typically be compliant for moderate priorities
    req = {"ue_id": "u1", "service_type": "embb", "service_priority": 5}

    passed_counter = metrics.QOS_COMPLIANCE_CHECKS.labels(service_type="embb", outcome="passed")._value.get()
    result, features = predict(req, model=dummy)
    assert "qos_compliance" in result
    assert isinstance(result["qos_compliance"], dict)
    assert "service_priority_ok" in result["qos_compliance"]
    assert metrics.QOS_COMPLIANCE_CHECKS.labels(service_type="embb", outcome="passed")._value.get() == passed_counter + 1

    # If we set an extremely high required priority, compliance may fail
    req_high = {"ue_id": "u1", "service_type": "embb", "service_priority": 10}
    failed_counter = metrics.QOS_COMPLIANCE_CHECKS.labels(service_type="embb", outcome="failed")._value.get()
    violation_counter = metrics.QOS_VIOLATION_REASONS.labels(service_type="embb", metric="latency")._value.get()
    result_high, _ = predict(req_high, model=dummy)
    assert "qos_compliance" in result_high
    assert isinstance(result_high["qos_compliance"], dict)
    assert "observed_confidence" in result_high["qos_compliance"]
    assert result_high["qos_compliance"]["confidence_ok"] is False
    assert metrics.QOS_COMPLIANCE_CHECKS.labels(service_type="embb", outcome="failed")._value.get() == failed_counter + 1
    # Confidence failure should not record metric-level violations
    assert metrics.QOS_VIOLATION_REASONS.labels(service_type="embb", metric="latency")._value.get() == violation_counter
