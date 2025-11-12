"""Integration tests for NEF handover coverage loss detection."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_state_manager():
    """Create a mock network state manager with cell configuration."""
    mgr = MagicMock()
    
    # Mock cell with 500m radius
    mock_cell = MagicMock()
    mock_cell.latitude = 0.0
    mock_cell.longitude = 0.0
    mock_cell.radius = 500.0
    
    mgr.get_cell.return_value = mock_cell
    mgr.resolve_antenna_id.side_effect = lambda x: x
    mgr.antenna_list = ["antenna_1", "antenna_2", "antenna_3", "antenna_4"]
    mgr.apply_handover_decision.return_value = {"from": "antenna_1", "to": "antenna_2"}
    
    return mgr


@pytest.fixture
def handover_engine(mock_state_manager):
    """Create handover engine with mocked state manager."""
    import sys
    from pathlib import Path
    
    # Add NEF backend to path
    nef_backend = Path(__file__).parents[2] / "5g-network-optimization" / "services" / "nef-emulator" / "backend"
    if str(nef_backend) not in sys.path:
        sys.path.insert(0, str(nef_backend))
    
    from app.handover.engine import HandoverEngine
    
    engine = HandoverEngine(
        state_mgr=mock_state_manager,
        use_ml=False,  # Use A3 for simpler testing
        a3_hysteresis_db=2.0,
        a3_ttt_s=0.0,
    )
    
    return engine


def test_coverage_loss_forces_handover_even_if_target_equals_current(handover_engine, mock_state_manager):
    """UE outside current cell coverage should force handover even if predicted cell is current."""
    ue_id = "test_ue_coverage_loss"
    
    # UE is at (10.0, 10.0) - far from current cell at (0.0, 0.0)
    # Distance ~15.7km >> 750m (1.5x radius)
    features = {
        "ue_id": ue_id,
        "latitude": 10.0,
        "longitude": 10.0,
        "connected_to": "antenna_1",
    }
    
    # Mock A3 rule to return current antenna (normally would skip)
    with patch.object(handover_engine, "_select_rule", return_value="antenna_1"):
        # Mock nearest cell finder to return antenna_2
        with patch.object(handover_engine, "_find_nearest_cell", return_value="antenna_2"):
            result = handover_engine.decide_and_apply(ue_id, features)
    
    # Should have forced handover despite target == current
    assert result is not None
    assert result["to"] == "antenna_2"
    mock_state_manager.apply_handover_decision.assert_called_once_with(ue_id, "antenna_2")


def test_already_connected_skips_when_in_coverage(handover_engine, mock_state_manager):
    """UE within cell coverage should skip handover if already connected."""
    ue_id = "test_ue_in_coverage"
    
    # UE is at (0.001, 0.001) - close to current cell at (0.0, 0.0)
    # Distance ~150m << 750m (1.5x radius)
    features = {
        "ue_id": ue_id,
        "latitude": 0.001,
        "longitude": 0.001,
        "connected_to": "antenna_1",
    }
    
    # Mock A3 rule to return current antenna
    with patch.object(handover_engine, "_select_rule", return_value="antenna_1"):
        result = handover_engine.decide_and_apply(ue_id, features)
    
    # Should skip handover (already connected and in coverage)
    assert result is None
    mock_state_manager.apply_handover_decision.assert_not_called()


def test_find_nearest_cell_returns_closest(handover_engine):
    """Helper method should return nearest cell based on haversine distance."""
    # Position near antenna_4 at (1000.0, 866.0) from synthetic grid
    ue_position = (999.0, 865.0)
    
    nearest = handover_engine._find_nearest_cell(ue_position)
    
    assert nearest == "antenna_4"


def test_find_nearest_cell_handles_invalid_position(handover_engine):
    """Helper should handle None position gracefully."""
    assert handover_engine._find_nearest_cell((None, 10.0)) is None
    assert handover_engine._find_nearest_cell((10.0, None)) is None
    assert handover_engine._find_nearest_cell((None, None)) is None


def test_coverage_loss_logged_in_decision_trace(handover_engine, mock_state_manager, caplog):
    """Coverage loss should be logged in structured decision log."""
    import logging
    
    caplog.set_level(logging.INFO)
    
    ue_id = "test_ue_logging"
    features = {
        "ue_id": ue_id,
        "latitude": 10.0,
        "longitude": 10.0,
        "connected_to": "antenna_1",
    }
    
    with patch.object(handover_engine, "_select_rule", return_value="antenna_1"):
        with patch.object(handover_engine, "_find_nearest_cell", return_value="antenna_2"):
            handover_engine.decide_and_apply(ue_id, features)
    
    # Check structured log contains coverage loss
    decision_logs = [rec.message for rec in caplog.records if "HANDOVER_DECISION" in rec.message]
    assert len(decision_logs) > 0
    
    import json
    decision_data = json.loads(decision_logs[0].split("HANDOVER_DECISION: ", 1)[1])
    
    assert decision_data.get("coverage_loss") is True
    assert "distance_to_current_cell" in decision_data
    assert "max_coverage_distance" in decision_data
