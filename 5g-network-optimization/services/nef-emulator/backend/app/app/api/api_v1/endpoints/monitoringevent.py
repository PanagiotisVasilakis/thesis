from typing import Any, List
from fastapi import APIRouter, Depends, HTTPException, Path, Response, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from app import models, schemas
from app.crud import crud_mongo, user, ue
from app.api import deps
from app import tools
from app.db.session import client
from app.api.api_v1.endpoints.utils import add_notifications, ccf_logs, log_to_capif
from .ue_movement import retrieve_ue_state, retrieve_ue
import logging

router = APIRouter()
db_collection= 'MonitoringEvent'

@router.get("/{scsAsId}/subscriptions", response_model=List[schemas.MonitoringEventSubscription], responses={204: {"model" : None}})
async def read_active_subscriptions(
    *,
    scsAsId: str = Path(
        ...,
        title="The ID of the Netapp that read all the subscriptions",
        examples={"default": {"value": "myNetapp"}},
    ),
    current_user: models.User = Depends(deps.get_current_active_user),
    token_payload = Depends(deps.verify_with_public_key),
    http_request: Request
) -> Any:
    """
    Read all active subscriptions
    """
    _ = scsAsId
    db_mongo = client.fastapi

    retrieved_docs = crud_mongo.read_all(db_mongo, db_collection, current_user.id)
    active_docs = []

    for sub in retrieved_docs:
        sub_validate_time = tools.check_expiration_time(expire_time=sub.get("monitorExpireTime"))
        if sub_validate_time:
            active_docs.append(sub)
        else:
            crud_mongo.delete_by_item(db_mongo, db_collection, "externalId", sub.get("externalId"))

    if active_docs:
        http_response = JSONResponse(content=active_docs, status_code=200)
        await add_notifications(http_request, http_response, False)
        await log_to_capif(http_request, http_response, "service_monitoring_event.json", token_payload)

        return http_response
    else:
        return Response(status_code=204)



#Callback 

monitoring_callback_router = APIRouter()

@monitoring_callback_router.post(
    "{$request.body.notificationDestination}",
    response_model=schemas.MonitoringEventReportReceived,
    status_code=200,
    response_class=Response,
)
async def monitoring_notification(
    body: schemas.MonitoringNotification, *, http_request: Request
) -> Any:
    """Receive and store monitoring notifications."""
    db_mongo = client.fastapi
    try:
        crud_mongo.create(
            db_mongo, "MonitoringEventNotification", jsonable_encoder(body)
        )
    except Exception as ex:  # pragma: no cover - defensive
        raise HTTPException(status_code=400, detail=str(ex))

    http_response = JSONResponse(content={"ok": True}, status_code=200)
    await add_notifications(http_request, http_response, True)
    return http_response

