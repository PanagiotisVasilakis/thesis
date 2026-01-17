import requests
import json
import logging
from app.crud import ue
from app.api.api_v1.endpoints.qosInformation import qos_reference_match
from app.db.session import SessionLocal
from fastapi.encoders import jsonable_encoder
from app.core.constants import DEFAULT_TIMEOUT


def qos_callback(callbackurl, resource, qos_status, ipv4):
    url = callbackurl

    payload = json.dumps({
    "transaction" : resource,
    "ipv4Addr" : ipv4,
    "eventReports": [
    {
      "event": qos_status,
      "accumulatedUsage": {
        "duration": None,
        "totalVolume": None,
        "downlinkVolume": None,
        "uplinkVolume": None
      },
      "appliedQosRef": None,
      "qosMonReports": [
        {
          "ulDelays": [
            0
          ],
          "dlDelays": [
            0
          ],
          "rtDelays": [
            0
          ]
        }
      ]
    }]
    })    
    
    
    headers = {
    'accept': 'application/json',
    'Content-Type': 'application/json'
    }

    response = requests.request("POST", url, headers=headers, data=payload, timeout=DEFAULT_TIMEOUT)
    
    return response

def qos_notification_control(doc, ipv4, ues: dict, current_ue: dict):

    number_of_ues_in_cell = ues_in_cell(ues, current_ue)

    if number_of_ues_in_cell > 1:
      gbr_status = 'QOS_NOT_GUARANTEED' 
    else: 
      gbr_status= 'QOS_GUARANTEED'

    qos_standardized = qos_reference_match(doc.get('qosReference'))

    if qos_standardized.get('type') == 'GBR' or qos_standardized.get('type') == 'DC-GBR':
        try:
            response = qos_callback(doc.get('notificationDestination'), doc.get('link'), gbr_status, ipv4)
            logging.info("QoS callback sent to %s", doc.get('notificationDestination'))
        except requests.exceptions.Timeout as ex:
            logging.error("QoS callback timed out: %s", ex)
        except requests.exceptions.TooManyRedirects as ex:
            logging.error("QoS callback failed (too many redirects): %s", ex)
        except requests.exceptions.RequestException as ex:
            logging.error("QoS callback request failed: %s", ex)
    else:
        logging.debug('Non-GBR subscription - skipping QoS callback')

    return

def ues_in_cell(ues: dict, current_ue: dict) -> int:
    """Count UEs connected to the same cell as current_ue.

    Args:
        ues: Dictionary of running UEs keyed by identifier.
        current_ue: The UE whose cell we're counting.

    Returns:
        Number of UEs in the same cell (running + stationary).
    """
    ues_connected = 0

    # Find running UEs in the same cell
    for single_ue in ues:
        if ues[single_ue]["Cell_id"] == current_ue["Cell_id"]:
            ues_connected += 1

    # Find stationary UEs in the same cell (from database)
    db = SessionLocal()
    try:
        ues_list = ue.get_by_Cell(db=db, cell_id=current_ue["Cell_id"])

        for ue_in_db in ues_list:
            # Only count UEs that are not running (stationary)
            # In db the last known location (cell_id) is valid only for stationary UEs
            if jsonable_encoder(ue_in_db).get('supi') not in ues:
                ues_connected += 1
    finally:
        db.close()

    return ues_connected
