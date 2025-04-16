"""Test importing the mobility models in the NEF emulator environment."""
import sys
import os

# Add the root directory to the path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_imports():
    """Test importing our mobility models."""
    try:
        from mobility_models.models import LinearMobilityModel, LShapedMobilityModel
        print("✅ Successfully imported mobility models")
        
        # Test importing adapter
        from backend.app.app.tools.mobility.adapter import MobilityPatternAdapter
        print("✅ Successfully imported MobilityPatternAdapter")
        
        return True
    except ImportError as e:
        print(f"❌ Import error: {e}")
        return False

if __name__ == "__main__":
    success = test_imports()
    if success:
        print("All imports successful!")
    else:
        print("Import test failed.")
