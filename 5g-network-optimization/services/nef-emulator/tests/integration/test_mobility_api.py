"""Integration tests for the mobility patterns API."""
import requests
import json
import matplotlib.pyplot as plt
import numpy as np

def test_generate_linear_pattern():
    """Test generating a linear mobility pattern through the API."""
    url = "http://localhost:8080/api/v1/mobility-patterns/generate"
    
    # Login to get token
    login_url = "http://localhost:8080/api/v1/login/access-token"
    login_data = {
        "username": "admin",  # Use your credentials
        "password": "admin"   # Use your credentials
    }
    login_response = requests.post(login_url, data=login_data)
    if login_response.status_code != 200:
        print(f"Login failed: {login_response.status_code} - {login_response.text}")
        return False
    
    token = login_response.json()["access_token"]
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    # API request
    payload = {
        "model_type": "linear",
        "ue_id": "test_ue_1",
        "duration": 300,
        "time_step": 1.0,
        "parameters": {
            "start_position": [0, 0, 0],
            "end_position": [1000, 500, 0],
            "speed": 5.0
        }
    }
    
    # Make the request
    response = requests.post(url, json=payload, headers=headers)
    
    if response.status_code == 200:
        points = response.json()
        print(f"Generated {len(points)} points")
        
        # Plot the points
        latitudes = [point['latitude'] for point in points]
        longitudes = [point['longitude'] for point in points]
        
        plt.figure(figsize=(10, 6))
        plt.plot(latitudes, longitudes, 'b-', linewidth=2)
        plt.plot(latitudes[0], longitudes[0], 'go', markersize=10)  # Start point
        plt.plot(latitudes[-1], longitudes[-1], 'ro', markersize=10)  # End point
        
        plt.xlabel('Latitude')
        plt.ylabel('Longitude')
        plt.title('Generated Linear Mobility Pattern')
        plt.grid(True)
        
        plt.savefig('linear_api_pattern.png')
        print("Plot saved as linear_api_pattern.png")
        return True
    else:
        print(f"Error: {response.status_code}, {response.text}")
        return False

if __name__ == "__main__":
    success = test_generate_linear_pattern()
    print(f"Test {'succeeded' if success else 'failed'}")
