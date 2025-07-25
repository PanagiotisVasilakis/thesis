import threading, logging, time, requests
from fastapi import APIRouter, Path, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from typing import Any
from app import crud, tools, models
from app.crud import crud_mongo
from app.tools.distance import check_distance
from app.tools import qos_callback
from app.db.session import SessionLocal, client
from app.api import deps
from app.api.api_v1.state_manager import state_manager

logger = logging.getLogger(__name__)

# Counter for timer related errors is stored in StateManager

def log_timer_exception(ex: Exception) -> None:
    """Log timer exceptions and track how many times they occur."""
    state_manager.increment_timer_error()
    logger.warning("Timer error: %s", ex)
from app.schemas import Msg
from app.tools import monitoring_callbacks, timer
from sqlalchemy.orm import Session

#Dictionary holding threads and UEs' information are stored in StateManager

class BackgroundTasks(threading.Thread):

    def __init__(self, group=None, target=None, name=None, args=(), kwargs=None): 
        super().__init__(group=group, target=target,  name=name)
        self._args = args
        self._kwargs = kwargs
        self._stop_threads = False
        return

    def run(self):
        
        db_mongo = client.fastapi

        current_user = self._args[0]
        supi = self._args[1]
        json_cells = self._args[2]
        points = self._args[3]
        is_superuser = self._args[4]

        active_subscriptions = {
            "location_reporting" : False,
            "ue_reachability" : False,
            "loss_of_connectivity" : False,
            "as_session_with_qos" : False
        }

        try:
            
            t = timer.SequencialTimer(logger=logging.critical)
            rt = None
            # global loss_of_connectivity_ack
            loss_of_connectivity_ack = "FALSE"
            
            '''
            ===================================================================
                               2nd Approach for updating UEs position
            ===================================================================

            Summary: while(TRUE) --> keep increasing the moving index


                points [ 1 2 3 4 5 6 7 8 9 10 ... ] . . . . . . .
                         ^ current index
                         ^  moving index                ^ moving can also reach here
                 
            current: shows where the UE is
            moving : starts within the range of len(points) and keeps increasing.
                     When it goes out of these bounds, the MOD( len(points) ) prevents
                     the "index out of range" exception. It also starts the iteration
                     of points from the begining, letting the UE moving in endless loops.

            Sleep:   in both LOW / HIGH speed cases, the thread sleeps for 1 sec

            Speed:   LOW : (moving_position_index += 1)  no points are skipped, this means 1m/sec
                     HIGH: (moving_position_index += 10) skips 10 points, thus...        ~10m/sec

            Pros:    + the UE position is updated once every sec (not very aggressive)
                     + we can easily set speed this way (by skipping X points --> X m/sec)
            Cons:    - skipping points and updating once every second decreases the event resolution

            -------------------------------------------------------------------
            '''

            current_position_index = -1

            # find the index of the point where the UE is located
            for index, point in enumerate(points):
                if (ue_data["latitude"] == point["latitude"]) and (ue_data["longitude"] == point["longitude"]):
                    current_position_index = index

            # start iterating from this index and keep increasing the moving_position_index...
            moving_position_index = current_position_index

            while True:
                try:
                    # UE = crud.ue.update_coordinates(db=db, lat=points[current_position_index]["latitude"], long=points[current_position_index]["longitude"], db_obj=UE)
                    # cell_now = check_distance(UE.latitude, UE.longitude, json_cells) #calculate the distance from all the cells
                    ue_data["latitude"] = points[current_position_index]["latitude"]
                    ue_data["longitude"] = points[current_position_index]["longitude"]
                    cell_now = check_distance(ue_data["latitude"], ue_data["longitude"], json_cells) #calculate the distance from all the cells
                except Exception as ex:
                    logging.warning("Failed to update coordinates")
                    logging.warning(ex)
                
                
                #MonitoringEvent API - Loss of connectivity
                if not active_subscriptions.get("loss_of_connectivity"):
                    loss_of_connectivity_sub = crud_mongo.read_by_multiple_pairs(db_mongo, "MonitoringEvent", externalId = ue_data["external_identifier"], monitoringType = "LOSS_OF_CONNECTIVITY")
                    if loss_of_connectivity_sub:
                        active_subscriptions.update({"loss_of_connectivity" : True})
                    

                #Validation of subscription
                if active_subscriptions.get("loss_of_connectivity") and loss_of_connectivity_ack == "FALSE":
                    sub_is_valid = monitoring_event_sub_validation(loss_of_connectivity_sub, is_superuser, current_user.id, loss_of_connectivity_sub.get("owner_id"))    
                    if sub_is_valid:
                        try:
                            try:
                                elapsed_time = t.status()
                                if elapsed_time > loss_of_connectivity_sub.get("maximumDetectionTime"):
                                    response = monitoring_callbacks.loss_of_connectivity_callback(ue_data, loss_of_connectivity_sub.get("notificationDestination"), loss_of_connectivity_sub.get("link"))
                                    
                                    logging.critical(response.json())
                                    #This ack is used to send one time the loss of connectivity callback
                                    loss_of_connectivity_ack = response.json().get("ack")
                                    
                                    loss_of_connectivity_sub.update({"maximumNumberOfReports" : loss_of_connectivity_sub.get("maximumNumberOfReports") - 1})
                                    crud_mongo.update(db_mongo, "MonitoringEvent", loss_of_connectivity_sub.get("_id"), loss_of_connectivity_sub)
                            except timer.TimerError as ex:
                                log_timer_exception(ex)
                        except requests.exceptions.ConnectionError as ex:
                            logging.warning("Failed to send the callback request")
                            logging.warning(ex)
                            crud_mongo.delete_by_uuid(db_mongo, "MonitoringEvent", loss_of_connectivity_sub.get("_id"))
                            active_subscriptions.update({"loss_of_connectivity" : False})
                            continue
                    else:
                        crud_mongo.delete_by_uuid(db_mongo, "MonitoringEvent", loss_of_connectivity_sub.get("_id"))
                        active_subscriptions.update({"loss_of_connectivity" : False})
                        logging.warning("Subscription has expired")
                #MonitoringEvent API - Loss of connectivity

                #As Session With QoS API - search for active subscription in db
                if not active_subscriptions.get("as_session_with_qos"):
                    qos_sub = crud_mongo.read(db_mongo, 'QoSMonitoring', 'ipv4Addr', ue_data["ip_address_v4"])
                    if qos_sub:
                        active_subscriptions.update({"as_session_with_qos" : True})
                        reporting_freq = qos_sub["qosMonInfo"]["repFreqs"]
                        
                        if "PERIODIC" in reporting_freq:
                            reporting_period = qos_sub["qosMonInfo"]["repPeriod"]
                            rt = timer.RepeatedTimer(
                                reporting_period,
                                qos_callback.qos_notification_control,
                                qos_sub,
                                ue_data["ip_address_v4"],
                                state_manager.all_ues(),
                                ue_data,
                            )
                            # qos_callback.qos_notification_control(qos_sub, ue_data["ip_address_v4"], state_manager.all_ues(), ue_data)


                #If the document exists then validate the owner
                if not is_superuser and (qos_sub['owner_id'] != current_user.id):
                    logging.warning("Not enough permissions")
                    active_subscriptions.update({"as_session_with_qos" : False})
                #As Session With QoS API - search for active subscription in db

                if cell_now != None:
                    try:
                        t.stop()
                        loss_of_connectivity_ack = "FALSE"
                        if rt is not None:
                            rt.start()
                    except timer.TimerError as ex:
                        log_timer_exception(ex)

                    # if UE.Cell_id != cell_now.get('id'): #Cell has changed in the db "handover"
                    if ue_data["Cell_id"] != cell_now.get('id'): #Cell has changed in the db "handover"
                        
                        #Monitoring Event API - UE reachability 
                        #check if the ue was disconnected before
                        if ue_data["Cell_id"] == None:
                            
                            if not active_subscriptions.get("ue_reachability"):
                                ue_reachability_sub = crud_mongo.read_by_multiple_pairs(db_mongo, "MonitoringEvent", externalId = ue_data["external_identifier"], monitoringType = "UE_REACHABILITY")
                                if ue_reachability_sub:
                                    active_subscriptions.update({"ue_reachability" : True})

                            #Validation of subscription    
                             
                            if active_subscriptions.get("ue_reachability"):
                                sub_is_valid = monitoring_event_sub_validation(ue_reachability_sub, is_superuser, current_user.id, ue_reachability_sub.get("owner_id"))   
                                if sub_is_valid:
                                    try:
                                        try:
                                            monitoring_callbacks.ue_reachability_callback(ue_data, ue_reachability_sub.get("notificationDestination"), ue_reachability_sub.get("link"), ue_reachability_sub.get("reachabilityType"))
                                            ue_reachability_sub.update({"maximumNumberOfReports" : ue_reachability_sub.get("maximumNumberOfReports") - 1})
                                            crud_mongo.update(db_mongo, "MonitoringEvent", ue_reachability_sub.get("_id"), ue_reachability_sub)
                                        except timer.TimerError as ex:
                                            log_timer_exception(ex)
                                    except requests.exceptions.ConnectionError as ex:
                                        logging.warning("Failed to send the callback request")
                                        logging.warning(ex)
                                        crud_mongo.delete_by_uuid(db_mongo, "MonitoringEvent", ue_reachability_sub.get("_id"))
                                        active_subscriptions.update({"ue_reachability" : False})
                                        continue
                                else:
                                    crud_mongo.delete_by_uuid(db_mongo, "MonitoringEvent", ue_reachability_sub.get("_id"))
                                    active_subscriptions.update({"ue_reachability" : False})
                                    logging.warning("Subscription has expired")
                         #Monitoring Event API - UE reachability
                        
                        
                        # logging.warning(f"UE({UE.supi}) with ipv4 {UE.ip_address_v4} handovers to Cell {cell_now.get('id')}, {cell_now.get('description')}")
                        ue_data["Cell_id"] = cell_now.get('id')
                        ue_data["cell_id_hex"] = cell_now.get('cell_id')
                        ue_data["gnb_id_hex"] = cell_now.get('cell_id')[:6]

                        
                        #Monitoring Event API - Location Reporting
                        #Retrieve the subscription of the UE by external Id | This could be outside while true but then the user cannot subscribe when the loop runs
                        if not active_subscriptions.get("location_reporting"):
                            location_reporting_sub = crud_mongo.read_by_multiple_pairs(db_mongo, "MonitoringEvent", externalId = ue_data["external_identifier"], monitoringType = "LOCATION_REPORTING")
                            if location_reporting_sub:
                                active_subscriptions.update({"location_reporting" : True})

                        #Validation of subscription    
                        if active_subscriptions.get("location_reporting"): 
                            sub_is_valid = monitoring_event_sub_validation(location_reporting_sub, is_superuser, current_user.id, location_reporting_sub.get("owner_id"))    
                            if sub_is_valid:
                                try:
                                    try:
                                        monitoring_callbacks.location_callback(ue_data, location_reporting_sub.get("notificationDestination"), location_reporting_sub.get("link"))
                                        location_reporting_sub.update({"maximumNumberOfReports" : location_reporting_sub.get("maximumNumberOfReports") - 1})
                                        crud_mongo.update(db_mongo, "MonitoringEvent", location_reporting_sub.get("_id"), location_reporting_sub)
                                    except timer.TimerError as ex:
                                        log_timer_exception(ex)
                                except requests.exceptions.ConnectionError as ex:
                                    logging.warning("Failed to send the callback request")
                                    logging.warning(ex)
                                    crud_mongo.delete_by_uuid(db_mongo, "MonitoringEvent", location_reporting_sub.get("_id"))
                                    active_subscriptions.update({"location_reporting" : False})
                                    continue
                            else:
                                crud_mongo.delete_by_uuid(db_mongo, "MonitoringEvent", location_reporting_sub.get("_id"))
                                active_subscriptions.update({"location_reporting" : False})
                                logging.warning("Subscription has expired")
                        #Monitoring Event API - Location Reporting
                        
                        #As Session With QoS API - if EVENT_TRIGGER then send callback on handover
                        if active_subscriptions.get("as_session_with_qos"):
                            reporting_freq = qos_sub["qosMonInfo"]["repFreqs"]
                            if "EVENT_TRIGGERED" in reporting_freq:
                                qos_callback.qos_notification_control(
                                    qos_sub,
                                    ue_data["ip_address_v4"],
                                    state_manager.all_ues(),
                                    ue_data,
                                )
                        #As Session With QoS API - if EVENT_TRIGGER then send callback on handover

                else:
                    # crud.ue.update(db=db, db_obj=UE, obj_in={"Cell_id" : None})
                    try:
                        t.start()
                        if rt is not None:
                            rt.stop()
                    except timer.TimerError as ex:
                        log_timer_exception(ex)

                    ue_data["Cell_id"] = None
                    ue_data["cell_id_hex"] = None
                    ue_data["gnb_id_hex"] = None

                # logging.info(f'User: {current_user.id} | UE: {supi} | Current location: latitude ={UE.latitude} | longitude = {UE.longitude} | Speed: {UE.speed}' )
                
                if ue_data["speed"] == 'LOW':
                    # don't skip any points, keep default speed 1m /sec
                    moving_position_index += 1
                elif ue_data["speed"] == 'HIGH':
                    # skip 10 points --> 10m / sec
                    moving_position_index += 10

                time.sleep(1)

                current_position_index = moving_position_index % (len(points))
                state_manager.set_ue(supi, ue_data)

                
                if self._stop_threads:
                    logging.critical("Terminating thread...")
                    logging.critical("Updating UE with the latest coordinates and cell in the database (last known position)...")
                    db = SessionLocal()
                    UE = crud.ue.get_supi(db, supi)
                    crud.ue.update_coordinates(db=db, lat=ue_data["latitude"], long=ue_data["longitude"], db_obj=UE)
                    crud.ue.update(db=db, db_obj=UE, obj_in={"Cell_id" : ue_data["Cell_id"]})
                    state_manager.remove_ue(supi)
                    db.close()
                    if rt is not None:
                        rt.stop()
                    break
            
            # End of 2nd Approach for updating UEs position

        except Exception as ex:
            logging.critical(ex)

    def stop(self):
        self._stop_threads = True

