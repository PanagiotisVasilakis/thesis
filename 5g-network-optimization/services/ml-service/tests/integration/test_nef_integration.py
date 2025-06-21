"""Integration tests for NEF emulator communication."""
import requests
import json
import time
import importlib.util
from pathlib import Path

NEF_COLLECTOR_PATH = Path(__file__).resolve().parents[2] / "app" / "data" / "nef_collector.py"
spec = importlib.util.spec_from_file_location("nef_collector", NEF_COLLECTOR_PATH)
nef_collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nef_collector)
NEFDataCollector = nef_collector.NEFDataCollector

def test_nef_connection():
    """Test connecting to the NEF emulator."""
    print("Testing NEF emulator connection...")
    
    # Try to connect to NEF API
    try:
        # First, check if NEF emulator is running
        response = requests.get("http://localhost:8080/docs", timeout=2)
        if response.status_code != 200:
            print("❌ NEF emulator does not appear to be running or is not accessible")
            print("Please start the NEF emulator and try again")
            return False
        
        # Initialize collector with credentials (adjust as needed)
        collector = NEFDataCollector(
            nef_url="http://localhost:8080",
            username="admin",
            password="admin"  # Change to match your NEF emulator credentials
        )
        
        # Attempt to login
        success = collector.login()
        if success:
            print("✅ Successfully connected to NEF emulator")
        else:
            print("❌ Failed to authenticate with NEF emulator")
            print("Check your credentials and NEF emulator status")
            return False
        
        return True
    except requests.exceptions.ConnectionError:
        print("❌ Connection error - NEF emulator is not running or not accessible")
        print("Please start the NEF emulator and try again")
        return False
    except Exception as e:
        print(f"❌ Unexpected error during NEF connection test: {str(e)}")
        return False

def test_data_collection(duration=10):
    """Test collecting data from the NEF emulator."""
    print(f"\nTesting data collection for {duration} seconds...")
    
    # Initialize collector
    collector = NEFDataCollector(
        nef_url="http://localhost:8080",
        username="admin",
        password="admin"  # Change to match your NEF emulator credentials
    )
    
    # Login
    if not collector.login():
        print("❌ Login failed - skipping data collection test")
        return False
    
    # Get current UE movement state
    ue_state = collector.get_ue_movement_state()
    
    if not ue_state:
        print("❌ No UEs in movement state found")
        print("Please start UE movement in the NEF emulator before running this test")
        return False
    
    print(f"✅ Found {len(ue_state)} UEs in movement")
    
    # Collect data for specified duration
    print(f"Collecting data for {duration} seconds...")
    data = collector.collect_training_data(duration=duration, interval=1)
    
    if not data:
        print("❌ No data collected")
        return False
    
    print(f"✅ Successfully collected {len(data)} data points")
    
    # Save sample to test file
    with open("test_collected_data.json", "w") as f:
        json.dump(data[:10], f, indent=2)  # Save first 10 samples
    
    print("✅ Sample data saved to test_collected_data.json")
    return True

def test_ml_prediction_with_nef_data():
    """Test making predictions with data from NEF emulator."""
    print("\nTesting ML prediction with NEF data...")
    
    # Check if we have collected data
    try:
        with open("test_collected_data.json", "r") as f:
            data = json.load(f)
        
        if not data:
            print("❌ No data available for prediction test")
            return False
        
        # Make prediction request to ML service
        url = "http://localhost:5050/api/predict"
        response = requests.post(url, json=data[0])
        
        if response.status_code == 200:
            result = response.json()
            print("✅ Prediction successful")
            print(f"UE: {result.get('ue_id')}")
            print(f"Predicted antenna: {result.get('predicted_antenna')}")
            print(f"Confidence: {result.get('confidence')}")
            return True
        else:
            print(f"❌ Prediction failed: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"❌ Error during prediction test: {str(e)}")
        return False

def test_end_to_end_flow():
    """Test the complete end-to-end flow."""
    print("\nTesting end-to-end flow (NEF → ML Service → Prediction)...")
    
    # Step 1: Connect to NEF
    if not test_nef_connection():
        print("❌ NEF connection failed - stopping end-to-end test")
        return False
    
    # Step 2: Collect data (just a few samples)
    collector = NEFDataCollector(
        nef_url="http://localhost:8080",
        username="admin", 
        password="admin"
    )
    collector.login()
    data = collector.collect_training_data(duration=5, interval=1)
    
    if not data:
        print("❌ No data collected - stopping end-to-end test")
        return False
    
    print(f"✅ Collected {len(data)} samples for end-to-end test")
    
    # Step 3: Train model with collected data
    try:
        train_url = "http://localhost:5050/api/train"
        train_response = requests.post(train_url, json=data)
        
        if train_response.status_code == 200:
            print("✅ Training successful")
            metrics = train_response.json().get('metrics', {})
            print(f"Trained with {metrics.get('samples', 0)} samples")
            print(f"Found {metrics.get('classes', 0)} antenna classes")
        else:
            print(f"❌ Training failed: {train_response.status_code} - {train_response.text}")
            # Continue anyway since the model may have a default prediction
    except Exception as e:
        print(f"❌ Error during training: {str(e)}")
        # Continue anyway
    
    # Step 4: Make prediction for a UE
    try:
        # Get current UE state
        ue_state = collector.get_ue_movement_state()
        
        if not ue_state:
            print("❌ No UEs available for prediction")
            return False
        
        # Take the first UE
        ue_id, ue_data = next(iter(ue_state.items()))
        
        # Make prediction
        predict_url = "http://localhost:5050/api/predict"
        predict_response = requests.post(predict_url, json=ue_data)
        
        if predict_response.status_code == 200:
            result = predict_response.json()
            print("✅ End-to-end prediction successful")
            print(f"UE: {result.get('ue_id', ue_id)}")
            print(f"Position: ({ue_data.get('latitude', 'N/A')}, {ue_data.get('longitude', 'N/A')})")
            print(f"Connected to: {ue_data.get('Cell_id', 'N/A')}")
            print(f"Predicted antenna: {result.get('predicted_antenna', 'N/A')}")
            print(f"Confidence: {result.get('confidence', 'N/A')}")
            return True
        else:
            print(f"❌ End-to-end prediction failed: {predict_response.status_code} - {predict_response.text}")
            return False
    except Exception as e:
        print(f"❌ Error during end-to-end test: {str(e)}")
        return False

if __name__ == "__main__":
    print("Running NEF Integration Tests")
    print("============================")
    print("Note: These tests require the NEF emulator to be running")
    print("      and at least one UE with active movement\n")
    
    # Run tests only if NEF is available
    if test_nef_connection():
        test_data_collection()
        test_ml_prediction_with_nef_data()
        test_end_to_end_flow()
    else:
        print("\nSkipping remaining tests due to NEF connection failure")
