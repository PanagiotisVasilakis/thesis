import requests
import json
from urllib.parse import urlparse
from app.core.constants import DEFAULT_TIMEOUT


def _validate_callback_url(callbackurl: str) -> None:
    parsed = urlparse(callbackurl)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"Unsupported callback URL scheme: {parsed.scheme}")
    if not parsed.netloc:
        raise ValueError("Callback URL must include a host")

def location_callback(ue, callbackurl, subscription):
    url = callbackurl
    _validate_callback_url(url)

    payload = json.dumps({
    "externalId" : ue.get("external_identifier"),
    "ipv4Addr" : ue.get("ip_address_v4"),
    "subscription" : subscription,
    "monitoringType": "LOCATION_REPORTING",
    "locationInfo": {
        "cellId": ue.get("cell_id_hex"),
        "enodeBId": ue.get("gnb_id_hex")
    }
    })
    headers = {
    'accept': 'application/json',
    'Content-Type': 'application/json'
    }

    response = requests.request("POST", url, headers=headers, data=payload, timeout=DEFAULT_TIMEOUT)
    
    return response

def loss_of_connectivity_callback(ue, callbackurl, subscription):
    url = callbackurl
    _validate_callback_url(url)

    payload = json.dumps({
    "externalId" : ue.get("external_identifier"),
    "ipv4Addr" : ue.get("ip_address_v4"),
    "subscription" : subscription,
    "monitoringType": "LOSS_OF_CONNECTIVITY",
    "lossOfConnectReason": 7
    })
    headers = {
    'accept': 'application/json',
    'Content-Type': 'application/json'
    }

    response = requests.request("POST", url, headers=headers, data=payload, timeout=DEFAULT_TIMEOUT)
    
    return response

def ue_reachability_callback(ue, callbackurl, subscription, reachabilityType):
    url = callbackurl
    _validate_callback_url(url)

    payload = json.dumps({
    "externalId" : ue.get("external_identifier"),
    "ipv4Addr" : ue.get("ip_address_v4"),
    "subscription" : subscription,
    "monitoringType": "UE_REACHABILITY",
    "reachabilityType": reachabilityType
    })
    headers = {
    'accept': 'application/json',
    'Content-Type': 'application/json'
    }

    #Timeout values according to https://docs.python-requests.org/en/master/user/advanced/#timeouts 
    #First value of the tuple "3.05" corresponds to connect and second "27" to read timeouts 
    #(i.e., connect timeout means that the server is unreachable and read that the server is reachable but the client does not receive a response within 27 seconds)
    
    response = requests.request("POST", url, headers=headers, data=payload, timeout=DEFAULT_TIMEOUT)
    
    return response
