"""Test importing the mobility models in the NEF emulator environment."""

def test_imports():
    """Ensure required mobility modules can be imported."""
    try:
        from backend.app.app.mobility_models.models import (  # noqa: F401
            LinearMobilityModel,
            LShapedMobilityModel,
        )
        from backend.app.app.tools.mobility.adapter import (  # noqa: F401
            MobilityPatternAdapter,
        )
    except ImportError as e:  # pragma: no cover - will fail the test
        import pytest

        pytest.fail(f"Import error: {e}")

    # If imports succeed, ensure the imported symbols exist
    assert LinearMobilityModel
    assert LShapedMobilityModel
    assert MobilityPatternAdapter


if __name__ == "__main__":  # pragma: no cover
    test_imports()
