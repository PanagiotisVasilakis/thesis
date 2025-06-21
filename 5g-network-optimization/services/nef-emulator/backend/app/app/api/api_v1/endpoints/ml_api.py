# services/nef-emulator/backend/app/app/api/api_v1/endpoints/ml_api.py

from fastapi import APIRouter, HTTPException
from app.network.state_manager import NetworkStateManager
from app.handover.engine import HandoverEngine

router = APIRouter(
    prefix="/ml",
    tags=["ml-service"]
)

# Single, shared NetworkStateManager instance
state_mgr = NetworkStateManager()
engine = HandoverEngine(state_mgr)

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
            raise HTTPException(status_code=400, detail="No handover triggered")
        return result
    except KeyError as err:
        raise HTTPException(status_code=404, detail=str(err))
