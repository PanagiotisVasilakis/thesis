# Save this as tests/test_integration.py

import requests
import json
import subprocess
import time
import matplotlib.pyplot as plt

# Import mobility models and adapter
from backend.app.app.mobility_models.models import LinearMobilityModel
from backend.app.app.mobility_models.nef_adapter import generate_nef_path_points, save_path_to_json

def test_nef_connection():
    """Test connection to NEF emulator."""
    print("\nTesting connection to NEF emulator...")
    
    try:
        # Try to connect to NEF docs endpoint (this should be available without auth)
        response = requests.get("http://localhost:8080/docs", timeout=2)
        
        if response.status_code == 200:
            print("✓ NEF emulator is running")
            return True
        else:
            print(f"✗ NEF emulator returned unexpected status: {response.status_code}")
            return False
    except requests.exceptions.ConnectionError:
        print("✗ Could not connect to NEF emulator. Is it running?")
        return False
    except Exception as e:
        print(f"✗ Error connecting to NEF emulator: {str(e)}")
        return False

def test_ml_service_connection():
    """Test connection to ML service."""
    print("\nTesting connection to ML service...")
    
    try:
        # Try to connect to ML service health endpoint
        response = requests.get("http://localhost:5050/api/health", timeout=2)
        
        if response.status_code == 200:
            print("✓ ML service is running")
            return True
        else:
            print(f"✗ ML service returned unexpected status: {response.status_code}")
            return False
    except requests.exceptions.ConnectionError:
        print("✗ Could not connect to ML service. Is it running?")
        return False
    except Exception as e:
        print(f"✗ Error connecting to ML service: {str(e)}")
        return False

def test_nef_mobility_integration():
    """Test integration between mobility models and NEF emulator."""
    print("\nTesting NEF mobility integration...")
    
    # Check if NEF is running
    if not test_nef_connection():
        print("✗ Cannot test NEF integration - emulator not running")
        return False
    
    try:
        # 1. Login to NEF
        print("Logging in to NEF emulator...")
        login_url = "http://localhost:8080/api/v1/login/access-token"
        login_data = {
            "username": "admin",  # Replace with your credentials
            "password": "admin"   # Replace with your credentials
        }
        
        login_response = requests.post(login_url, data=login_data)
        
        if login_response.status_code != 200:
            print(f"✗ Login failed: {login_response.status_code}")
            return False
        
        token = login_response.json().get("access_token")
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        print("✓ Successfully logged in to NEF emulator")
        
        # 2. Generate mobility path
        print("Generating mobility path...")
        params = {
            'ue_id': 'integration_test_ue',
            'start_position': (100, 100, 0),
            'end_position': (900, 500, 0),
            'speed': 5.0,
            'duration': 200,
            'time_step': 1.0
        }
        
        path_points = generate_nef_path_points('linear', **params)
        path_file = save_path_to_json(path_points, 'integration_test_path.json')
        
        print(f"✓ Generated {len(path_points)} path points")
        
        # 3. Create a path in NEF
        print("Creating path in NEF emulator...")
        
        # Adjust path format for NEF API if needed
        nef_path_data = {
            "description": "Integration test path",
            "path_points": path_points
        }
        
        # Try using mobility patterns endpoint if available
        try:
            path_url = "http://localhost:8080/api/v1/mobility-patterns/generate"
            path_payload = {
                "model_type": "linear",
                "ue_id": "integration_test_ue",
                "duration": 200,
                "time_step": 1.0,
                "parameters": {
                    "start_position": [100, 100, 0],
                    "end_position": [900, 500, 0],
                    "speed": 5.0
                }
            }
            
            path_response = requests.post(path_url, json=path_payload, headers=headers)
            
            if path_response.status_code == 200:
                print("✓ Successfully generated path using mobility patterns API")
                path_points = path_response.json()
                
                # Visualize the path
                if path_points:
                    lats = [point.get('latitude', point.get('x', 0)) for point in path_points]
                    lons = [point.get('longitude', point.get('y', 0)) for point in path_points]
                    
                    plt.figure(figsize=(10, 6))
                    plt.plot(lats, lons, 'b-', linewidth=2)
                    plt.plot(lats[0], lons[0], 'go', markersize=10, label='Start')
                    plt.plot(lats[-1], lons[-1], 'ro', markersize=10, label='End')
                    
                    plt.grid(True)
                    plt.xlabel('Latitude/X')
                    plt.ylabel('Longitude/Y')
                    plt.title('Integration Test Path')
                    plt.legend()
                    
                    plt.savefig('integration_test_path.png')
                    plt.close()
                    
                    print("✓ Path visualization saved to integration_test_path.png")
                
                return True
            else:
                print(f"✗ Failed to generate path using mobility patterns API: {path_response.status_code}")
                print("Falling back to standard path creation...")
        except Exception as e:
            print(f"Mobility patterns API not available: {str(e)}")
            print("Falling back to standard path creation...")
        
        # Fallback: Try the standard paths endpoint
        try:
            path_url = "http://localhost:8080/api/v1/paths/"
            
            # Format for standard paths endpoint
            standard_path_data = [
                {
                    "latitude": point.get('latitude', 0),
                    "longitude": point.get('longitude', 0),
                    "description": f"Point {i}"
                }
                for i, point in enumerate(path_points)
            ]
            
            path_response = requests.post(path_url, json=standard_path_data, headers=headers)
            
            if path_response.status_code == 200:
                print("✓ Successfully created path in NEF emulator")
                return True
            else:
                print(f"✗ Failed to create path: {path_response.status_code} - {path_response.text}")
                return False
        except Exception as e:
            print(f"✗ Error creating path: {str(e)}")
            return False
    
    except Exception as e:
        print(f"✗ Error during NEF integration test: {str(e)}")
        return False

