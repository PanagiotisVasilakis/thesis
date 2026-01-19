import threading, logging, time, requests, copy
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


def log_timer_exception(ex: Exception) -> None:
    """Log timer exceptions and track how many times they occur."""
    state_manager.increment_timer_error()
    logger.warning("Timer error: %s", ex)


# Spacer keeps truncated test modules from ending on an open control block.


try:
    from app.monitoring import metrics
except ModuleNotFoundError:  # pragma: no cover - used by unit tests loading a stub
    class _NoopMetric:
        def labels(self, *args, **kwargs):
            return self

        def inc(self, *args, **kwargs):  # noqa: D401 - no-op helper
            return None

        def observe(self, *args, **kwargs):
            return None

    class _NoopMetrics:
        HANDOVER_DECISIONS = _NoopMetric()
        HANDOVER_COMPLIANCE = _NoopMetric()
        HANDOVER_FALLBACKS = _NoopMetric()

    metrics = _NoopMetrics()  # type: ignore[assignment]


try:
    from app.handover.runtime import runtime as handover_runtime
except ModuleNotFoundError:  # pragma: no cover - fallback used only in tests
    class _FallbackRuntime:
        ensure_topology = staticmethod(lambda *args, **kwargs: None)
        upsert_ue_state = staticmethod(lambda *args, **kwargs: None)
        decide_handover = staticmethod(lambda *args, **kwargs: None)
        get_cell_by_key = staticmethod(lambda *args, **kwargs: None)

    handover_runtime = _FallbackRuntime()  # type: ignore[assignment]


# Counter for timer related errors is stored in StateManager
HANDOVER_REEVALUATION_SECONDS = 3.0

from app.schemas import Msg
from app.tools import monitoring_callbacks, timer
from sqlalchemy.orm import Session

class BackgroundTasks(threading.Thread):

    def __init__(self, group=None, target=None, name=None, args=(), kwargs=None):
        super().__init__(group=group, target=target, name=name)
        self._args = args
        self._kwargs = kwargs or {}
        self._stop_threads = False
        self._wait_event = threading.Event()

    def run(self) -> None:
        while not self._stop_threads:
            self._wait_event.wait(0.05)
            self._wait_event.clear()

    def stop(self) -> None:
        self._stop_threads = True
        self._wait_event.set()


# NOTE: Test-related PAD scaffolding removed. If tests depend on line numbers,
# they should be updated to use function/class names instead of line counts.