@router.post("/{scsAsId}/subscriptions", response_model=schemas.MonitoringEventReport, responses={201: {"model" : schemas.MonitoringEventSubscription}}, callbacks=monitoring_callback_router.routes)
async def create_subscription(
    *,
    scsAsId: str = Path(
        ...,
        title="The ID of the Netapp that creates a subscription",
        examples={"default": {"value": "myNetapp"}},
    ),
    db: Session = Depends(deps.get_db),
    item_in: schemas.MonitoringEventSubscriptionCreate,
    current_user: models.User = Depends(deps.get_current_active_user),
    token_payload = Depends(deps.verify_with_public_key),
    http_request: Request
) -> Any:
    """
    Create new subscription.
    """
    _ = scsAsId
    db_mongo = client.fastapi

    UE = ue.get_externalId(db=db, externalId=str(item_in.externalId), owner_id=current_user.id)
    if not UE: 
        error_response = JSONResponse(
            content={"detail": "UE with this external identifier doesn't exist"},
            status_code=409
        )
        await log_to_capif(http_request, error_response, "service_monitoring_event.json", token_payload)
        raise HTTPException(status_code=409, detail="UE with this external identifier doesn't exist")
    
    
    #One time request
    if item_in.monitoringType == "LOCATION_REPORTING" and item_in.maximumNumberOfReports == 1:
        
        json_compatible_item_data = {}
        json_compatible_item_data["monitoringType"] = item_in.monitoringType
        json_compatible_item_data["externalId"] = item_in.externalId
        json_compatible_item_data["ipv4Addr"] = UE.ip_address_v4

        
        #If ue is moving retieve ue's information from memory else retrieve info from db
        if retrieve_ue_state(supi=UE.supi, user_id=current_user.id):
            cell_id_hex = retrieve_ue(UE.supi).get("cell_id_hex")
            gnb_id_hex = retrieve_ue(UE.supi).get("gnb_id_hex")
            json_compatible_item_data["locationInfo"] = {'cellId' : cell_id_hex, 'gNBId' : gnb_id_hex}
        else:
            if UE.Cell is not None:
                json_compatible_item_data["locationInfo"] = {'cellId' : UE.Cell.cell_id, 'gNBId' : UE.Cell.gNB.gNB_id}
            else:
                json_compatible_item_data["locationInfo"] = {'cellId' : None, 'gNBId' : None}

        http_response = JSONResponse(content=json_compatible_item_data, status_code=200)
        await add_notifications(http_request, http_response, False)
        
        #CAPIF Core Function Logging Service
        try:
            await log_to_capif(http_request, http_response, "service_monitoring_event.json", token_payload)
        except TypeError as error:
            logging.error("Error: %s", error)
        except AttributeError as error:
            logging.error("Error: %s", error)
        
        return http_response 
    #Subscription
    elif item_in.monitoringType == "LOCATION_REPORTING" and item_in.maximumNumberOfReports>1:
        
        #Check if subscription with externalid exists
        if crud_mongo.read_by_multiple_pairs(db_mongo, db_collection, externalId = item_in.externalId, monitoringType = item_in.monitoringType):
            #CAPIF Core Function Logging Service
            error_response = JSONResponse(
                content={"detail": f"There is already an active subscription for UE with external id {item_in.externalId} - Monitoring Type = {item_in.monitoringType}"},
                status_code=409
            )
            try:
                await log_to_capif(http_request, error_response, "service_monitoring_event.json", token_payload)
            except (TypeError, AttributeError) as error:
                logging.error("Error: %s", error)
            raise HTTPException(status_code=409, detail=f"There is already an active subscription for UE with external id {item_in.externalId} - Monitoring Type = {item_in.monitoringType}")
   
        json_data = jsonable_encoder(item_in.model_dump(exclude_unset=True))
        json_data.update({'owner_id' : current_user.id, "ipv4Addr" : UE.ip_address_v4})

        inserted_doc = crud_mongo.create(db_mongo, db_collection, json_data) 
        
        #Create the reference resource and location header
        link = str(http_request.url) + '/' + str(inserted_doc.inserted_id)
        response_header = {"location" : link}
        
        #Update the subscription with the new resource (link) and return the response (+response header)
        crud_mongo.update_new_field(db_mongo, db_collection, inserted_doc.inserted_id, {"link" : link})

        #Retrieve the updated document | UpdateResult is not a dict
        updated_doc = crud_mongo.read_uuid(db_mongo, db_collection, inserted_doc.inserted_id)
        updated_doc.pop("owner_id")


        http_response = JSONResponse(content=updated_doc, status_code=201, headers=response_header)
        await add_notifications(http_request, http_response, False)
        
        #CAPIF Core Function Logging Service
        try:
            await log_to_capif(http_request, http_response, "service_monitoring_event.json", token_payload)
        except TypeError as error:
            logging.error("Error: %s", error)
        except AttributeError as error:
            logging.error("Error: %s", error)
        
        return http_response
    elif (item_in.monitoringType == "LOSS_OF_CONNECTIVITY" or item_in.monitoringType == "UE_REACHABILITY") and item_in.maximumNumberOfReports == 1:

        error_response = JSONResponse(
            content=jsonable_encoder({
                "title" : "The requested parameters are out of range",
                "invalidParams" : {
                    "param" : "maximumNumberOfReports",
                    "reason" : '"maximumNumberOfReports" should be greater than 1 in case of LOSS_OF_CONNECTIVITY event'
                }
            }),
            status_code=403
        )
        #CAPIF Core Function Logging Service
        try:
            await log_to_capif(http_request, error_response, "service_monitoring_event.json", token_payload)
        except (TypeError, AttributeError) as error:
            logging.error("Error: %s", error)
        return error_response
    elif (item_in.monitoringType == "LOSS_OF_CONNECTIVITY" or item_in.monitoringType == "UE_REACHABILITY") and item_in.maximumNumberOfReports > 1:
        #Check if subscription with externalid && monitoringType exists
        if crud_mongo.read_by_multiple_pairs(db_mongo, db_collection, externalId = item_in.externalId, monitoringType = item_in.monitoringType):
            #CAPIF Core Function Logging Service
            error_response = JSONResponse(
                content={"detail": f"There is already an active subscription for UE with external id {item_in.externalId} - Monitoring Type = {item_in.monitoringType}"},
                status_code=409
            )
            try:
                await log_to_capif(http_request, error_response, "service_monitoring_event.json", token_payload)
            except (TypeError, AttributeError) as error:
                logging.error("Error: %s", error)
            raise HTTPException(status_code=409, detail=f"There is already an active subscription for UE with external id {item_in.externalId} - Monitoring Type = {item_in.monitoringType}")
   
        json_data = jsonable_encoder(item_in.model_dump(exclude_unset=True))
        json_data.update({'owner_id' : current_user.id, "ipv4Addr" : UE.ip_address_v4})

        inserted_doc = crud_mongo.create(db_mongo, db_collection, json_data) 
        
        #Create the reference resource and location header
        link = str(http_request.url) + '/' + str(inserted_doc.inserted_id)
        response_header = {"location" : link}
        
        #Update the subscription with the new resource (link) and return the response (+response header)
        crud_mongo.update_new_field(db_mongo, db_collection, inserted_doc.inserted_id, {"link" : link})

        #Retrieve the updated document | UpdateResult is not a dict
        updated_doc = crud_mongo.read_uuid(db_mongo, db_collection, inserted_doc.inserted_id)
        updated_doc.pop("owner_id")


        http_response = JSONResponse(content=updated_doc, status_code=201, headers=response_header)
        await add_notifications(http_request, http_response, False)
        
        #CAPIF Core Function Logging Service
        try:
            await log_to_capif(http_request, http_response, "service_monitoring_event.json", token_payload)
        except TypeError as error:
            logging.error("Error: %s", error)
        except AttributeError as error:
            logging.error("Error: %s", error)

        return http_response


