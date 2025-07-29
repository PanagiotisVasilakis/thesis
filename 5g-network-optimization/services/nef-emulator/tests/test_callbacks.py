from backend.app.app.tools import monitoring_callbacks, qos_callback
import json
import requests
import pytest
import sys
import types

# Provide minimal stub modules required by qos_callback import
app_pkg = sys.modules.setdefault("app", types.ModuleType("app"))

crud_mod = types.ModuleType("app.crud")
crud_mod.ue = types.SimpleNamespace()
app_pkg.crud = crud_mod
sys.modules.setdefault("app.crud", crud_mod)

api_pkg = types.ModuleType("app.api")
api_v1_pkg = types.ModuleType("app.api.api_v1")
endpoints_pkg = types.ModuleType("app.api.api_v1.endpoints")
qos_info_mod = types.ModuleType("app.api.api_v1.endpoints.qosInformation")
qos_info_mod.qos_reference_match = lambda ref: {"type": "GBR"}
endpoints_pkg.qosInformation = qos_info_mod
api_v1_pkg.endpoints = endpoints_pkg
api_pkg.api_v1 = api_v1_pkg
app_pkg.api = api_pkg
sys.modules.setdefault("app.api", api_pkg)
sys.modules.setdefault("app.api.api_v1", api_v1_pkg)
sys.modules.setdefault("app.api.api_v1.endpoints", endpoints_pkg)
sys.modules.setdefault("app.api.api_v1.endpoints.qosInformation", qos_info_mod)

db_session_mod = types.ModuleType("app.db.session")
db_session_mod.SessionLocal = lambda: None
app_pkg.db = types.ModuleType("app.db")
app_pkg.db.session = db_session_mod
sys.modules.setdefault("app.db", app_pkg.db)
sys.modules.setdefault("app.db.session", db_session_mod)


@pytest.fixture
def sample_ue():
    return {
        "external_identifier": "ue-ext",
        "ip_address_v4": "10.0.0.1",
        "cell_id_hex": "CELL123",
        "gnb_id_hex": "GNB001",
    }


def _patch_request(monkeypatch):
    calls = {}

    def fake_request(method, url, headers=None, data=None, timeout=None):
        calls['method'] = method
        calls['url'] = url
        calls['headers'] = headers
        calls['data'] = data
        calls['timeout'] = timeout
        return "response"

    monkeypatch.setattr(requests, "request", fake_request)
    return calls


def test_location_callback_payload(sample_ue, monkeypatch):
    calls = _patch_request(monkeypatch)
    monitoring_callbacks.location_callback(sample_ue, "http://cb", "sub")

    payload = json.loads(calls['data'])
    assert calls['method'] == "POST"
    assert calls['url'] == "http://cb"
    assert calls['timeout'] == (3.05, 27)
    assert payload == {
        "externalId": "ue-ext",
        "ipv4Addr": "10.0.0.1",
        "subscription": "sub",
        "monitoringType": "LOCATION_REPORTING",
        "locationInfo": {
            "cellId": "CELL123",
            "enodeBId": "GNB001",
        },
    }


def test_loss_of_connectivity_payload(sample_ue, monkeypatch):
    calls = _patch_request(monkeypatch)
    monitoring_callbacks.loss_of_connectivity_callback(
        sample_ue, "http://cb", "sub")

    payload = json.loads(calls['data'])
    assert payload["monitoringType"] == "LOSS_OF_CONNECTIVITY"
    assert payload["lossOfConnectReason"] == 7


def test_ue_reachability_payload(sample_ue, monkeypatch):
    calls = _patch_request(monkeypatch)
    monitoring_callbacks.ue_reachability_callback(
        sample_ue, "http://cb", "sub", "NR_REACHABLE")
    payload = json.loads(calls['data'])
    assert payload["reachabilityType"] == "NR_REACHABLE"


def test_qos_callback_payload(monkeypatch):
    calls = _patch_request(monkeypatch)
    qos_callback.qos_callback("http://cb", "res", "QOS_GUARANTEED", "1.1.1.1")

    payload = json.loads(calls['data'])
    assert payload["transaction"] == "res"
    assert payload["ipv4Addr"] == "1.1.1.1"
    assert payload["eventReports"][0]["event"] == "QOS_GUARANTEED"


def test_qos_notification_control_timeout(monkeypatch):
    monkeypatch.setattr(qos_callback, "ues_in_cell", lambda ues, current: 2)
    monkeypatch.setattr(qos_callback, "qos_reference_match",
                        lambda ref: {"type": "GBR"})

    from unittest.mock import MagicMock
    mock = MagicMock(side_effect=requests.exceptions.Timeout)
    monkeypatch.setattr(requests, "request", mock)

    doc = {"notificationDestination": "http://cb",
           "link": "res", "qosReference": "5"}
    qos_callback.qos_notification_control(doc, "1.1.1.1", {}, {"Cell_id": 1})

    assert mock.call_count == 1


def test_qos_notification_control_success(monkeypatch):
    monkeypatch.setattr(qos_callback, "ues_in_cell", lambda ues, current: 1)
    monkeypatch.setattr(qos_callback, "qos_reference_match",
                        lambda ref: {"type": "GBR"})

    calls = _patch_request(monkeypatch)
    doc = {"notificationDestination": "http://cb",
           "link": "res", "qosReference": "5"}
    qos_callback.qos_notification_control(doc, "1.1.1.1", {}, {"Cell_id": 1})

    payload = json.loads(calls['data'])
    assert payload["eventReports"][0]["event"] == "QOS_GUARANTEED"
