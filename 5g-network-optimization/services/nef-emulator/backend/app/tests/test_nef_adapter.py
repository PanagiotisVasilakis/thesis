"""Test the simplified NEF adapter."""
import sys
import os
import matplotlib.pyplot as plt
import json
import logging

# Add the root directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger(__name__)

# Import the adapter
from backend.app.app.mobility_models.nef_adapter import generate_nef_path_points, save_path_to_json

def test_nef_adapter():
    """Test generating and saving NEF-compatible path points."""
    # Generate linear path
    params = {
        'ue_id': 'test_ue_1',
        'start_position': (0, 0, 0),
        'end_position': (1000, 500, 0),
        'speed': 5.0,
        'duration': 250,
        'time_step': 1.0
    }
    
    linear_points = generate_nef_path_points('linear', **params)
    logger.info(f"Generated {len(linear_points)} linear path points")
    
    # Save to JSON
    linear_json = save_path_to_json(linear_points, 'linear_path.json')
    
    # Generate L-shaped path
    params = {
        'ue_id': 'test_ue_2',
        'start_position': (0, 0, 0),
        'corner_position': (500, 0, 0),
        'end_position': (500, 500, 0),
        'speed': 5.0,
        'duration': 250,
        'time_step': 1.0
    }
    
    l_shaped_points = generate_nef_path_points('l_shaped', **params)
    logger.info(f"Generated {len(l_shaped_points)} L-shaped path points")
    
    # Save to JSON
    l_shaped_json = save_path_to_json(l_shaped_points, 'l_shaped_path.json')
    
    # Visualize both paths
    plt.figure(figsize=(10, 8))
    
    # Plot linear path
    latitudes_linear = [point['latitude'] for point in linear_points]
    longitudes_linear = [point['longitude'] for point in linear_points]
    plt.plot(latitudes_linear, longitudes_linear, 'b-', linewidth=2, label='Linear')
    plt.plot(latitudes_linear[0], longitudes_linear[0], 'go', markersize=10)  # Start
    plt.plot(latitudes_linear[-1], longitudes_linear[-1], 'ro', markersize=10)  # End
    
    # Plot L-shaped path
    latitudes_l = [point['latitude'] for point in l_shaped_points]
    longitudes_l = [point['longitude'] for point in l_shaped_points]
    plt.plot(latitudes_l, longitudes_l, 'g-', linewidth=2, label='L-shaped')
    plt.plot(latitudes_l[0], longitudes_l[0], 'go', markersize=10)  # Start
    plt.plot(latitudes_l[-1], longitudes_l[-1], 'ro', markersize=10)  # End
    
    plt.xlabel('X position (latitude)')
    plt.ylabel('Y position (longitude)')
    plt.title('Generated Mobility Patterns')
    plt.legend()
    plt.grid(True)
    
    # Save visualization
    plt.savefig('mobility_patterns.png')
    logger.info("Visualization saved as mobility_patterns.png")
    
    return True

if __name__ == "__main__":
    if test_nef_adapter():
        logger.info("NEF adapter test successful!")
    else:
        logger.info("NEF adapter test failed.")
