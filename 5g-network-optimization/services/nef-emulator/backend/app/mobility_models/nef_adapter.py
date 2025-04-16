"""Adapter to convert mobility model trajectories to NEF-compatible path points."""
import json
import os
from .models import LinearMobilityModel, LShapedMobilityModel

def generate_nef_path_points(model_type, **params):
    """
    Generate path points in NEF emulator format
    
    Args:
        model_type: Type of mobility model ('linear', 'l_shaped')
        **params: Parameters for the mobility model
        
    Required parameters:
        - ue_id: UE identifier
        - start_position: Starting position (x, y, z)
        - end_position: Ending position (x, y, z) for linear model
        - corner_position: Corner position (x, y, z) for l_shaped model
        - speed: Speed in m/s
        - duration: Duration in seconds
        - time_step: Time step in seconds
        
    Returns:
        List of points in NEF format
    """
    # Extract common parameters
    ue_id = params.get('ue_id', 'test_ue')
    start_position = params.get('start_position', (0, 0, 0))
    speed = params.get('speed', 1.0)
    duration = params.get('duration', 300)
    time_step = params.get('time_step', 1.0)
    
    # Create the appropriate model
    if model_type == 'linear':
        end_position = params.get('end_position', (100, 0, 0))
        model = LinearMobilityModel(ue_id, start_position, end_position, speed)
    elif model_type == 'l_shaped':
        corner_position = params.get('corner_position', (50, 0, 0))
        end_position = params.get('end_position', (50, 50, 0))
        model = LShapedMobilityModel(ue_id, start_position, corner_position, end_position, speed)
    else:
        raise ValueError(f"Unknown mobility model type: {model_type}")
    
    # Generate trajectory
    trajectory = model.generate_trajectory(duration, time_step)
    
    # Convert to NEF format
    nef_points = []
    for i, point in enumerate(trajectory):
        nef_point = {
            "latitude": point['position'][0],   # X coordinate
            "longitude": point['position'][1],  # Y coordinate
            "description": f"Point {i} for {ue_id}"
        }
        nef_points.append(nef_point)
    
    return nef_points

def save_path_to_json(points, filename='generated_path.json'):
    """Save generated path points to a JSON file."""
    with open(filename, 'w') as f:
        json.dump(points, f, indent=2)
    print(f"Path saved to {filename}")
    
    return filename
