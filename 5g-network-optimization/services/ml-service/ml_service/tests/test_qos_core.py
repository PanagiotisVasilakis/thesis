import pytest

from ml_service.app.core.qos import qos_from_request, DEFAULT_SERVICE_PRESETS
from ml_service.app.models.antenna_selector import AntennaSelector


def test_qos_from_request_defaults():
    payload = {"service_type": "urllc"}
    qos = qos_from_request(payload)
    preset = DEFAULT_SERVICE_PRESETS["urllc"]
    assert qos["service_type"] == "urllc"
    assert qos["service_priority"] == int(preset["service_priority"])


def test_extract_features_includes_qos(tmp_path):
    # Create a selector with default config and call extract_features with QoS fields
    selector = AntennaSelector(model_path=None, neighbor_count=0, config_path=str(tmp_path / "features.yaml"))

    # Provide input payload including a service_type and an explicit override
    payload = {
        "ue_id": "test-ue-1",
        "latitude": 100,
        "longitude": 200,
        "service_type": "embb",
        "latency_requirement_ms": 20.5,
    }

    features = selector.extract_features(payload, include_neighbors=False)

    # QoS-derived fields should be present
    assert "service_type" in features
    assert features["service_type"] == "embb"
    assert "latency_requirement_ms" in features
    assert features["latency_requirement_ms"] == 20.5