@router.put("/{scsAsId}/subscriptions/{subscriptionId}", response_model=schemas.MonitoringEventSubscription)
async def update_subscription(
    *,
    scsAsId: str = Path(
        ...,
        title="The ID of the Netapp that creates a subscription",
        examples={"default": {"value": "myNetapp"}},
    ),
    subscriptionId: str = Path(..., title="Identifier of the subscription resource"),
    item_in: schemas.MonitoringEventSubscriptionCreate,
    current_user: models.User = Depends(deps.get_current_active_user),
    token_payload = Depends(deps.verify_with_public_key),
    http_request: Request
) -> Any:
    """
    Update/Replace an existing subscription resource
    """
    _ = scsAsId
    db_mongo = client.fastapi

    try:
        retrieved_doc = crud_mongo.read_uuid(db_mongo, db_collection, subscriptionId)
    except Exception as ex:
        error_response = JSONResponse(content={"detail": "Please enter a valid uuid (24-character hex string)"}, status_code=400)
        await log_to_capif(http_request, error_response, "service_monitoring_event.json", token_payload)
        raise HTTPException(status_code=400, detail='Please enter a valid uuid (24-character hex string)')
    
    #Check if the document exists
    if not retrieved_doc:
        error_response = JSONResponse(content={"detail": "Subscription not found"}, status_code=404)
        await log_to_capif(http_request, error_response, "service_monitoring_event.json", token_payload)
        raise HTTPException(status_code=404, detail="Subscription not found")
    #If the document exists then validate the owner
    if not user.is_superuser(current_user) and (retrieved_doc['owner_id'] != current_user.id):
        raise HTTPException(status_code=400, detail="Not enough permissions")

    sub_validate_time = tools.check_expiration_time(expire_time=retrieved_doc.get("monitorExpireTime"))
    
    if sub_validate_time:
        #Update the document
        json_data = jsonable_encoder(item_in)
        crud_mongo.update_new_field(db_mongo, db_collection, subscriptionId, json_data)
        
        #Retrieve the updated document | UpdateResult is not a dict
        updated_doc = crud_mongo.read_uuid(db_mongo, db_collection, subscriptionId)
        updated_doc.pop("owner_id")

        http_response = JSONResponse(content=updated_doc, status_code=200)
        await add_notifications(http_request, http_response, False)
        await log_to_capif(http_request, http_response, "service_monitoring_event.json", token_payload)

        return http_response
    else:
        crud_mongo.delete_by_uuid(db_mongo, db_collection, subscriptionId)
        raise HTTPException(status_code=403, detail="Subscription has expired")
    

