"""Test the mobility patterns API functionality with mocks."""
import sys
import os
import json

# Add the root directory to the path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import our models and adapter
from backend.app.app.mobility_models.models import LinearMobilityModel
from backend.app.app.tools.mobility.adapter import MobilityPatternAdapter

class MockRequest:
    """Mock request object for testing."""
    def __init__(self, model_type, ue_id, duration, time_step, parameters):
        self.model_type = model_type
        self.ue_id = ue_id
        self.duration = duration
        self.time_step = time_step
        self.parameters = parameters

def mock_generate_mobility_pattern(req):
    """Mock the API endpoint functionality."""
    try:
        # Create mobility model
        model = MobilityPatternAdapter.get_mobility_model(
            model_type=req.model_type,
            ue_id=req.ue_id,
            **req.parameters
        )
        
        # Generate path points
        points = MobilityPatternAdapter.generate_path_points(
            model=model,
            duration=req.duration,
            time_step=req.time_step
        )
        
        return points
    except ValueError as e:
        print(f"ValueError: {e}")
        return None
    except Exception as e:
        print(f"Error: {e}")
        return None

def test_mock_api():
    """Test the mock API functionality."""
    # Create a mock request
    req = MockRequest(
        model_type="linear",
        ue_id="test_ue_1",
        duration=60,
        time_step=1.0,
        parameters={
            "start_position": (0, 0, 0),
            "end_position": (500, 250, 0),
            "speed": 10.0
        }
    )
    
    # Call the mock API
    points = mock_generate_mobility_pattern(req)
    
    if points:
        print(f"✅ Successfully generated {len(points)} points via mock API")
        
        # Save the points to a file for inspection
        with open('mock_api_points.json', 'w') as f:
            json.dump(points, f, indent=2)
        
        print("✅ Points saved to mock_api_points.json")
        return True
    else:
        print("❌ Failed to generate points via mock API")
        return False

if __name__ == "__main__":
    success = test_mock_api()
    if success:
        print("Mock API test successful!")
    else:
        print("Mock API test failed.")
