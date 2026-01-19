import json
import logging
from datetime import datetime
from typing import Any, Dict

import requests
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm.session import Session

from app import crud, models, schemas
from app.api import deps
from app.api.api_v1.endpoints.paths import get_random_point
from app.api.api_v1.endpoints.ue_movement import retrieve_ue_state
from app.api.api_v1.state_manager import state_manager
from app.core.config import settings
from app.core.constants import DEFAULT_TIMEOUT
from app.schemas import UserPlaneNotificationData, monitoringevent

logger = logging.getLogger(__name__)
try:
    from evolved5g.sdk import CAPIFLogger
except (ImportError, AttributeError):
    class CAPIFLogger:
        """Minimal stub if evolved5g CAPIFLogger is unavailable."""

        class LogEntry:
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)

        def __init__(self, certificates_folder: str = "", capif_host: str = "", capif_https_port: int = 0):
            self.certificates_folder = certificates_folder
            self.capif_host = capif_host
            self.capif_https_port = capif_https_port

        def get_capif_service_description(self, capif_service_api_description_json_full_path: str):
            _ = capif_service_api_description_json_full_path
            return {"apiId": "dummy"}

        def save_log(self, api_invoker_id: str, log_entries: list):
            return True


class CCFLogRequest(BaseModel):
    """Generic model for request bodies logged by CAPIF."""

    data: Dict[str, Any]

#Create CAPIF Logger object
async def ccf_logs(input_request: Request, output_response: dict, service_api_description: str, invoker_id: str):
    
    try:
        capif_logger = CAPIFLogger(certificates_folder="app/core/certificates",
                                    capif_host=settings.CAPIF_HOST,
                                    capif_https_port=settings.CAPIF_HTTPS_PORT
                                    )

        log_entries = []
        service_description = capif_logger.get_capif_service_description(capif_service_api_description_json_full_path=
                                                                f"app/core/certificates/CAPIF_{service_api_description}")

        api_id = service_description["apiId"]

        endpoint = input_request.url.path
        if endpoint.find('monitoring') != -1:
            resource = "Monitoring_Event_API"
            endpoint = "/nef/api/v1/3gpp-monitoring-event/"
        elif endpoint.find('session-with-qos') != -1:
            resource = "AsSession_With_QoS_API"
            endpoint = "/nef/api/v1/3gpp-as-session-with-qos/"

        #Request body check and trim
        if input_request.method in {"POST", "PUT"}:
            try:
                parsed = await input_request.json()
            except Exception as exc:
                raise HTTPException(status_code=400, detail="Invalid JSON body") from exc
            req_body = CCFLogRequest(data=parsed).data
        else:
            req_body = " "
        
        url_string = "https://" + input_request.url.hostname + ":4443" + endpoint
        
        log_entry = CAPIFLogger.LogEntry(
                                        apiId = api_id,
                                        apiVersion="v1",
                                        apiName=endpoint,
                                        resourceName=resource,
                                        uri=url_string,
                                        protocol="HTTP_1_1",
                                        invocationTime= datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                        invocationLatency=10,
                                        operation=input_request.method,
                                        result= output_response.get("status_code"),
                                        inputParameters=req_body,
                                        outputParameters=output_response.get("response")
                                        )

        log_entries.append(log_entry)
        api_invoker_id = invoker_id
        capif_logger.save_log(api_invoker_id,log_entries)
    except HTTPException:
        raise
    except Exception as ex:  # pragma: no cover - defensive
        logging.critical(ex)
        logging.critical("Potential cause of failure: CAPIF Core Function is not deployed or unreachable")