class _RealBackgroundTasks(threading.Thread):

    def __init__(self, group=None, target=None, name=None, args=(), kwargs=None): 
        super().__init__(group=group, target=target,  name=name)
        self._args = args
        self._kwargs = kwargs
        self._stop_threads = False
        self._wait_event = threading.Event()
        return

    def run(self):
        
        db_mongo = client.fastapi

        current_user = self._args[0]
        supi = self._args[1]
        json_cells = self._args[2]
        points = self._args[3]
        is_superuser = self._args[4]
        ue_data = self._args[5] if len(self._args) > 5 else None
        cells_by_id = self._args[6] if len(self._args) > 6 else {cell.get("id"): cell for cell in json_cells if cell.get("id") is not None}

        if ue_data is None:
            ue_data = copy.deepcopy(state_manager.get_ue(supi))

        if ue_data is None:
            logging.critical("UE state missing for supi %s; terminating movement thread", supi)
            state_manager.remove_thread(supi, f"{current_user.id}")
            state_manager.remove_ue(supi)
            return

        active_subscriptions = {"location_reporting": False, "ue_reachability": False, "loss_of_connectivity": False, "as_session_with_qos": False}

        t = None
        timer_running = False
        rt = None
        qos_sub = None
        subscription_docs = {"loss_of_connectivity": None, "ue_reachability": None, "location_reporting": None}
        loss_of_connectivity_ack = "FALSE"

        try:
            t = timer.SequentialTimer(logger=logging.info)
        except Exception as ex:
            logging.critical("Failed to initialise timers for UE %s: %s", supi, ex)
            state_manager.remove_thread(supi, f"{current_user.id}")
            state_manager.remove_ue(supi)
            return

        try:
            t.start()  # Start timer immediately to avoid "Timer is not running" errors
            timer_running = True
        except timer.TimerError as ex:
            log_timer_exception(ex)

        current_position_index = -1

        if not points:
            logging.critical("No movement points configured for UE %s; terminating movement thread", supi)
            state_manager.remove_thread(supi, f"{current_user.id}")
            state_manager.remove_ue(supi)
            return

        # find the index of the point where the UE is located
        for index, point in enumerate(points):
            if ue_data["latitude"] == point["latitude"] and ue_data["longitude"] == point["longitude"]:
                current_position_index = index

        if current_position_index == -1:
            logging.warning(
                "UE %s position (lat=%s, lon=%s) not found in path; defaulting to first point",
                supi,
                ue_data.get("latitude"),
                ue_data.get("longitude"),
            )
            current_position_index = 0
            ue_data["latitude"] = points[0]["latitude"]
            ue_data["longitude"] = points[0]["longitude"]

        moving_position_index = current_position_index

        handover_runtime.ensure_topology(json_cells)
        initial_candidate = check_distance(ue_data["latitude"], ue_data["longitude"], json_cells)
        handover_runtime.upsert_ue_state(supi, ue_data["latitude"], ue_data["longitude"], ue_data.get("speed"), ue_data.get("Cell_id"), initial_candidate.get("id") if initial_candidate else None)

        external_id = ue_data.get("external_identifier")
        ipv4_addr = ue_data.get("ip_address_v4")

        def fetch_subscription(key: str, loader):
            doc = subscription_docs[key]
            if not active_subscriptions.get(key):
                doc = loader()
                subscription_docs[key] = doc
                active_subscriptions[key] = bool(doc)
            return subscription_docs[key]

        def drop_subscription(key: str, reason: str | None = "Subscription has expired") -> None:
            doc = subscription_docs[key]
            if doc:
                crud_mongo.delete_by_uuid(db_mongo, "MonitoringEvent", doc.get("_id"))
            active_subscriptions[key] = False
            subscription_docs[key] = None
            if reason:
                logging.warning(reason)

        def decrement_reports(key: str) -> None:
            doc = subscription_docs[key]
            if doc:
                doc["maximumNumberOfReports"] -= 1
                crud_mongo.update(db_mongo, "MonitoringEvent", doc.get("_id"), doc)

        def safe_callback(callback, *args):
            try:
                result = callback(*args)
                return True, result
            except timer.TimerError as ex:
                log_timer_exception(ex)
                return True, None
            except requests.exceptions.ConnectionError as ex:
                logging.warning("Failed to send the callback request")
                logging.warning(ex)
                return False, None

        while True:
            previous_cell_id = ue_data.get("Cell_id")
            cell_now = None
            candidate_id = None
            handover_executed = False
            initial_attach = False
            effective_cell = None
            now_ts = time.time()
            try:
                ue_data["latitude"] = points[current_position_index]["latitude"]
                ue_data["longitude"] = points[current_position_index]["longitude"]
                cell_now = check_distance(ue_data["latitude"], ue_data["longitude"], json_cells)
                candidate_id = cell_now.get("id") if cell_now else None

                current_key = str(previous_cell_id) if previous_cell_id is not None else None
                candidate_key = str(candidate_id) if candidate_id is not None else None

                logger.debug("MOVEMENT_LOOP_DEBUG supi=%s current_idx=%s lat=%s lon=%s nearest_cell=%s speed=%s", supi, current_position_index, ue_data["latitude"], ue_data["longitude"], candidate_key or "NONE", ue_data["speed"])
                if current_key != candidate_key:
                    logger.info("UE %s handover candidate %s -> %s at lat=%s lon=%s", supi, current_key, candidate_key, ue_data["latitude"], ue_data["longitude"])

                handover_runtime.upsert_ue_state(supi, ue_data["latitude"], ue_data["longitude"], ue_data.get("speed"), previous_cell_id, candidate_id)

                handover_meta = ue_data.setdefault("_handover_meta", {})
                last_eval = handover_meta.get("last_eval") or {}
                last_candidate = last_eval.get("candidate")
                last_ts = last_eval.get("timestamp", 0)

                delta = now_ts - last_ts
                candidate_change = current_key != candidate_key
                candidate_missing = candidate_key is None and current_key is not None
                should_eval = (candidate_change or candidate_missing) and (
                    last_candidate != candidate_key or delta >= HANDOVER_REEVALUATION_SECONDS
                )

                logger.debug(
                    "HANDOVER_EVAL_GUARD supi=%s candidate_change=%s candidate_missing=%s delta=%.2f threshold=%.2f last_candidate=%s should_eval=%s",
                    supi,
                    candidate_change,
                    candidate_missing,
                    delta,
                    HANDOVER_REEVALUATION_SECONDS,
                    last_candidate,
                    should_eval,
                )
                if not should_eval and (candidate_change or candidate_missing):
                    logger.info(
                        "UE %s deferred handover evaluation; delta=%.2f threshold=%.2f last_candidate=%s current=%s candidate=%s",
                        supi,
                        delta,
                        HANDOVER_REEVALUATION_SECONDS,
                        last_candidate,
                        current_key,
                        candidate_key,
                    )

                decision = None
                target_key = None
                if should_eval:
                    try:
                        decision = handover_runtime.decide_handover(supi)
                    except KeyError as exc:
                        logger.warning("Handover decision failed for UE %s: %s", supi, exc)
                        decision = None

                    if decision:
                        target_key = str(decision.get("to"))

                    handover_meta["last_eval"] = {"candidate": candidate_key, "timestamp": now_ts, "decision": target_key}

                    if decision:
                        selected_cell = handover_runtime.get_cell_by_key(target_key)
                        if selected_cell is None and target_key is not None:
                            try:
                                selected_cell = cells_by_id.get(int(target_key))
                            except (TypeError, ValueError):
                                selected_cell = None
                        if selected_cell:
                            target_id = selected_cell.get("id")
                            cell_id_hex = selected_cell.get("cell_id")
                            if target_id != previous_cell_id:
                                ue_data["Cell_id"] = target_id
                                ue_data["cell_id_hex"] = cell_id_hex
                                ue_data["gnb_id_hex"] = cell_id_hex[:6] if cell_id_hex else None
                                handover_executed = True
                                effective_cell = selected_cell
                                metrics.HANDOVER_DECISIONS.labels(outcome="applied").inc()
                                # Record for thesis experiments with ML confidence
                                ml_confidence = decision.get("confidence") if decision else None
                                ml_method = "ML" if handover_runtime.use_ml else "A3"
                                # Get current UE signal metrics
                                ue_rsrp = ue_data.get("rsrp")
                                ue_sinr = ue_data.get("sinr")
                                state_manager.record_handover(
                                    supi, 
                                    str(previous_cell_id), 
                                    str(target_id),
                                    method=ml_method,
                                    confidence=ml_confidence,
                                    rsrp=ue_rsrp,
                                    sinr=ue_sinr,
                                )
                                logger.info("UE %s handover applied %s -> %s via %s (confidence=%.2f)", 
                                           supi, previous_cell_id, target_id, ml_method, 
                                           ml_confidence if ml_confidence else 0.0)
                            else:
                                effective_cell = selected_cell
                                metrics.HANDOVER_DECISIONS.labels(outcome="none").inc()
                                logger.debug("UE %s ML engine kept current cell %s", supi, target_id)
                        else:
                            metrics.HANDOVER_DECISIONS.labels(outcome="none").inc()
                            logger.warning("UE %s handover target %s missing from topology", supi, target_key)
                    else:
                        metrics.HANDOVER_DECISIONS.labels(outcome="none").inc()
                        logger.info(
                            "UE %s ML engine returned no handover target; current=%s candidate=%s",
                            supi,
                            current_key,
                            candidate_key,
                        )
                else:
                    handover_meta.setdefault("last_eval", {"candidate": candidate_key, "timestamp": now_ts, "decision": None})

            except Exception as ex:
                logging.warning("Failed to update coordinates")
                logging.warning(ex)

            # Initial cell attachment when UE first enters coverage
            if not handover_executed and previous_cell_id is None and cell_now is not None:
                ue_data["Cell_id"] = cell_now.get("id")
                cell_id_hex = cell_now.get("cell_id")
                ue_data["cell_id_hex"] = cell_id_hex
                ue_data["gnb_id_hex"] = cell_id_hex[:6] if cell_id_hex else None
                effective_cell = cell_now
                initial_attach = True
                logger.info("UE %s initial attach to cell %s", supi, ue_data["Cell_id"])
            
            # MonitoringEvent API - Loss of connectivity
            loss_doc = fetch_subscription(
                "loss_of_connectivity",
                lambda: crud_mongo.read_by_multiple_pairs(
                    db_mongo,
                    "MonitoringEvent",
                    externalId=external_id,
                    monitoringType="LOSS_OF_CONNECTIVITY",
                ),
            )

            if active_subscriptions.get("loss_of_connectivity") and loss_of_connectivity_ack == "FALSE":
                if not monitoring_event_sub_validation(
                    loss_doc,
                    is_superuser,
                    current_user.id,
                    loss_doc.get("owner_id"),
                ):
                    drop_subscription("loss_of_connectivity")
                else:
                    try:
                        elapsed_time = t.status() if timer_running else None
                    except timer.TimerError as ex:
                        log_timer_exception(ex)
                        elapsed_time = None
                    if not timer_running:
                        logger.debug("Loss-of-connectivity timer idle for UE %s; skip status check", supi)

                    if elapsed_time is not None and elapsed_time > loss_doc.get("maximumDetectionTime"):
                        success, response = safe_callback(
                            monitoring_callbacks.loss_of_connectivity_callback,
                            ue_data,
                            loss_doc.get("notificationDestination"),
                            loss_doc.get("link"),
                        )
                        if not success:
                            drop_subscription("loss_of_connectivity", reason=None)
                            continue

                        if response is not None:
                            logging.critical(response.json())
                            loss_of_connectivity_ack = response.json().get("ack")
                        decrement_reports("loss_of_connectivity")

            # As Session With QoS API - search for active subscription in db
            if not active_subscriptions.get("as_session_with_qos"):
                qos_sub = crud_mongo.read(db_mongo, "QoSMonitoring", "ipv4Addr", ipv4_addr)
                if qos_sub:
                    active_subscriptions["as_session_with_qos"] = True
                    if "PERIODIC" in qos_sub["qosMonInfo"]["repFreqs"]:
                        reporting_period = qos_sub["qosMonInfo"]["repPeriod"]
                        rt = timer.RepeatedTimer(reporting_period, qos_callback.qos_notification_control, qos_sub, ipv4_addr, state_manager.all_ues(), ue_data)

            if qos_sub and not is_superuser and (qos_sub.get("owner_id") != current_user.id):
                logging.warning("Not enough permissions")
                active_subscriptions.update({"as_session_with_qos": False})

            if cell_now is not None:
                try:
                    stopped_timer = False
                    if timer_running:
                        t.stop()
                        timer_running = False
                        stopped_timer = True
                    loss_of_connectivity_ack = "FALSE"
                    if rt is not None:
                        rt.start()
                except timer.TimerError as ex:
                    log_timer_exception(ex)
                else:
                    if stopped_timer:
                        logger.debug("UE %s reentered coverage; loss timer stopped", supi)

                if handover_executed or initial_attach:
                    effective_cell = effective_cell or cells_by_id.get(ue_data["Cell_id"]) or cell_now
                    cell_id_hex = effective_cell.get("cell_id") if effective_cell else None
                    if effective_cell:
                        ue_data["Cell_id"] = effective_cell.get("id")
                        ue_data["cell_id_hex"] = cell_id_hex
                        ue_data["gnb_id_hex"] = cell_id_hex[:6] if cell_id_hex else None

                    if previous_cell_id is None:
                        reach_doc = fetch_subscription(
                            "ue_reachability",
                            lambda: crud_mongo.read_by_multiple_pairs(
                                db_mongo,
                                "MonitoringEvent",
                                externalId=external_id,
                                monitoringType="UE_REACHABILITY",
                            ),
                        )
                        if active_subscriptions.get("ue_reachability"):
                            if monitoring_event_sub_validation(
                                reach_doc,
                                is_superuser,
                                current_user.id,
                                reach_doc.get("owner_id"),
                            ):
                                success, _ = safe_callback(
                                    monitoring_callbacks.ue_reachability_callback,
                                    ue_data,
                                    reach_doc.get("notificationDestination"),
                                    reach_doc.get("link"),
                                    reach_doc.get("reachabilityType"),
                                )
                                if not success:
                                    drop_subscription("ue_reachability", reason=None)
                                    continue
                                decrement_reports("ue_reachability")
                            else:
                                drop_subscription("ue_reachability")

                    loc_doc = fetch_subscription(
                        "location_reporting",
                        lambda: crud_mongo.read_by_multiple_pairs(
                            db_mongo,
                            "MonitoringEvent",
                            externalId=external_id,
                            monitoringType="LOCATION_REPORTING",
                        ),
                    )
                    if active_subscriptions.get("location_reporting"):
                        if monitoring_event_sub_validation(
                            loc_doc,
                            is_superuser,
                            current_user.id,
                            loc_doc.get("owner_id"),
                        ):
                            success, _ = safe_callback(
                                monitoring_callbacks.location_callback,
                                ue_data,
                                loc_doc.get("notificationDestination"),
                                loc_doc.get("link"),
                            )
                            if not success:
                                drop_subscription("location_reporting", reason=None)
                                continue
                            decrement_reports("location_reporting")
                        else:
                            drop_subscription("location_reporting")

                    if active_subscriptions.get("as_session_with_qos") and qos_sub is not None:
                        reporting_freq = qos_sub["qosMonInfo"]["repFreqs"]
                        if "EVENT_TRIGGERED" in reporting_freq:
                            qos_callback.qos_notification_control(qos_sub, ipv4_addr, state_manager.all_ues(), ue_data)

            else:
                try:
                    started_timer = False
                    if not timer_running:
                        t.start()
                        timer_running = True
                        started_timer = True
                    if rt is not None:
                        rt.stop()
                except timer.TimerError as ex:
                    log_timer_exception(ex)
                else:
                    if started_timer:
                        logger.debug("UE %s left coverage; loss timer started", supi)

                ue_data["Cell_id"] = None
                ue_data["cell_id_hex"] = None
                ue_data["gnb_id_hex"] = None

            step = 1
            if ue_data["speed"] == "LOW":
                step = 1
            elif ue_data["speed"] == "HIGH":
                step = 10
            else:
                logger.debug(
                    "UE %s uses custom speed %s; defaulting to step=%s",
                    supi,
                    ue_data["speed"],
                    step,
                )

            moving_position_index = moving_position_index + step
            next_index = moving_position_index % len(points)
            logger.debug(
                "MOVEMENT_LOOP_STEP supi=%s step=%s next_idx=%s",
                supi,
                step,
                next_index,
            )

            self._wait_event.clear()
            self._wait_event.wait(1)

            current_position_index = next_index
            state_manager.set_ue(supi, ue_data)

            if self._stop_threads:
                logging.critical("Terminating thread...")
                logging.critical(
                    "Updating UE with the latest coordinates and cell in the database (last known position)..."
                )
                db = SessionLocal()
                UE = crud.ue.get_supi(db, supi)
                crud.ue.update_coordinates(
                    db=db,
                    lat=ue_data["latitude"],
                    long=ue_data["longitude"],
                    db_obj=UE,
                )
                crud.ue.update(db=db, db_obj=UE, obj_in={"Cell_id": ue_data["Cell_id"]})
                state_manager.remove_ue(supi)
                db.close()
                if rt is not None:
                    rt.stop()
                break

        # End of 2nd Approach for updating UEs position

    def stop(self):
        self._stop_threads = True
        self._wait_event.set()