@router.get("/{scsAsId}/subscriptions/{subscriptionId}", response_model=schemas.MonitoringEventSubscription)
async def read_subscription(
    *,
    scsAsId: str = Path(
        ...,
        title="The ID of the Netapp that creates a subscription",
        examples={"default": {"value": "myNetapp"}},
    ),
    subscriptionId: str = Path(..., title="Identifier of the subscription resource"),
    current_user: models.User = Depends(deps.get_current_active_user),
    token_payload = Depends(deps.verify_with_public_key),
    http_request: Request
) -> Any:
    """
    Get subscription by id
    """
    _ = scsAsId
    db_mongo = client.fastapi

    try:
        retrieved_doc = crud_mongo.read_uuid(db_mongo, db_collection, subscriptionId)
    except Exception as ex:
        error_response = JSONResponse(content={"detail": "Please enter a valid uuid (24-character hex string)"}, status_code=400)
        await log_to_capif(http_request, error_response, "service_monitoring_event.json", token_payload)
        raise HTTPException(status_code=400, detail='Please enter a valid uuid (24-character hex string)')
    
    #Check if the document exists
    if not retrieved_doc:
        error_response = JSONResponse(content={"detail": "Subscription not found"}, status_code=404)
        await log_to_capif(http_request, error_response, "service_monitoring_event.json", token_payload)
        raise HTTPException(status_code=404, detail="Subscription not found")
    #If the document exists then validate the owner
    if not user.is_superuser(current_user) and (retrieved_doc['owner_id'] != current_user.id):
        raise HTTPException(status_code=400, detail="Not enough permissions")
    
    sub_validate_time = tools.check_expiration_time(expire_time=retrieved_doc.get("monitorExpireTime"))
    
    if sub_validate_time:
        retrieved_doc.pop("owner_id")
        http_response = JSONResponse(content=retrieved_doc, status_code=200)

        await add_notifications(http_request, http_response, False)
        await log_to_capif(http_request, http_response, "service_monitoring_event.json", token_payload)

        return http_response
    else:
        crud_mongo.delete_by_uuid(db_mongo, db_collection, subscriptionId)
        raise HTTPException(status_code=403, detail="Subscription has expired")

@router.delete("/{scsAsId}/subscriptions/{subscriptionId}", response_model=schemas.MonitoringEventSubscription)
async def delete_subscription(
    *,
    scsAsId: str = Path(
        ...,
        title="The ID of the Netapp that creates a subscription",
        examples={"default": {"value": "myNetapp"}},
    ),
    subscriptionId: str = Path(..., title="Identifier of the subscription resource"),
    current_user: models.User = Depends(deps.get_current_active_user),
    token_payload = Depends(deps.verify_with_public_key),
    http_request: Request
) -> Any:
    """
    Delete a subscription
    """
    _ = scsAsId
    db_mongo = client.fastapi
    
    try:
        retrieved_doc = crud_mongo.read_uuid(db_mongo, db_collection, subscriptionId)
    except Exception as ex:
        error_response = JSONResponse(content={"detail": "Please enter a valid uuid (24-character hex string)"}, status_code=400)
        await log_to_capif(http_request, error_response, "service_monitoring_event.json", token_payload)
        raise HTTPException(status_code=400, detail='Please enter a valid uuid (24-character hex string)')
    
    #Check if the document exists
    if not retrieved_doc:
        error_response = JSONResponse(content={"detail": "Subscription not found"}, status_code=404)
        await log_to_capif(http_request, error_response, "service_monitoring_event.json", token_payload)
        raise HTTPException(status_code=404, detail="Subscription not found")
    #If the document exists then validate the owner
    if not user.is_superuser(current_user) and (retrieved_doc['owner_id'] != current_user.id):
        raise HTTPException(status_code=400, detail="Not enough permissions")

    crud_mongo.delete_by_uuid(db_mongo, db_collection, subscriptionId)
    retrieved_doc.pop("owner_id")

    http_response = JSONResponse(content=retrieved_doc, status_code=200)
    await add_notifications(http_request, http_response, False)
    await log_to_capif(http_request, http_response, "service_monitoring_event.json", token_payload)

    return http_response
