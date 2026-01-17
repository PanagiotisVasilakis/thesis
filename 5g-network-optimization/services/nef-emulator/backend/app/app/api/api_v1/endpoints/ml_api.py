# services/nef-emulator/backend/app/app/api/api_v1/endpoints/ml_api.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

try:
    from app.handover.runtime import runtime
except ImportError:  # pragma: no cover - fallback for test stubs
    runtime = None
    from app.network.state_manager import NetworkStateManager
    from app.handover.engine import HandoverEngine

from app.monitoring import metrics

router = APIRouter(
    tags=["ml-service"]
)

# Single, shared NetworkStateManager instance
if runtime is None:
    state_mgr = NetworkStateManager()
    engine = HandoverEngine(state_mgr)
else:
    state_mgr = runtime.state_manager
    engine = runtime.engine


class ModeRequest(BaseModel):
    use_ml: bool


@router.get("/mode")
def get_mode():
    """Return the current handover mode for observability tools."""
    return {"mode": "ml" if engine.use_ml else "a3", "use_ml": engine.use_ml}


@router.post("/mode")
def set_mode(payload: ModeRequest):
    """Toggle the handover engine between ML and A3 modes."""
    engine.use_ml = bool(payload.use_ml)
    # Disable auto mode when manually setting mode
    try:
        engine._auto = False
    except AttributeError:
        pass  # _auto may not exist in all engine implementations
    return {"mode": "ml" if engine.use_ml else "a3", "use_ml": engine.use_ml}

@router.get("/state/{ue_id}")
def get_feature_vector(ue_id: str):
    """
    Return the ML feature vector for a given UE.
    GET /api/v1/ml/state/{ue_id}
    """
    try:
        features = state_mgr.get_feature_vector(ue_id)
        return features
    except KeyError as err:
        raise HTTPException(status_code=404, detail=str(err))

@router.post("/handover")
def apply_handover(ue_id: str):
    """
    Apply a handover decision using either a rule-based or ML approach.
    POST /api/v1/ml/handover?ue_id=<>
    """
    try:
        result = engine.decide_and_apply(ue_id)
        if result is None:
            metrics.HANDOVER_DECISIONS.labels(outcome="none").inc()
            raise HTTPException(status_code=400, detail="No handover triggered")
        metrics.HANDOVER_DECISIONS.labels(outcome="applied").inc()
        return result
    except KeyError as err:
        raise HTTPException(status_code=404, detail=str(err))
