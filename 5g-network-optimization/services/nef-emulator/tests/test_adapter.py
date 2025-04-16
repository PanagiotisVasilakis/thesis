"""Test the MobilityPatternAdapter functionality."""
import sys
import os
import matplotlib.pyplot as plt

# Add the root directory to the path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app.app.tools.mobility.adapter import MobilityPatternAdapter

def test_adapter():
    """Test the MobilityPatternAdapter functionality."""
    try:
        # Create a linear mobility model using the adapter
        params = {
            "start_position": (0, 0, 0),
            "end_position": (100, 50, 0),
            "speed": 5.0
        }
        
        model = MobilityPatternAdapter.get_mobility_model(
            model_type="linear",
            ue_id="test_ue_1",
            **params
        )
        print(f"✅ Successfully created {model.__class__.__name__}")
        
        # Generate path points
        points = MobilityPatternAdapter.generate_path_points(
            model=model,
            duration=30,
            time_step=1.0
        )
        print(f"✅ Successfully generated {len(points)} points")
        
        # Visualize the generated path
        latitudes = [point['latitude'] for point in points]
        longitudes = [point['longitude'] for point in points]
        
        plt.figure(figsize=(10, 6))
        plt.plot(latitudes, longitudes, 'b-', linewidth=2)
        plt.plot(latitudes[0], longitudes[0], 'go', markersize=10)  # Start point
        plt.plot(latitudes[-1], longitudes[-1], 'ro', markersize=10)  # End point
        
        plt.xlabel('Latitude')
        plt.ylabel('Longitude')
        plt.title('Generated Linear Mobility Pattern via Adapter')
        plt.grid(True)
        
        plt.savefig('adapter_test.png')
        print("✅ Visualization saved as adapter_test.png")
        
        return True
    except Exception as e:
        print(f"❌ Error in adapter test: {e}")
        return False

if __name__ == "__main__":
    success = test_adapter()
    if success:
        print("Adapter test successful!")
    else:
        print("Adapter test failed.")
