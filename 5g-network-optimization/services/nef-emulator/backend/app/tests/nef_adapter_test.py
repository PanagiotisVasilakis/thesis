"""Test the NEF adapter."""
import sys
import os

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Test the adapter
from mobility_models.nef_adapter import generate_nef_path_points, save_path_to_json

def test_nef_adapter():
    # Generate a linear path
    params = {
        'ue_id': 'test_ue_1',
        'start_position': (0, 0, 0),
        'end_position': (1000, 500, 0),
        'speed': 5.0,
        'duration': 250,
        'time_step': 1.0
    }
    
    print("Generating linear path...")
    linear_points = generate_nef_path_points('linear', **params)
    print(f"Generated {len(linear_points)} linear path points")
    
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
    
    print("Generating L-shaped path...")
    l_shaped_points = generate_nef_path_points('l_shaped', **params)
    print(f"Generated {len(l_shaped_points)} L-shaped path points")
    
    # Save to JSON
    l_shaped_json = save_path_to_json(l_shaped_points, 'l_shaped_path.json')
    
    print("NEF adapter test completed successfully!")
    return True

if __name__ == "__main__":
    test_nef_adapter()
