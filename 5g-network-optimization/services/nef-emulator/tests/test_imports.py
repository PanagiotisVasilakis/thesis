"""Test importing the mobility models in the NEF emulator environment."""

import pytest


def test_imports():
    """Ensure required mobility modules can be imported.
    
    This test verifies that the mobility model infrastructure is properly
    configured and importable within the test environment.
    """
    # Import will raise ImportError if modules are missing
    from backend.app.app.mobility_models.models import (
        LinearMobilityModel,
        LShapedMobilityModel,
    )
    from backend.app.app.tools.mobility.adapter import (
        MobilityPatternAdapter,
    )

    # Verify the imported symbols are class types
    assert isinstance(LinearMobilityModel, type)
    assert isinstance(LShapedMobilityModel, type)
    assert isinstance(MobilityPatternAdapter, type)