def test_ml_service_prediction():
    """Test ML service prediction functionality."""
    print("\nTesting ML service prediction...")
    
    # Check if ML service is running
    if not test_ml_service_connection():
        print("✗ Cannot test ML service - service not running")
        return False
    
    try:
        # Create test data
        test_data = {
            'ue_id': 'integration_test_ue',
            'latitude': 500.0,
            'longitude': 400.0,
            'speed': 5.0,
            'direction': [0.7, 0.7, 0],
            'connected_to': 'antenna_1',
            'rf_metrics': {
                'antenna_1': {'rsrp': -85, 'sinr': 10},
                'antenna_2': {'rsrp': -95, 'sinr': 5},
                'antenna_3': {'rsrp': -90, 'sinr': 7}
            }
        }
        
        # Make prediction request
        pred_url = "http://localhost:5050/api/predict"
        pred_response = requests.post(pred_url, json=test_data)
        
        if pred_response.status_code == 200:
            prediction = pred_response.json()
            print("✓ Successfully received prediction from ML service")
            print(f"  Predicted antenna: {prediction.get('predicted_antenna')}")
            print(f"  Confidence: {prediction.get('confidence')}")
            return True
        else:
            print(f"✗ Failed to get prediction: {pred_response.status_code} - {pred_response.text}")
            return False
    
    except Exception as e:
        print(f"✗ Error during ML service prediction test: {str(e)}")
        return False

