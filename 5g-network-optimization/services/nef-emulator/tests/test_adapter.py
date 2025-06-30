"""Test the MobilityPatternAdapter functionality."""

from backend.app.app.tools.mobility.adapter import MobilityPatternAdapter
import pytest
import logging

logger = logging.getLogger(__name__)

def test_adapter():
    """Test the MobilityPatternAdapter functionality."""
    # Create a linear mobility model using the adapter
    params = {
        "start_position": (0, 0, 0),
        "end_position": (100, 50, 0),
        "speed": 5.0,
    }

    model = MobilityPatternAdapter.get_mobility_model(
        model_type="linear",
        ue_id="test_ue_1",
        **params,
    )

    points = MobilityPatternAdapter.generate_path_points(
        model=model,
        duration=30,
        time_step=1.0,
    )

    assert len(points) > 0

    latitudes = [p["latitude"] for p in points]
    longitudes = [p["longitude"] for p in points]
    assert (round(latitudes[0]), round(longitudes[0])) == (0, 0)
    assert latitudes[-1] == pytest.approx(100, abs=2)
    assert longitudes[-1] == pytest.approx(50, abs=2)

if __name__ == "__main__":
    success = test_adapter()
    if success:
        logger.info("Adapter test successful!")
    else:
        logger.info("Adapter test failed.")
