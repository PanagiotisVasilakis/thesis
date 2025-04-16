import logging
import math
import sys
import os
from datetime import datetime, timedelta

# Add the root directory to the path to access our mobility models
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))))
from mobility_models.models import LinearMobilityModel, MobilityModel

class MobilityPatternAdapter:
    """
    Adapter class to integrate 3GPP-compliant mobility models with the NEF Emulator.
    This bridges our standalone mobility models with the existing UE movement system.
    """
    
    @staticmethod
    def get_mobility_model(model_type, ue_id, **params):
        """
        Factory method to create a mobility model instance
        
        Args:
            model_type (str): Type of mobility model ('linear', 'l_shaped', etc.)
            ue_id (str): UE identifier
            **params: Additional parameters needed for the specific model
        
        Returns:
            MobilityModel: An instance of the appropriate mobility model
        """
        if model_type == "linear":
            # For linear model, we need start_position, end_position, and speed
            return LinearMobilityModel(
                ue_id=ue_id,
                start_position=params.get("start_position", (0, 0, 0)),
                end_position=params.get("end_position", (100, 0, 0)),
                speed=params.get("speed", 1.0)
            )
        # Add other model types here as we implement them
        
        # Default case
        raise ValueError(f"Unsupported mobility model type: {model_type}")
    
    @staticmethod
    def generate_path_points(model, duration=300, time_step=1.0):
        """
        Generate path points using a mobility model that can be used by the NEF Emulator
        
        Args:
            model (MobilityModel): Mobility model instance
            duration (int): Duration of the path in seconds
            time_step (float): Time step between points in seconds
        
        Returns:
            list: List of points in format expected by NEF Emulator
        """
        # Generate trajectory using the mobility model
        trajectory = model.generate_trajectory(duration, time_step)
        
        # Convert to format expected by NEF Emulator
        nef_points = []
        for point in trajectory:
            # NEF Emulator expects points with latitude and longitude
            # We assume our mobility model has (x, y, z) coordinates
            # Here we do a simple conversion (in a real implementation, this would use proper geo-coordinates)
            nef_point = {
                "latitude": point['position'][0],  # Using x as latitude for simplicity
                "longitude": point['position'][1], # Using y as longitude for simplicity
                # Add any other fields needed by NEF Emulator
            }
            nef_points.append(nef_point)
        
        return nef_points
    
    @staticmethod
    def convert_existing_path_to_model(points, ue_id, speed='LOW'):
        """
        Convert an existing path from NEF Emulator to our mobility model format
        
        Args:
            points (list): List of points from NEF Emulator
            ue_id (str): UE identifier
            speed (str): Speed setting ('LOW' or 'HIGH')
        
        Returns:
            MobilityModel: A mobility model representing the path
        """
        # Extract start and end points
        if not points:
            raise ValueError("Empty points list")
        
        start_point = (points[0]['latitude'], points[0]['longitude'], 0)
        end_point = (points[-1]['latitude'], points[-1]['longitude'], 0)
        
        # Convert speed string to numeric value
        speed_value = 1.0 if speed == 'LOW' else 10.0  # 1 m/s for LOW, 10 m/s for HIGH
        
        # Create a linear model (simplification - in reality we might want to detect the pattern)
        return LinearMobilityModel(ue_id=ue_id, start_position=start_point, end_position=end_point, speed=speed_value)