async def log_to_capif(
    http_request: Request,
    http_response: JSONResponse,
    service_file: str,
    token_payload: dict
) -> None:
    """
    Helper function to log API calls to CAPIF Core Function.
    
    Consolidates the repetitive CAPIF logging pattern used across multiple endpoints.
    
    Args:
        http_request: The incoming HTTP request
        http_response: The outgoing HTTP response
        service_file: The service API description JSON filename (e.g., "service_monitoring_event.json")
        token_payload: The JWT token payload containing the subscriber ID
    """
    try:
        response = http_response.body.decode("utf-8")
        json_response = {
            "response": response,
            "status_code": str(http_response.status_code)
        }
        await ccf_logs(http_request, json_response, service_file, token_payload.get("sub"))
    except TypeError as error:
        logging.warning("CAPIF logging TypeError: %s", error)
    except AttributeError as error:
        logging.warning("CAPIF logging AttributeError: %s", error)


async def log_error_to_capif(
    http_request: Request,
    error_message: str,
    status_code: int,
    service_file: str,
    token_payload: dict
) -> None:
    """Log an error response to CAPIF before raising an HTTPException.
    
    This helper consolidates the repetitive pattern of logging error
    responses to CAPIF. Use this when you need to log an error before
    raising HTTPException.
    
    Args:
        http_request: The incoming HTTP request
        error_message: The error message to log
        status_code: The HTTP status code
        service_file: The service API description JSON filename
        token_payload: The JWT token payload containing the subscriber ID
    """
    try:
        json_response = {
            "response": error_message,
            "status_code": str(status_code)
        }
        invoker_id = token_payload.get("sub") if token_payload else None
        await ccf_logs(http_request, json_response, service_file, invoker_id)
    except (TypeError, AttributeError) as error:
        logging.warning("CAPIF error logging failed: %s", error)


# Runtime state is stored in the shared StateManager instance

async def add_notifications(request: Request, response: JSONResponse, is_notification: bool):

    json_data: dict = {}

    #Find the service API 
    #Keep in mind that whether endpoint changes format, the following if statement needs review
    #Since new APIs are added in the emulator, the if statement will expand
    endpoint = request.url.path
    if endpoint.find('monitoring') != -1:
        serviceAPI = "Monitoring Event API"
    elif endpoint.find('session-with-qos') != -1:
        serviceAPI = "AsSession With QoS API"
    elif endpoint.find('qosInfo') != -1:
        serviceAPI = "QoS Information"

    #Request body check and trim
    if request.method in {"POST", "PUT"}:
        try:
            parsed = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Invalid JSON body") from exc
        json_data["request_body"] = json.dumps(CCFLogRequest(data=parsed).data)

    json_data["response_body"] = response.body.decode("utf-8")  
    json_data["endpoint"] = endpoint
    json_data["serviceAPI"] = serviceAPI
    json_data["method"] = request.method    
    json_data["status_code"] = response.status_code
    json_data["isNotification"] = is_notification
    json_data["timestamp"] = datetime.now()

    state_manager.add_notification(json_data)

    return json_data
    
router = APIRouter()

@router.get("/export/scenario", response_model=schemas.Scenario)
def get_scenario(
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_active_user)
) -> Any:
    """
    Export the scenario
    """
    gNBs = crud.gnb.get_multi_by_owner(db=db, owner_id=current_user.id, skip=0, limit=100)
    Cells = crud.cell.get_multi_by_owner(db=db, owner_id=current_user.id, skip=0, limit=100)
    UEs = crud.ue.get_multi_by_owner(db=db, owner_id=current_user.id, skip=0, limit=100)
    paths = crud.path.get_multi_by_owner(db=db, owner_id=current_user.id, skip=0, limit=100)

    
    json_gNBs= jsonable_encoder(gNBs)
    json_Cells= jsonable_encoder(Cells)
    json_UEs= jsonable_encoder(UEs)
    json_path = jsonable_encoder(paths)
    ue_path_association = []

    # Build a lookup dict for O(1) access instead of O(n²) nested loop
    path_by_id = {path.id: path for path in paths}
    
    for item_json in json_path:
        path = path_by_id.get(item_json.get('id'))
        if path:
            item_json["start_point"] = {
                "latitude": path.start_lat,
                "longitude": path.start_long
            }
            item_json["end_point"] = {
                "latitude": path.end_lat,
                "longitude": path.end_long
            }
            item_json["id"] = path.id
            points = crud.points.get_points(db=db, path_id=path.id)
            item_json["points"] = [
                {'latitude': obj.get('latitude'), 'longitude': obj.get('longitude')}
                for obj in jsonable_encoder(points)
            ]

    for ue in UEs:
        if ue.path_id:
            json_ue_path_association = {}
            json_ue_path_association["supi"] = ue.supi
            json_ue_path_association["path"] = ue.path_id
            ue_path_association.append(json_ue_path_association)

    export_json = {
        "gNBs" : json_gNBs,
        "cells" : json_Cells,
        "UEs" : json_UEs,
        "paths" : json_path,
        "ue_path_association" : ue_path_association
    }

    return export_json

