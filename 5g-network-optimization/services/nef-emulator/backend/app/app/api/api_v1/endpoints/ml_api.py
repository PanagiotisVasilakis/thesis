# services/nef-emulator/backend/app/app/api/api_v1/endpoints/ml_api.py

from enum import Enum
from typing import Optional

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


class HandoverMode(str, Enum):
    """Supported handover decision modes for thesis experiments."""
    ML = "ml"           # Pure ML predictions, no fallback
    A3 = "a3"           # Pure 3GPP A3 rule-based decisions
    HYBRID = "hybrid"   # ML primary with A3 fallback on failures


class ModeRequest(BaseModel):
    """Request body for setting handover mode."""
    mode: Optional[HandoverMode] = None
    # Legacy support for use_ml boolean
    use_ml: Optional[bool] = None


def _get_current_mode() -> str:
    """Get the current handover mode as a string."""
    if hasattr(engine, 'handover_mode'):
        return engine.handover_mode
    # Fallback for engines without handover_mode attribute
    return "ml" if engine.use_ml else "a3"


def _set_engine_mode(mode: str) -> None:
    """Set the engine to the specified mode."""
    # Validate mode string
    valid_modes = {"ml", "a3", "hybrid"}
    if mode not in valid_modes:
        raise ValueError(f"Invalid mode: {mode}. Must be one of {valid_modes}")
    
    # Set the new handover_mode attribute
    engine.handover_mode = mode
    
    # Also update use_ml for backward compatibility
    engine.use_ml = mode in ("ml", "hybrid")
    
    # Disable auto mode when manually setting mode
    try:
        engine._auto = False
    except AttributeError:
        pass


@router.get("/mode")
def get_mode():
    """Return the current handover mode for observability tools.
    
    Returns:
        mode: Current mode ("ml", "a3", or "hybrid")
        use_ml: Legacy boolean for backward compatibility
    """
    current_mode = _get_current_mode()
    return {
        "mode": current_mode,
        "use_ml": current_mode in ("ml", "hybrid"),
    }


@router.post("/mode")
def set_mode(payload: ModeRequest):
    """Set the handover engine mode.
    
    Supports three modes for thesis experiments:
    - ml: Pure ML predictions without A3 fallback
    - a3: Pure 3GPP A3 rule-based decisions  
    - hybrid: ML primary with A3 fallback on low confidence/QoS failures
    
    Also supports legacy use_ml boolean for backward compatibility.
    """
    if payload.mode is not None:
        # New 3-mode API
        _set_engine_mode(payload.mode.value)
    elif payload.use_ml is not None:
        # Legacy boolean API - map to hybrid (existing behavior) or a3
        _set_engine_mode("hybrid" if payload.use_ml else "a3")
    else:
        raise HTTPException(
            status_code=400,
            detail="Either 'mode' or 'use_ml' must be provided"
        )
    
    current_mode = _get_current_mode()
    return {
        "mode": current_mode,
        "use_ml": current_mode in ("ml", "hybrid"),
    }

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
