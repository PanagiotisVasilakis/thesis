"""Integration tests for visualization endpoints."""
import sys
import os
import requests
from PIL import Image
import matplotlib.pyplot as plt
import numpy as np

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

def test_coverage_map():
    """Test the coverage map endpoint."""
    print("Testing coverage map visualization...")
    
    # Make request to endpoint
    url = "http://localhost:5050/api/visualization/coverage-map"
    response = requests.get(url)
    
    # Check response
    if response.status_code == 200:
        print("✅ Successfully received coverage map")
        
        # Save the image
        with open("test_coverage_map.png", "wb") as f:
            f.write(response.content)
        
        # Check if it's a valid image
        try:
            img = Image.open("test_coverage_map.png")
            print(f"✅ Valid image received - Size: {img.size}, Format: {img.format}")
            return True
        except Exception as e:
            print(f"❌ Invalid image: {e}")
            return False
    else:
        print(f"❌ Failed to get coverage map: {response.status_code} - {response.text}")
        return False

def test_trajectory_visualization():
    """Test the trajectory visualization endpoint."""
    print("\nTesting trajectory visualization...")
    
    # Generate synthetic trajectory data
    trajectory_data = []
    for i in range(50):
        # Create a zigzag pattern
        x = i * 20
        y = 500 if i % 2 == 0 else 300
        
        # Assign antenna based on position
        if i < 20:
            antenna = "antenna_1"
        elif i < 40:
            antenna = "antenna_2"
        else:
            antenna = "antenna_3"
        
        point = {
            "ue_id": "test_ue",
            "timestamp": f"2025-04-17T{10+i//10}:{i%10}0:00",
            "latitude": x,
            "longitude": y,
            "connected_to": antenna,
            "speed": 2.0
        }
        trajectory_data.append(point)
    
    # Make request to endpoint
    url = "http://localhost:5050/api/visualization/trajectory"
    response = requests.post(url, json=trajectory_data)
    
    # Check response
    if response.status_code == 200:
        print("✅ Successfully received trajectory visualization")
        
        # Save the image
        with open("test_trajectory.png", "wb") as f:
            f.write(response.content)
        
        # Check if it's a valid image
        try:
            img = Image.open("test_trajectory.png")
            print(f"✅ Valid image received - Size: {img.size}, Format: {img.format}")
            return True
        except Exception as e:
            print(f"❌ Invalid image: {e}")
            return False
    else:
        print(f"❌ Failed to get trajectory visualization: {response.status_code} - {response.text}")
        return False

if __name__ == "__main__":
    test_coverage_map()
    test_trajectory_visualization()
