# File: backend/app/app/tools/mobility/adapter.py

"""Comprehensive adapter for integrating 3GPP mobility models with NEF emulator."""
import os
import json
import logging
from typing import Dict, List, Any
from datetime import datetime

# Import mobility models
from ...mobility_models.models import (
    MobilityModel, 
    LinearMobilityModel, 
    LShapedMobilityModel,
    RandomDirectionalMobilityModel,
    UrbanGridMobilityModel,
    ReferencePointGroupMobilityModel
)

# Set up logging
logger = logging.getLogger(__name__)

class MobilityPatternAdapter:
    """Adapter class for transforming between mobility models and NEF emulator formats."""
    
    # Registered model types
    MODEL_TYPES = {
        "linear": LinearMobilityModel,
        "l_shaped": LShapedMobilityModel,
        "random_directional": RandomDirectionalMobilityModel,
        "urban_grid": UrbanGridMobilityModel,
        "group": ReferencePointGroupMobilityModel
    }
    
    
    @classmethod
    def get_mobility_model(cls, model_type: str, ue_id: str, **params) -> MobilityModel:
        """
        Create a mobility model of the specified type with given parameters.
        
        Args:
            model_type: Type of model ("linear", "l_shaped", etc)
            ue_id: UE identifier
            **params: Model-specific parameters
            
        Returns:
            Initialized mobility model
            
        Raises:
            ValueError: If model_type is not supported
        """
        if model_type not in cls.MODEL_TYPES:
            raise ValueError(f"Unsupported mobility model type: {model_type}. "
                             f"Supported types: {list(cls.MODEL_TYPES.keys())}")
        
        model_class = cls.MODEL_TYPES[model_type]
        
        try:
            if model_type == "linear":
                required_params = ["start_position", "end_position", "speed"]
                cls._validate_required_params(params, required_params)
                return model_class(
                    ue_id=ue_id,
                    start_position=params["start_position"],
                    end_position=params["end_position"],
                    speed=params["speed"],
                    start_time=params.get("start_time"),
                    seed=params.get("seed")
                )
            elif model_type == "l_shaped":
                required_params = ["start_position", "corner_position", "end_position", "speed"]
                cls._validate_required_params(params, required_params)
                return model_class(
                    ue_id=ue_id,
                    start_position=params["start_position"],
                    corner_position=params["corner_position"],
                    end_position=params["end_position"],
                    speed=params["speed"],
                    start_time=params.get("start_time"),
                    seed=params.get("seed")
                )
            elif model_type == "random_directional":
                required_params = ["start_position", "speed"]
                cls._validate_required_params(params, required_params)
                return model_class(
                    ue_id=ue_id,
                    start_position=params["start_position"],
                    speed=params["speed"],
                    area_bounds=params.get("area_bounds"),
                    direction_change_mean=params.get("direction_change_mean", 30.0),
                    start_time=params.get("start_time"),
                    seed=params.get("seed")
                )
            elif model_type == "urban_grid":
                required_params = ["start_position", "speed"]
                cls._validate_required_params(params, required_params)
                return model_class(
                    ue_id=ue_id,
                    start_position=params["start_position"],
                    speed=params["speed"],
                    grid_size=params.get("grid_size", 50.0),
                    turn_probability=params.get("turn_probability", 0.3),
                    start_time=params.get("start_time"),
                    seed=params.get("seed")
                )
            elif model_type == "group":
                required_params = ["reference_model", "relative_position"]
                cls._validate_required_params(params, required_params)
                return model_class(
                    ue_id=ue_id,
                    reference_model=params["reference_model"],
                    relative_position=params["relative_position"],
                    max_deviation=params.get("max_deviation", 5.0),
                    deviation_change_mean=params.get("deviation_change_mean", 10.0),
                    start_time=params.get("start_time"),
                    seed=params.get("seed")
                )
        except Exception as e:
            logger.error(f"Error creating mobility model: {str(e)}")
            raise
    
    @classmethod
    def generate_path_points(cls, model: MobilityModel, duration: float = 300.0, 
                           time_step: float = 1.0) -> List[Dict[str, Any]]:
        """
        Generate path points using the given mobility model.
        
        Args:
            model: Mobility model instance
            duration: Duration in seconds
            time_step: Time step in seconds
            
        Returns:
            List of points in NEF-compatible format
        """
        try:
            # Generate trajectory using the model
            trajectory = model.generate_trajectory(duration, time_step)
            
            # Convert to NEF format
            nef_points = []
            for i, point in enumerate(trajectory):
                position = point["position"]
                nef_point = {
                    "latitude": float(position[0]),   # X coordinate
                    "longitude": float(position[1]),  # Y coordinate
                    "altitude": float(position[2]) if len(position) > 2 else 0.0,
                    "description": f"Point {i} for {model.ue_id}",
                    "timestamp": point["timestamp"].isoformat() if isinstance(point.get("timestamp"), datetime) else None
                }
                nef_points.append(nef_point)
            
            return nef_points
        except Exception as e:
            logger.error(f"Error generating path points: {str(e)}")
            raise
    
    @classmethod
    def save_path_to_json(cls, points: List[Dict[str, Any]], 
                         filename: str = "generated_path.json") -> str:
        """
        Save path points to a JSON file.
        
        Args:
            points: List of path points
            filename: Output filename
            
        Returns:
            Path to the saved file
        """
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(os.path.abspath(filename)) or '.', exist_ok=True)
            
            # Clean up points for JSON serialization
            clean_points = []
            for point in points:
                clean_point = {k: v for k, v in point.items() if v is not None}
                clean_points.append(clean_point)
                
            # Save to file
            with open(filename, 'w') as f:
                json.dump(clean_points, f, indent=2)
                
            logger.info(f"Path saved to {filename}")
            return filename
        except Exception as e:
            logger.error(f"Error saving path to JSON: {str(e)}")
            raise
    
    @classmethod
    def _validate_required_params(cls, params: Dict[str, Any], required: List[str]) -> None:
        """Validate that all required parameters are present."""
        missing = [param for param in required if param not in params or params.get(param) is None]
        if missing:
            raise ValueError(f"Missing required parameters: {missing}")