#API
router = APIRouter()

@router.post("/start-loop", status_code=200)
def initiate_movement(
    *,
    msg: Msg,
    current_user: models.User = Depends(deps.get_current_active_user),
    db: Session = Depends(deps.get_db)
) -> Any:
    """
    Start the loop.
    """
    if state_manager.get_thread(msg.supi, f"{current_user.id}"):
        raise HTTPException(status_code=409, detail=f"There is a thread already running for this supi:{msg.supi}")
    
    #Check if UE 
    UE = crud.ue.get_supi(db=db, supi=msg.supi)
    if not UE:
        logging.warning("UE not found")
        state_manager.remove_thread(msg.supi)
        return
    if (UE.owner_id != current_user.id):
        logging.warning("Not enough permissions")
        state_manager.remove_thread(msg.supi)
        return
    
    #Insert running UE in the dictionary

    ue_data = jsonable_encoder(UE)
    ue_data.pop("id")

    if UE.Cell_id != None:
        ue_data["cell_id_hex"] = UE.Cell.cell_id
        ue_data["gnb_id_hex"] = UE.Cell.gNB.gNB_id
    else:
        ue_data["cell_id_hex"] = None
        ue_data["gnb_id_hex"] = None


    #Retrieve paths & points
    path = crud.path.get(db=db, id=UE.path_id)
    if not path:
        logging.warning("Path not found")
        state_manager.remove_thread(msg.supi)
        return
    if (path.owner_id != current_user.id):
        logging.warning("Not enough permissions")
        state_manager.remove_thread(msg.supi)
        return

    points = crud.points.get_points(db=db, path_id=UE.path_id)
    points = jsonable_encoder(points)

    #Retrieve all the cells
    Cells = crud.cell.get_multi_by_owner(db=db, owner_id=current_user.id, skip=0, limit=100)
    json_cells = jsonable_encoder(Cells)

    is_superuser = crud.user.is_superuser(current_user)

    t = BackgroundTasks(args=(current_user, msg.supi, json_cells, points, is_superuser))
    state_manager.set_thread(msg.supi, f"{current_user.id}", t)
    state_manager.set_ue(msg.supi, ue_data)
    t.start()
    return {"msg": "Loop started"}

