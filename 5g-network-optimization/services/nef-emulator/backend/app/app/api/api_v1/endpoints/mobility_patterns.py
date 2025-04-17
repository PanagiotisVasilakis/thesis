# File: backend/app/app/api/api_v1/endpoints/mobility_patterns.py

from typing import Dict, List, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel, Field

from app.api import deps
from app.tools.mobility.adapter import MobilityPatternAdapter
from app.models.user import User

router = APIRouter()

class MobilityParameters(BaseModel):
    """Parameters for the mobility model."""
    # Common parameters
    start_position: List[float] = Field(..., description="Starting position (x, y, z)")
    speed: Optional[float] = Field(None, description="Speed in m/s")
    
    # Linear model parameters
    end_position: Optional[List[float]] = Field(None, description="Ending position for linear model")
    
    # L-shaped model parameters
    corner_position: Optional[List[float]] = Field(None, description="Corner position for L-shaped model")
    
    # Random directional model parameters
    area_bounds: Optional[List[List[float]]] = Field(None, description="Area bounds [(min_x, max_x), (min_y, max_y), (min_z, max_z)]")
    direction_change_mean: Optional[float] = Field(None, description="Mean time between direction changes in seconds")
    
    # Urban grid model parameters
    grid_size: Optional[float] = Field(None, description="Size of grid cells (distance between streets)")
    turn_probability: Optional[float] = Field(None, description="Probability of turning at an intersection")
    
    # Group model parameters
    reference_model_type: Optional[str] = Field(None, description="Type of reference mobility model")
    reference_model_params: Optional[Dict[str, Any]] = Field(None, description="Parameters for reference mobility model")
    relative_position: Optional[List[float]] = Field(None, description="Position relative to reference point")
    max_deviation: Optional[float] = Field(None, description="Maximum deviation from relative position")
    deviation_change_mean: Optional[float] = Field(None, description="Mean time between deviation changes")

class MobilityPatternRequest(BaseModel):
    """Request body for generating a mobility pattern."""
    model_type: str = Field(..., description="Type of mobility model (linear, l_shaped)")
    ue_id: str = Field(..., description="UE identifier")
    duration: float = Field(300.0, description="Duration in seconds")
    time_step: float = Field(1.0, description="Time step in seconds")
    parameters: MobilityParameters = Field(..., description="Model-specific parameters")

@router.post("/generate", response_model=List[Dict[str, Any]])
def generate_mobility_pattern(
    request: MobilityPatternRequest = Body(...),
    current_user: User = Depends(deps.get_current_active_user)
) -> List[Dict[str, Any]]:
    """
    Generate mobility pattern using the specified model.
    """
    try:
        params = request.parameters.dict()
        
        # Convert list parameters to tuples
        for key in ["start_position", "end_position", "corner_position", "relative_position"]:
            if key in params and params[key] is not None:
                params[key] = tuple(params[key])
        
        if "area_bounds" in params and params["area_bounds"] is not None:
            params["area_bounds"] = [tuple(bounds) for bounds in params["area_bounds"]]
        
        # Special handling for group mobility
        if request.model_type == "group" and params.get("reference_model_type"):
            # Create reference model first
            ref_model_type = params.pop("reference_model_type")
            ref_model_params = params.pop("reference_model_params", {})
            
            # Convert list parameters to tuples in ref_model_params
            for key in ["start_position", "end_position", "corner_position"]:
                if key in ref_model_params and ref_model_params[key] is not None:
                    ref_model_params[key] = tuple(ref_model_params[key])
            
            reference_model = MobilityPatternAdapter.get_mobility_model(
                model_type=ref_model_type,
                ue_id=f"{request.ue_id}_reference",
                **ref_model_params
            )
            
            # Add reference model to params
            params["reference_model"] = reference_model
        
        # Create model
        model = MobilityPatternAdapter.get_mobility_model(
            model_type=request.model_type,
            ue_id=request.ue_id,
            **params
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