@router.post("/import/scenario")
def create_scenario(
    scenario_in: schemas.Scenario,
    db: Session = Depends(deps.get_db),
    current_user: models.User = Depends(deps.get_current_active_user), 
) -> Any:
    """
    Import the scenario
    """
    errors: Dict[str, str] = {}
    
    gNBs = scenario_in.gNBs
    cells = scenario_in.cells
    ues = scenario_in.UEs
    paths = scenario_in.paths
    ue_path_association = scenario_in.ue_path_association
    
    # Reset simulation state and stop background threads
    state_manager.reset()

    from sqlalchemy import text
    db.execute(text('TRUNCATE TABLE cell, gnb, monitoring, path, points, ue RESTART IDENTITY'))
    
    for gNB_in in gNBs:
        gNB = crud.gnb.get_gNB_id(db=db, id=gNB_in.gNB_id)
        if gNB:
            logger.error("ERROR: gNB with id %s already exists", gNB_in.gNB_id)
            errors[gNB_in.name] = f"ERROR: gNB with id {gNB_in.gNB_id} already exists"
        else:
            gNB = crud.gnb.create_with_owner(db=db, obj_in=gNB_in, owner_id=current_user.id)

    for cell_in in cells:
        cell = crud.cell.get_Cell_id(db=db, id=cell_in.cell_id)
        if cell:
            logger.error("ERROR: Cell with id %s already exists", cell_in.cell_id)
            errors[cell_in.name] = f"ERROR: Cell with id {cell_in.cell_id} already exists"
            crud.cell.remove_all_by_owner(db=db, owner_id=current_user.id)
        else:
            cell = crud.cell.create_with_owner(db=db, obj_in=cell_in, owner_id=current_user.id)

    for ue_in in ues:
        ue = crud.ue.get_supi(db=db, supi=ue_in.supi)
        if ue:
            logger.error("ERROR: UE with supi %s already exists", ue_in.supi)
            errors[ue.name] = f"ERROR: UE with supi {ue_in.supi} already exists"
        else:
            ue = crud.ue.create_with_owner(db=db, obj_in=ue_in, owner_id=current_user.id)

    for path_in in paths:
        path_old_id = path_in.id

        path = crud.path.get_description(db=db, description = path_in.description)
        if path:
            logger.error("ERROR: Path with description '%s' already exists", path_in.description)
            errors[path_in.description] = (
                f"ERROR: Path with description '{path_in.description}' already exists"
            )
        else:
            path = crud.path.create_with_owner(db=db, obj_in=path_in, owner_id=current_user.id)
            crud.points.create(db=db, obj_in=path_in, path_id=path.id) 
            
            for ue_path in ue_path_association:
                if retrieve_ue_state(ue_path.supi, current_user.id):
                    errors[ue_path.supi] = (
                        "UE is currently moving. You are not allowed to edit"
                        " the UE's path while it's moving"
                    )
                else:
                    #Assign the coordinates
                    UE = crud.ue.get_supi(db=db, supi=ue_path.supi)
                    json_data = jsonable_encoder(UE)
                    
                    #Check if the old path id or the new one is associated with one or more UEs store in ue_path_association dictionary
                    #If not then add path_id 0 on UE's table
                    logger.debug("Ue_path_association %s", ue_path.path)
                    logger.debug("Path old id: %s", path_old_id)
                    if ue_path.path == path_old_id:
                        logger.debug("New path id %s", path.id)
                        json_data['path_id'] = path.id
                        
                        # Deterministic Start: Always start at the beginning of the path (index 0)
                        # This ensures every run is identical for A/B testing
                        points = crud.points.get_points(db=db, path_id=path.id)
                        if points:
                            start_point = jsonable_encoder(points[0])
                            json_data['latitude'] = start_point.get('latitude')
                            json_data['longitude'] = start_point.get('longitude')
                        else:
                            # Fallback if no points (should not happen in valid scenarios)
                            logger.warning("No points found for path %s, user will start at (0,0)", path.id)
                            json_data['latitude'] = 0.0
                            json_data['longitude'] = 0.0
                    
                    crud.ue.update(db=db, db_obj=UE, obj_in=json_data)
    
    if errors:
        raise HTTPException(status_code=409, detail=errors)
    return ""

