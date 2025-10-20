from ml_service.app.schemas import PredictionRequestWithQoS


def test_prediction_request_with_qos_valid():
    data = {
        "ue_id": "u1",
        "latitude": 1.0,
        "longitude": 2.0,
        "connected_to": "A",
        "rf_metrics": {"A": {"rsrp": -80.0, "sinr": 10.0}},
        "service_type": "urllc",
        "qos_requirements": {"latency_ms": 10.0, "throughput_mbps": 1.0, "reliability_pct": 99.9},
        "service_priority": 9,
    }

    model = PredictionRequestWithQoS.model_validate(data)
    assert model.ue_id == "u1"
    assert model.service_type == "urllc"
    assert model.service_priority == 9


def test_prediction_request_with_qos_invalid_service_priority():
    data = {
        "ue_id": "u1",
        "service_type": "embb",
        "service_priority": 100,
    }
    try:
        PredictionRequestWithQoS.model_validate(data)
        assert False, "validation should have failed for service_priority"
    except Exception:
        assert True