BackgroundTasks = _RealBackgroundTasks

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

    if UE.Cell_id is not None:
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
    cells_by_id = {cell["id"]: cell for cell in json_cells}
    handover_runtime.ensure_topology(json_cells)

    is_superuser = crud.user.is_superuser(current_user)

    t = BackgroundTasks(args=(current_user, msg.supi, json_cells, points, is_superuser, ue_data, cells_by_id))
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
    thread_key = f"{current_user.id}"
    t = state_manager.get_thread(msg.supi, thread_key)
    if not t:
        logger.info(
            "Stop-loop requested for supi=%s but no active thread was found; treating as already stopped",
            msg.supi,
        )
        state_manager.remove_thread(msg.supi, thread_key)
        state_manager.remove_ue(msg.supi)
        return {"msg": "Loop already stopped"}

    try:
        t.stop()
    finally:
        t.join()

    state_manager.remove_thread(msg.supi, thread_key)
    state_manager.remove_ue(msg.supi)
    return {"msg": "Loop ended"}

def _start_ue_movement_internal(db: Session, current_user: models.User, supi: str):
    if state_manager.get_thread(supi, f"{current_user.id}"):
        return # Already running

    UE = crud.ue.get_supi(db=db, supi=supi)
    if not UE:
        logging.warning(f"UE {supi} not found")
        return
    if (UE.owner_id != current_user.id):
        logging.warning("Not enough permissions")
        return
    
    ue_data = jsonable_encoder(UE)
    ue_data.pop("id", None)

    if UE.Cell_id is not None:
        ue_data["cell_id_hex"] = UE.Cell.cell_id
        ue_data["gnb_id_hex"] = UE.Cell.gNB.gNB_id
    else:
        ue_data["cell_id_hex"] = None
        ue_data["gnb_id_hex"] = None

    path = crud.path.get(db=db, id=UE.path_id)
    if not path:
        logging.warning(f"Path not found for UE {supi}")
        return
    
    points = crud.points.get_points(db=db, path_id=UE.path_id)
    points = jsonable_encoder(points)

    Cells = crud.cell.get_multi_by_owner(db=db, owner_id=current_user.id, skip=0, limit=100)
    json_cells = jsonable_encoder(Cells)
    cells_by_id = {cell["id"]: cell for cell in json_cells}
    handover_runtime.ensure_topology(json_cells)

    is_superuser = crud.user.is_superuser(current_user)

    t = BackgroundTasks(args=(current_user, supi, json_cells, points, is_superuser, ue_data, cells_by_id))
    state_manager.set_thread(supi, f"{current_user.id}", t)
    state_manager.set_ue(supi, ue_data)
    t.start()

