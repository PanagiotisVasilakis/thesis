"""Test importing the mobility models in the NEF emulator environment."""

def test_imports():
    """Test importing our mobility models."""
    try:
        from backend.app.app.mobility_models.models import LinearMobilityModel, LShapedMobilityModel
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