class callback(BaseModel):
    callbackurl: str

@router.post("/test/callback")
def get_test(
    item_in: callback
    ):
    
    callbackurl = item_in.callbackurl
    logger.info(callbackurl)
    payload = json.dumps({
    "externalId" : "10000@domain.com",
    "ipv4Addr" : "10.0.0.0",
    "subscription" : "http://localhost:8888/api/v1/3gpp-monitoring-event/v1/myNetapp/subscriptions/whatever",
    "monitoringType": "LOCATION_REPORTING",
    "locationInfo": {
        "cellId": "AAAAAAAAA",
        "enodeBId": "AAAAAA"
    }
    })

    headers = {
    'accept': 'application/json',
    'Content-Type': 'application/json'
    }

    try:
        response = requests.request(
            "POST",
            callbackurl,
            headers=headers,
            data=payload,
            timeout=DEFAULT_TIMEOUT,
        )
        return response.json()
    except requests.exceptions.ConnectionError as ex:
        logging.warning(ex)
        raise HTTPException(status_code=409, detail=f"Failed to send the callback request. Error: {ex}")

@router.post("/session-with-qos/callback")
async def create_item(_: UserPlaneNotificationData, request: Request):

    http_response = JSONResponse(content={'ack' : 'TRUE'}, status_code=200)
    await add_notifications(request, http_response, True)
    return http_response

@router.post("/monitoring/callback")
async def create_item(_: monitoringevent.MonitoringNotification, request: Request):

    http_response = JSONResponse(content={'ack' : 'TRUE'}, status_code=200)
    await add_notifications(request, http_response, True)
    return http_response

@router.get("/monitoring/notifications")
def get_notifications(
    skip: int = 0,
    limit: int = 100,
    current_user: models.User = Depends(deps.get_current_active_user)
    ):
    return state_manager.get_notifications(skip, limit)

@router.get("/monitoring/last_notifications")
def get_last_notifications(
    id: int = Query(..., description="The id of the last retrieved item"),
    current_user: models.User = Depends(deps.get_current_active_user)
    ):
    updated_notification = []
    event_notifications_snapshot = state_manager.all_notifications()


    if id == -1:
        return event_notifications_snapshot

    if event_notifications_snapshot:
        if event_notifications_snapshot[0].get('id') > id:
            return event_notifications_snapshot
    else:
        raise HTTPException(status_code=409, detail="Event notification list is empty")
            
    skipped_items = 0


    for notification in event_notifications_snapshot:
        if notification.get('id') == id:
            updated_notification = event_notifications_snapshot[(skipped_items+1):]
            break
        skipped_items += 1
    
    return updated_notification
