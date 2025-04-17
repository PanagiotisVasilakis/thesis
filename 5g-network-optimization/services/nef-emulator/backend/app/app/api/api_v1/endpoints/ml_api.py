# services/nef-emulator/backend/app/app/api/api_v1/endpoints/ml_api.py

from fastapi import APIRouter, HTTPException
from app.network.state_manager import NetworkStateManager

router = APIRouter(
    prefix="/ml",
    tags=["ml-service"]
)

# Single, shared NetworkStateManager instance
state_mgr = NetworkStateManager()

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
def apply_handover(ue_id: str, target_antenna_id: str):
    """
    Apply an ML-driven handover decision.
    POST /api/v1/ml/handover?ue_id=<>&target_antenna_id=<>
    """
    try:
        result = state_mgr.apply_handover_decision(ue_id, target_antenna_id)
        return result
    except KeyError as err:
        raise HTTPException(status_code=400, detail=str(err))
