from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from typing import Any, List
from app.api import deps
from app.models import User
from app.tools.mobility.adapter import MobilityPatternAdapter
from pydantic import BaseModel, Field

router = APIRouter()

class MobilityModelRequest(BaseModel):
    """Request model for creating mobility patterns"""
    model_type: str = Field(..., description="Type of mobility model (linear, l_shaped)")
    ue_id: str = Field(..., description="UE identifier")
    duration: int = Field(300, description="Duration of the trajectory in seconds")
    time_step: float = Field(1.0, description="Time step between points in seconds")
    parameters: dict = Field({}, description="Model-specific parameters")

@router.post("/generate", response_model=List[dict])
def generate_mobility_pattern(
    *,
    req: MobilityModelRequest = Body(...),
    current_user: User = Depends(deps.get_current_active_user),
    db: Session = Depends(deps.get_db)
) -> Any:
    """
    Generate a mobility pattern based on 3GPP models
    """
    try:
        # Create mobility model
        model = MobilityPatternAdapter.get_mobility_model(
            model_type=req.model_type,
            ue_id=req.ue_id,
            **req.parameters
        )
        
        # Generate path points
        points = MobilityPatternAdapter.generate_path_points(
            model=model,
            duration=req.duration,
            time_step=req.time_step
        )
        
        return points
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating mobility pattern: {str(e)}")
