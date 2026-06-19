# services/nef-emulator/backend/app/app/api/api_v1/endpoints/ml_api.py

import os
from enum import Enum
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

try:
    from app.handover.runtime import runtime
except ImportError:  # pragma: no cover - fallback for test stubs
    if os.getenv("TESTING", "").lower() not in {"1", "true", "yes"}:
        raise

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
    FIXED_A3_BASELINE = "fixed_a3_baseline"
    TUNED_A3_BASELINE = "tuned_a3_baseline"
    COMPLEXITY_AWARE_ML_A3 = "complexity_aware_ml_a3"
    TRACE_CAPTURE = "trace_capture"  # Measurement-only mode, no decisions applied


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
    valid_modes = {
        "ml",
        "a3",
        "hybrid",
        "fixed_a3_baseline",
        "tuned_a3_baseline",
        "complexity_aware_ml_a3",
        "trace_capture",
    }
    if mode not in valid_modes:
        raise ValueError(f"Invalid mode: {mode}. Must be one of {valid_modes}")
    
    # Set the new handover_mode attribute
    engine.handover_mode = mode
    
    # Also update use_ml for backward compatibility
    engine.use_ml = mode in ("ml", "hybrid", "complexity_aware_ml_a3")
    
    # Disable auto mode when manually setting mode
    try:
        engine._auto = False
    except AttributeError:
        pass


@router.get("/mode")
def get_mode():
    """Return the current handover mode for observability tools.
    
    Returns:
        mode: Current mode
        use_ml: Legacy boolean for backward compatibility
    """
    current_mode = _get_current_mode()
    return {
        "mode": current_mode,
        "use_ml": current_mode in ("ml", "hybrid", "complexity_aware_ml_a3"),
    }


@router.post("/mode")
def set_mode(payload: ModeRequest):
    """Set the handover engine mode.
    
    Supports explicit modes for thesis experiments:
    - ml: Pure ML predictions without A3 fallback
    - a3: Pure 3GPP A3 rule-based decisions  
    - hybrid: ML primary with A3 fallback on low confidence/QoS failures
    - fixed_a3_baseline: standards-inspired non-ML baseline-service policy
    - tuned_a3_baseline: non-ML baseline-service policy using saved tuned params
    - complexity_aware_ml_a3: tuned A3 in sparse/moderate buckets, ML in high bucket
    - trace_capture: measurement-only infrastructure mode with no decisions applied
    
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
        "use_ml": current_mode in ("ml", "hybrid", "complexity_aware_ml_a3"),
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


@router.get("/rf-provenance")
def get_rf_provenance():
    if runtime is None:
        return {"fallback": True, "strict_mode": False, "antenna_count": 0}
    return runtime.rf_provenance()

@router.post("/handover")
def apply_handover(ue_id: str):
    """
    Apply a handover decision using either a rule-based or ML approach.
    POST /api/v1/ml/handover?ue_id=<>
    """
    try:
        result = engine.evaluate_and_apply_handover(ue_id, source="ml_api")
        if result is None:
            metrics.HANDOVER_DECISIONS.labels(outcome="none").inc()
            raise HTTPException(status_code=400, detail="No handover triggered")
        metrics.HANDOVER_DECISIONS.labels(outcome="applied").inc()
        return result
    except KeyError as err:
        raise HTTPException(status_code=404, detail=str(err))