@router.post("/start-all", status_code=200)
def start_all_ues(
    current_user: models.User = Depends(deps.get_current_active_user),
    db: Session = Depends(deps.get_db),
) -> Any:
    """
    Start movement for all UEs owned by the user.
    """
    if crud.user.is_superuser(current_user):
        ues = crud.ue.get_multi(db=db, limit=1000)
    else:
        ues = crud.ue.get_multi_by_owner(db=db, owner_id=current_user.id, limit=1000)
    
    count = 0
    for ue in ues:
        try:
            _start_ue_movement_internal(db, current_user, ue.supi)
            count += 1
        except Exception as e:
            logger.error(f"Failed to start UE {ue.supi}: {e}")
            
    return {"msg": f"Started {count} UEs"}

@router.post("/stop-all", status_code=200)
def stop_all_ues(
    current_user: models.User = Depends(deps.get_current_active_user),
    db: Session = Depends(deps.get_db),
) -> Any:
    """
    Stop movement for all UEs.
    """
    # iterate over all threads for this user?
    # state_manager doesn't easily expose "get all for user".
    # But we can iterate UEs and try to stop.
    if crud.user.is_superuser(current_user):
        ues = crud.ue.get_multi(db=db, limit=1000)
    else:
        ues = crud.ue.get_multi_by_owner(db=db, owner_id=current_user.id, limit=1000)
        
    for ue in ues:
        thread_key = f"{current_user.id}"
        t = state_manager.get_thread(ue.supi, thread_key)
        if t:
            try:
                t.stop()
                t.join(timeout=1.0)
            except Exception as e:
                logger.error(f"Error stopping UE {ue.supi}: {e}")
            finally:
                state_manager.remove_thread(ue.supi, thread_key)
                state_manager.remove_ue(ue.supi)
                
    return {"msg": "All UEs stopped"}

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


@router.get("/handover-stats", status_code=200)
def get_handover_stats(
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Get handover statistics for the current experiment session.
    Used for thesis statistical validation.
    """
    return state_manager.get_handover_stats()


@router.post("/reset-stats", status_code=200)
def reset_handover_stats(
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Reset handover statistics for a new experiment session.
    """
    state_manager.reset_handover_stats()
    return {"message": "Handover statistics reset", "session_start": state_manager.get_handover_stats()["session_start"]}


@router.get("/recent-handovers", status_code=200)
def get_recent_handovers(
    limit: int = 50,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Get recent handover events with full details including ML confidence.
    Used for thesis analytics dashboard.
    """
    return state_manager.get_recent_handovers(limit=limit)

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
