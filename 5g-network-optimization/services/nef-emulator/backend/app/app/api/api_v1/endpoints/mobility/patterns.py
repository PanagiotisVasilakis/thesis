"""API endpoints for mobility patterns."""
from typing import Dict, List, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel, Field

from app.api import deps
from app.tools.mobility.adapter import MobilityPatternAdapter
from app.models.user import User

router = APIRouter()

class MobilityPatternRequest(BaseModel):
    """Request body for generating a mobility pattern."""
    model_type: str = Field(..., description="Type of mobility model (linear, l_shaped, random_directional, urban_grid, group)")
    ue_id: str = Field(..., description="UE identifier")
    duration: float = Field(300.0, description="Duration in seconds")
    time_step: float = Field(1.0, description="Time step in seconds")
    parameters: Dict[str, Any] = Field(..., description="Model-specific parameters")

@router.post("/generate", response_model=List[Dict[str, Any]])
def generate_mobility_pattern(
    request: MobilityPatternRequest = Body(...),
    current_user: User = Depends(deps.get_current_active_user)
) -> List[Dict[str, Any]]:
    """
    Generate mobility pattern using the specified model.
    """
    try:
        # Create model
        model = MobilityPatternAdapter.get_mobility_model(
            model_type=request.model_type,
            ue_id=request.ue_id,
            **request.parameters
        )
        
        # Generate path points
        points = MobilityPatternAdapter.generate_path_points(
            model=model,
            duration=request.duration,
            time_step=request.time_step
        )
        
        return points
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating mobility pattern: {str(e)}")