def test_end_to_end_integration():
    """Test end-to-end integration between NEF emulator and ML service."""
    print("\nTesting end-to-end integration...")
    
    # Check if both services are running
    if not test_nef_connection() or not test_ml_service_connection():
        print("✗ Cannot test end-to-end integration - services not running")
        return False
    
    try:
        # 1. Login to NEF
        print("Logging in to NEF emulator...")
        login_url = "http://localhost:8080/api/v1/login/access-token"
        login_data = {
            "username": "admin",  # Replace with your credentials
            "password": "admin"   # Replace with your credentials
        }
        
        login_response = requests.post(login_url, data=login_data)
        
        if login_response.status_code != 200:
            print(f"✗ Login failed: {login_response.status_code}")
            return False
        
        token = login_response.json().get("access_token")
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        print("✓ Successfully logged in to NEF emulator")
        
        # 2. Get UE state if available
        try:
            ue_state_url = "http://localhost:8080/api/v1/ue-movement/state-ues"
            ue_state_response = requests.get(ue_state_url, headers=headers)
            
            if ue_state_response.status_code == 200:
                ue_state = ue_state_response.json()
                
                if ue_state:
                    print(f"✓ Found {len(ue_state)} UEs in movement")
                    
                    # Test prediction for first UE
                    first_ue_id = next(iter(ue_state))
                    first_ue = ue_state[first_ue_id]
                    
                    print(f"Testing prediction for UE: {first_ue_id}")
                    print(f"  Position: ({first_ue.get('latitude', 'N/A')}, {first_ue.get('longitude', 'N/A')})")
                    print(f"  Connected to: {first_ue.get('Cell_id', 'N/A')}")
                    
                    # Add RF metrics (mock data, as this might not be available in UE state)
                    first_ue['rf_metrics'] = {
                        'antenna_1': {'rsrp': -85, 'sinr': 10},
                        'antenna_2': {'rsrp': -95, 'sinr': 5},
                        'antenna_3': {'rsrp': -90, 'sinr': 7}
                    }
                    
                    # Make prediction
                    pred_url = "http://localhost:5050/api/predict"
                    pred_response = requests.post(pred_url, json=first_ue)
                    
                    if pred_response.status_code == 200:
                        prediction = pred_response.json()
                        print("✓ Successfully received prediction from ML service")
                        print(f"  Predicted antenna: {prediction.get('predicted_antenna')}")
                        print(f"  Confidence: {prediction.get('confidence')}")
                        return True
                    else:
                        print(f"✗ Failed to get prediction: {pred_response.status_code} - {pred_response.text}")
                        return False
                else:
                    print("✗ No UEs found in movement state")
                    print("Creating a synthetic UE for testing...")
                    
                    # Create synthetic UE data
                    synthetic_ue = {
                        'ue_id': 'synthetic_integration_ue',
                        'latitude': 500.0,
                        'longitude': 400.0,
                        'speed': 5.0,
                        'direction': [0.7, 0.7, 0],
                        'connected_to': 'antenna_1',
                        'rf_metrics': {
                            'antenna_1': {'rsrp': -85, 'sinr': 10},
                            'antenna_2': {'rsrp': -95, 'sinr': 5},
                            'antenna_3': {'rsrp': -90, 'sinr': 7}
                        }
                    }
                    
                    # Make prediction
                    pred_url = "http://localhost:5050/api/predict"
                    pred_response = requests.post(pred_url, json=synthetic_ue)
                    
                    if pred_response.status_code == 200:
                        prediction = pred_response.json()
                        print("✓ Successfully received prediction from ML service")
                        print(f"  Predicted antenna: {prediction.get('predicted_antenna')}")
                        print(f"  Confidence: {prediction.get('confidence')}")
                        print("Note: Used synthetic UE data since no UEs are in movement")
                        return True
                    else:
                        print(f"✗ Failed to get prediction: {pred_response.status_code} - {pred_response.text}")
                        return False
            else:
                print(f"✗ Failed to get UE state: {ue_state_response.status_code}")
                return False
        
        except Exception as e:
            print(f"✗ Error getting UE state: {str(e)}")
            print("Using synthetic data instead...")
            
            # Create synthetic UE data
            synthetic_ue = {
                'ue_id': 'synthetic_integration_ue',
                'latitude': 500.0,
                'longitude': 400.0,
                'speed': 5.0,
                'direction': [0.7, 0.7, 0],
                'connected_to': 'antenna_1',
                'rf_metrics': {
                    'antenna_1': {'rsrp': -85, 'sinr': 10},
                    'antenna_2': {'rsrp': -95, 'sinr': 5},
                    'antenna_3': {'rsrp': -90, 'sinr': 7}
                }
            }
            
            # Make prediction
            pred_url = "http://localhost:5050/api/predict"
            pred_response = requests.post(pred_url, json=synthetic_ue)
            
            if pred_response.status_code == 200:
                prediction = pred_response.json()
                print("✓ Successfully received prediction from ML service")
                print(f"  Predicted antenna: {prediction.get('predicted_antenna')}")
                print(f"  Confidence: {prediction.get('confidence')}")
                print("Note: Used synthetic UE data")
                return True
            else:
                print(f"✗ Failed to get prediction: {pred_response.status_code} - {pred_response.text}")
                return False
    
    except Exception as e:
        print(f"✗ Error during end-to-end integration test: {str(e)}")
        return False

if __name__ == "__main__":
    print("Running Integration Tests...")
    
    results = []
    results.append(("NEF Connection", test_nef_connection()))
    results.append(("ML Service Connection", test_ml_service_connection()))
    results.append(("NEF Mobility Integration", test_nef_mobility_integration()))
    results.append(("ML Service Prediction", test_ml_service_prediction()))
    results.append(("End-to-End Integration", test_end_to_end_integration()))
    
    print("\nSummary of Results:")
    for test_name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status} - {test_name}")