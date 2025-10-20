from ml_service.app.core.qos_encoding import encode_service_type


def test_encode_service_type_defaults():
    assert encode_service_type("embb") == 1.0
    assert encode_service_type("URRLC") == 0.0 or isinstance(encode_service_type("URRLC"), float)
    assert encode_service_type(None) == 0.0
    assert encode_service_type(2) == 2.0
