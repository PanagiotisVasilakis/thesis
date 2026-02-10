import requests
import json
from urllib.parse import urlparse
from app.core.constants import DEFAULT_TIMEOUT

# Common headers for callback requests
JSON_HEADERS = {
    'accept': 'application/json',
    'Content-Type': 'application/json'
}


def _validate_callback_url(callbackurl: str) -> None:
    """Validate callback URL has valid HTTP(S) scheme and host."""
    parsed = urlparse(callbackurl)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"Unsupported callback URL scheme: {parsed.scheme}")
    if not parsed.netloc:
        raise ValueError("Callback URL must include a host")


def location_callback(ue, callbackurl, subscription):
    """Send location reporting callback notification."""
    _validate_callback_url(callbackurl)

    payload = json.dumps({
        "externalId": ue.get("external_identifier"),
        "ipv4Addr": ue.get("ip_address_v4"),
        "subscription": subscription,
        "monitoringType": "LOCATION_REPORTING",
        "locationInfo": {
            "cellId": ue.get("cell_id_hex"),
            "enodeBId": ue.get("gnb_id_hex")
        }
    })

    return requests.post(callbackurl, headers=JSON_HEADERS, data=payload, timeout=DEFAULT_TIMEOUT)


def loss_of_connectivity_callback(ue, callbackurl, subscription):
    """Send loss of connectivity callback notification."""
    _validate_callback_url(callbackurl)

    payload = json.dumps({
        "externalId": ue.get("external_identifier"),
        "ipv4Addr": ue.get("ip_address_v4"),
        "subscription": subscription,
        "monitoringType": "LOSS_OF_CONNECTIVITY",
        "lossOfConnectReason": 7
    })

    return requests.post(callbackurl, headers=JSON_HEADERS, data=payload, timeout=DEFAULT_TIMEOUT)


def ue_reachability_callback(ue, callbackurl, subscription, reachabilityType):
    """Send UE reachability callback notification."""
    _validate_callback_url(callbackurl)

    payload = json.dumps({
        "externalId": ue.get("external_identifier"),
        "ipv4Addr": ue.get("ip_address_v4"),
        "subscription": subscription,
        "monitoringType": "UE_REACHABILITY",
        "reachabilityType": reachabilityType
    })

    return requests.post(callbackurl, headers=JSON_HEADERS, data=payload, timeout=DEFAULT_TIMEOUT)
