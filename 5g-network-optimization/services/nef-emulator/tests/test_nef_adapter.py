# Save this as tests/test_nef_adapter.py

import sys
import os
import json
import matplotlib.pyplot as plt

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import mobility models and adapter
from backend.app.app.mobility_models.models import (
    LinearMobilityModel,
    LShapedMobilityModel
)
from backend.app.app.mobility_models.nef_adapter import generate_nef_path_points, save_path_to_json

def test_linear_adapter():
    """Test NEF adapter with linear mobility model."""
    print("\nTesting NEF adapter with linear mobility model...")
    
    # Parameters for the model
    params = {
        'ue_id': 'test_ue_1',
        'start_position': (0, 0, 0),
        'end_position': (1000, 500, 0),
        'speed': 5.0,
        'duration': 300,
        'time_step': 1.0
    }
    
    # Generate path points
    nef_points = generate_nef_path_points('linear', **params)
    print(f"Generated {len(nef_points)} NEF-compatible points")
    
    # Verify structure of generated points
    if len(nef_points) == 0:
        print("❌ No points generated")
        return False
    
    sample_point = nef_points[0]
    print("Sample point structure:", json.dumps(sample_point, indent=2))
    
    # Check required fields
    required_fields = ['latitude', 'longitude', 'description']
    missing_fields = [field for field in required_fields if field not in sample_point]
    
    if missing_fields:
        print(f"❌ Missing required fields: {missing_fields}")
        return False
    
    # Save to JSON
    json_file = save_path_to_json(nef_points, 'test_linear_path.json')
    print(f"Saved path to {json_file}")
    
    # Visualize the path
    latitudes = [point['latitude'] for point in nef_points]
    longitudes = [point['longitude'] for point in nef_points]
    
    plt.figure(figsize=(10, 6))
    plt.plot(latitudes, longitudes, 'b-', linewidth=2)
    plt.plot(latitudes[0], longitudes[0], 'go', markersize=10, label='Start')
    plt.plot(latitudes[-1], longitudes[-1], 'ro', markersize=10, label='End')
    
    plt.grid(True)
    plt.xlabel('Latitude')
    plt.ylabel('Longitude')
    plt.title('NEF-Compatible Linear Mobility Path')
    plt.legend()
    
    plt.savefig('nef_linear_path.png')
    plt.close()
    
    return True

def test_l_shaped_adapter():
    """Test NEF adapter with L-shaped mobility model."""
    print("\nTesting NEF adapter with L-shaped mobility model...")
    
    # Parameters for the model
    params = {
        'ue_id': 'test_ue_2',
        'start_position': (0, 0, 0),
        'corner_position': (500, 0, 0),
        'end_position': (500, 500, 0),
        'speed': 5.0,
        'duration': 300,
        'time_step': 1.0
    }
    
    # Generate path points
    nef_points = generate_nef_path_points('l_shaped', **params)
    print(f"Generated {len(nef_points)} NEF-compatible points")
    
    # Save to JSON
    json_file = save_path_to_json(nef_points, 'test_l_shaped_path.json')
    print(f"Saved path to {json_file}")
    
    # Visualize the path
    latitudes = [point['latitude'] for point in nef_points]
    longitudes = [point['longitude'] for point in nef_points]
    
    plt.figure(figsize=(10, 6))
    plt.plot(latitudes, longitudes, 'g-', linewidth=2)
    plt.plot(latitudes[0], longitudes[0], 'go', markersize=10, label='Start')
    plt.plot(latitudes[-1], longitudes[-1], 'ro', markersize=10, label='End')
    
    # Mark the corner point (find point closest to corner)
    corner_position = params['corner_position']
    distances = [(lat - corner_position[0])**2 + (lon - corner_position[1])**2 
                for lat, lon in zip(latitudes, longitudes)]
    corner_index = distances.index(min(distances))
    
    plt.plot(latitudes[corner_index], longitudes[corner_index], 'bo', 
             markersize=10, label='Corner')
    
    plt.grid(True)
    plt.xlabel('Latitude')
    plt.ylabel('Longitude')
    plt.title('NEF-Compatible L-Shaped Mobility Path')
    plt.legend()
    
    plt.savefig('nef_l_shaped_path.png')
    plt.close()
    
    return True

def test_combined_visualization():
    """Create a combined visualization of multiple paths."""
    print("\nCreating combined visualization...")
    
    # Load saved paths
    with open('test_linear_path.json', 'r') as f:
        linear_path = json.load(f)
    
    with open('test_l_shaped_path.json', 'r') as f:
        l_shaped_path = json.load(f)
    
    # Plot both paths
    plt.figure(figsize=(12, 8))
    
    # Linear path
    linear_lats = [point['latitude'] for point in linear_path]
    linear_lons = [point['longitude'] for point in linear_path]
    plt.plot(linear_lats, linear_lons, 'b-', linewidth=2, label='Linear Path')
    plt.plot(linear_lats[0], linear_lons[0], 'go', markersize=8)
    plt.plot(linear_lats[-1], linear_lons[-1], 'ro', markersize=8)
    
    # L-shaped path
    l_lats = [point['latitude'] for point in l_shaped_path]
    l_lons = [point['longitude'] for point in l_shaped_path]
    plt.plot(l_lats, l_lons, 'g-', linewidth=2, label='L-Shaped Path')
    plt.plot(l_lats[0], l_lons[0], 'go', markersize=8)
    plt.plot(l_lats[-1], l_lons[-1], 'ro', markersize=8)
    
    plt.grid(True)
    plt.xlabel('Latitude')
    plt.ylabel('Longitude')
    plt.title('Combined NEF-Compatible Mobility Paths')
    plt.legend()
    
    plt.savefig('nef_combined_paths.png')
    plt.close()
    
    print("Combined visualization saved as nef_combined_paths.png")
    return True

if __name__ == "__main__":
    print("Testing NEF Adapter...")
    
    results = []
    results.append(("Linear Model Adapter", test_linear_adapter()))
    results.append(("L-Shaped Model Adapter", test_l_shaped_adapter()))
    results.append(("Combined Visualization", test_combined_visualization()))
    
    print("\nSummary of Results:")
    for test_name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status} - {test_name}")