@router.post("/stop-loop", status_code=200)
def terminate_movement(
     *,
    msg: Msg,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Stop the loop.
    """
    try:
        t = state_manager.get_thread(msg.supi, f"{current_user.id}")
        if not t:
            raise KeyError
        t.stop()
        t.join()
        state_manager.remove_thread(msg.supi)
        return {"msg": "Loop ended"}
    except KeyError as ke:
        logger.error('Key Not Found in Threads Dictionary: %s', ke)
        raise HTTPException(status_code=409, detail="There is no thread running for this user! Please initiate a new thread")

@router.get("/state-loop/{supi}", status_code=200)
def state_movement(
    *,
    supi: str = Path(...),
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Get the state
    """
    return {"running": retrieve_ue_state(supi, current_user.id)}

@router.get("/state-ues", status_code=200)
def state_ues(
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Get the state
    """
    return state_manager.all_ues()

#Functions
def retrieve_ue_state(supi: str, user_id: int) -> bool:
    try:
        t = state_manager.get_thread(supi, f"{user_id}")
        return t.is_alive() if t else False
    except KeyError as ke:
        logger.error('Key Not Found in Threads Dictionary: %s', ke)
        return False

def retrieve_ues() -> dict:
    return state_manager.all_ues()

def retrieve_ue(supi: str) -> dict:
    return state_manager.get_ue(supi)


def monitoring_event_sub_validation(sub: dict, is_superuser: bool, current_user_id: int, owner_id) -> bool:
    
    if not is_superuser and (owner_id != current_user_id):
        # logging.warning("Not enough permissions")
        return False
    else:
        sub_validate_time = tools.check_expiration_time(expire_time=sub.get("monitorExpireTime"))
        sub_validate_number_of_reports = tools.check_numberOfReports(sub.get("maximumNumberOfReports"))
        if sub_validate_time and sub_validate_number_of_reports:
            return True
        else:
            return False
