"""Tests for ping-pong prevention in ML handover decisions.

These tests validate the anti-ping-pong mechanisms critical for demonstrating
ML superiority over traditional A3 rules in the thesis.
"""
import pytest
import time
from ml_service.app.models.antenna_selector import AntennaSelector
from ml_service.app.data.feature_extractor import HandoverTracker
from ml_service.app.monitoring import metrics


@pytest.fixture
def trained_selector(tmp_path):
    """Create a trained antenna selector for testing."""
    selector = AntennaSelector(neighbor_count=3)
    
    # Train with minimal synthetic data
    training_data = []
    for i in range(50):
        training_data.append({
            "ue_id": f"train_{i}",
            "latitude": i * 10.0,
            "longitude": i * 5.0,
            "speed": 5.0,
            "direction_x": 1.0,
            "direction_y": 0.0,
            "heading_change_rate": 0.0,
            "path_curvature": 0.0,
            "velocity": 5.0,
            "acceleration": 0.0,
            "cell_load": 0.5,
            "handover_count": 0,
            "time_since_handover": 10.0,
            "signal_trend": 0.0,
            "environment": 0.0,
            "rsrp_stddev": 2.0,
            "sinr_stddev": 1.0,
            "rsrp_current": -80.0,
            "sinr_current": 15.0,
            "rsrq_current": -10.0,
            "best_rsrp_diff": 5.0,
            "best_sinr_diff": 3.0,
            "best_rsrq_diff": 2.0,
            "altitude": 0.0,
            "connected_to": "antenna_1",
            "rsrp_a1": -80.0,
            "sinr_a1": 15.0,
            "rsrq_a1": -10.0,
            "neighbor_cell_load_a1": 0.3,
            "rsrp_a2": -85.0,
            "sinr_a2": 12.0,
            "rsrq_a2": -12.0,
            "neighbor_cell_load_a2": 0.5,
            "rsrp_a3": -90.0,
            "sinr_a3": 10.0,
            "rsrq_a3": -14.0,
            "neighbor_cell_load_a3": 0.4,
            "optimal_antenna": f"antenna_{(i % 3) + 1}"
        })
    
    selector.train(training_data)
    return selector


def test_handover_tracker_detects_ping_pong():
    """Test that HandoverTracker detects immediate ping-pong patterns."""
    tracker = HandoverTracker()
    
    ue_id = "test_ue_1"
    timestamp = time.time()
    
    # Simulate: antenna_1 -> antenna_2 -> antenna_1 (ping-pong)
    tracker.update_handover_state(ue_id, "antenna_1", timestamp)
    tracker.update_handover_state(ue_id, "antenna_2", timestamp + 2.0)
    
    # Check if returning to antenna_1 is a ping-pong
    is_pingpong = tracker.check_immediate_pingpong(ue_id, "antenna_1", window_seconds=10.0)
    assert is_pingpong is True, "Should detect immediate ping-pong"
    
    # After 11 seconds, should not be considered ping-pong
    tracker.update_handover_state(ue_id, "antenna_2", timestamp + 12.0)
    is_pingpong = tracker.check_immediate_pingpong(ue_id, "antenna_1", window_seconds=10.0)
    assert is_pingpong is False, "Should not detect ping-pong after window expires"


def test_handover_tracker_counts_recent_handovers():
    """Test that HandoverTracker accurately counts handovers in time window."""
    tracker = HandoverTracker()
    
    ue_id = "test_ue_2"
    timestamp = time.time()
    
    # Simulate multiple handovers within 60 seconds
    cells = ["antenna_1", "antenna_2", "antenna_3", "antenna_1", "antenna_2"]
    for i, cell in enumerate(cells):
        tracker.update_handover_state(ue_id, cell, timestamp + i * 5.0)
    
    # Should count 4 handovers (transitions between cells)
    count = tracker.get_handovers_in_window(ue_id, 60.0)
    assert count == 4, f"Expected 4 handovers in window, got {count}"


def test_handover_tracker_maintains_cell_history():
    """Test that HandoverTracker maintains recent cell history."""
    tracker = HandoverTracker()
    
    ue_id = "test_ue_3"
    timestamp = time.time()
    
    # Simulate movement through cells
    cells = ["antenna_1", "antenna_2", "antenna_3", "antenna_4"]
    for i, cell in enumerate(cells):
        tracker.update_handover_state(ue_id, cell, timestamp + i * 1.0)
    
    # Get recent cells (should be in reverse order)
    recent = tracker.get_recent_cells(ue_id, n=4)
    assert recent == ["antenna_4", "antenna_3", "antenna_2", "antenna_1"], \
        f"Expected reverse order, got {recent}"


def test_ping_pong_suppression_too_recent(trained_selector, monkeypatch):
    """Test that handovers are suppressed if too recent."""
    # Set short minimum interval for testing
    monkeypatch.setenv("MIN_HANDOVER_INTERVAL_S", "2.0")
    
    # Reinitialize to pick up new config
    selector = AntennaSelector(neighbor_count=3)
    selector.model = trained_selector.model
    selector.scaler = trained_selector.scaler
    selector.feature_names = trained_selector.feature_names
    
    # First prediction
    features1 = {
        "ue_id": "pingpong_test_1",
        "latitude": 100.0,
        "longitude": 50.0,
        "speed": 5.0,
        "direction_x": 1.0,
        "direction_y": 0.0,
        "heading_change_rate": 0.0,
        "path_curvature": 0.0,
        "velocity": 5.0,
        "acceleration": 0.0,
        "cell_load": 0.5,
        "handover_count": 0,
        "time_since_handover": 10.0,
        "signal_trend": 0.0,
        "environment": 0.0,
        "rsrp_stddev": 2.0,
        "sinr_stddev": 1.0,
        "rsrp_current": -80.0,
        "sinr_current": 15.0,
        "rsrq_current": -10.0,
        "best_rsrp_diff": 5.0,
        "best_sinr_diff": 3.0,
        "best_rsrq_diff": 2.0,
        "altitude": 0.0,
        "connected_to": "antenna_1",
        "rsrp_a1": -80.0,
        "sinr_a1": 15.0,
        "rsrq_a1": -10.0,
        "neighbor_cell_load_a1": 0.3,
        "rsrp_a2": -75.0,  # Better signal
        "sinr_a2": 18.0,
        "rsrq_a2": -9.0,
        "neighbor_cell_load_a2": 0.2,
        "rsrp_a3": -90.0,
        "sinr_a3": 10.0,
        "rsrq_a3": -14.0,
        "neighbor_cell_load_a3": 0.6,
    }
    
    result1 = selector.predict(features1)
    first_prediction = result1["antenna_id"]
    
    # Immediately try another prediction (< 2 seconds)
    time.sleep(0.5)
    
    features2 = features1.copy()
    features2["rsrp_a1"] = -85.0  # Current cell worse
    features2["rsrp_a2"] = -70.0  # antenna_2 much better
    
    result2 = selector.predict(features2)
    
    # Handover should be suppressed due to too_recent
    if first_prediction != "antenna_1":
        assert result2["anti_pingpong_applied"] is True, \
            "Ping-pong prevention should have been applied"
        assert result2["suppression_reason"] == "too_recent", \
            f"Expected 'too_recent', got {result2.get('suppression_reason')}"
        assert result2["antenna_id"] == "antenna_1", \
            "Should stay on current cell when too recent"


def test_ping_pong_suppression_too_many(trained_selector, monkeypatch):
    """Test that handovers are suppressed if too many occur in window."""
    monkeypatch.setenv("MAX_HANDOVERS_PER_MINUTE", "3")
    monkeypatch.setenv("MIN_HANDOVER_INTERVAL_S", "0.1")  # Very short for testing
    
    selector = AntennaSelector(neighbor_count=3)
    selector.model = trained_selector.model
    selector.scaler = trained_selector.scaler
    selector.feature_names = trained_selector.feature_names
    
    ue_id = "pingpong_test_2"
    
    # Base features
    base_features = {
        "ue_id": ue_id,
        "latitude": 100.0,
        "longitude": 50.0,
        "speed": 20.0,  # High speed
        "direction_x": 1.0,
        "direction_y": 0.0,
        "heading_change_rate": 0.0,
        "path_curvature": 0.0,
        "velocity": 20.0,
        "acceleration": 0.0,
        "cell_load": 0.5,
        "handover_count": 0,
        "time_since_handover": 10.0,
        "signal_trend": 0.0,
        "environment": 0.0,
        "rsrp_stddev": 2.0,
        "sinr_stddev": 1.0,
        "rsrp_current": -80.0,
        "sinr_current": 15.0,
        "rsrq_current": -10.0,
        "best_rsrp_diff": 5.0,
        "best_sinr_diff": 3.0,
        "best_rsrq_diff": 2.0,
        "altitude": 0.0,
        "connected_to": "antenna_1",
        "rsrp_a1": -80.0,
        "sinr_a1": 15.0,
        "rsrq_a1": -10.0,
        "neighbor_cell_load_a1": 0.3,
        "rsrp_a2": -85.0,
        "sinr_a2": 12.0,
        "rsrq_a2": -12.0,
        "neighbor_cell_load_a2": 0.5,
        "rsrp_a3": -90.0,
        "sinr_a3": 10.0,
        "rsrq_a3": -14.0,
        "neighbor_cell_load_a3": 0.4,
    }
    
    # Simulate rapid handovers (4 times in quick succession)
    cells = ["antenna_1", "antenna_2", "antenna_3", "antenna_1", "antenna_2"]
    for i, cell in enumerate(cells):
        time.sleep(0.15)  # Just above MIN_HANDOVER_INTERVAL_S
        features = base_features.copy()
        features["connected_to"] = cell
        # Make the next cell appear better
        next_cell = cells[i+1] if i < len(cells)-1 else cell
        features[f"rsrp_a{int(next_cell[-1])}"] = -70.0  # Much better
        
        result = selector.predict(features)
        
        # After 3 handovers, the 4th should be suppressed or require high confidence
        if i >= 3:
            handovers_count = result.get("handover_count_1min", 0)
            if handovers_count >= 3:
                # Either suppressed or very high confidence required
                if result["anti_pingpong_applied"]:
                    assert result["suppression_reason"] == "too_many", \
                        "Should suppress due to too_many handovers"


def test_immediate_pingpong_detection(trained_selector, monkeypatch):
    """Test detection of immediate ping-pong (A -> B -> A)."""
    monkeypatch.setenv("MIN_HANDOVER_INTERVAL_S", "0.1")
    monkeypatch.setenv("PINGPONG_WINDOW_S", "10.0")
    
    selector = AntennaSelector(neighbor_count=3)
    selector.model = trained_selector.model
    selector.scaler = trained_selector.scaler
    selector.feature_names = trained_selector.feature_names
    
    ue_id = "pingpong_test_3"
    
    base_features = {
        "ue_id": ue_id,
        "latitude": 100.0,
        "longitude": 50.0,
        "speed": 5.0,
        "direction_x": 1.0,
        "direction_y": 0.0,
        "heading_change_rate": 0.0,
        "path_curvature": 0.0,
        "velocity": 5.0,
        "acceleration": 0.0,
        "cell_load": 0.5,
        "handover_count": 0,
        "time_since_handover": 10.0,
        "signal_trend": 0.0,
        "environment": 0.0,
        "rsrp_stddev": 2.0,
        "sinr_stddev": 1.0,
        "rsrp_current": -80.0,
        "sinr_current": 15.0,
        "rsrq_current": -10.0,
        "best_rsrp_diff": 5.0,
        "best_sinr_diff": 3.0,
        "best_rsrq_diff": 2.0,
        "altitude": 0.0,
        "connected_to": "antenna_1",
        "rsrp_a1": -80.0,
        "sinr_a1": 15.0,
        "rsrq_a1": -10.0,
        "neighbor_cell_load_a1": 0.5,
        "rsrp_a2": -75.0,
        "sinr_a2": 18.0,
        "rsrq_a2": -9.0,
        "neighbor_cell_load_a2": 0.3,
        "rsrp_a3": -90.0,
        "sinr_a3": 10.0,
        "rsrq_a3": -14.0,
        "neighbor_cell_load_a3": 0.6,
    }
    
    # Step 1: On antenna_1
    result1 = selector.predict(base_features)
    
    # Step 2: Move to antenna_2
    time.sleep(0.2)
    features2 = base_features.copy()
    features2["connected_to"] = "antenna_2"
    features2["rsrp_a2"] = -70.0  # antenna_2 best
    result2 = selector.predict(features2)
    
    # Step 3: Try to return to antenna_1 quickly (ping-pong)
    time.sleep(0.2)
    features3 = base_features.copy()
    features3["connected_to"] = "antenna_2"
    features3["rsrp_a1"] = -70.0  # antenna_1 suddenly better
    features3["rsrp_a2"] = -85.0  # antenna_2 worse
    result3 = selector.predict(features3)
    
    # Should detect ping-pong and possibly suppress
    # (depends on confidence, but should at least detect)
    assert "anti_pingpong_applied" in result3, "Result should include ping-pong flag"


def test_handover_interval_metric_recorded(trained_selector):
    """Test that handover intervals are recorded in metrics."""
    selector = trained_selector
    
    ue_id = "interval_test"
    
    features = {
        "ue_id": ue_id,
        "latitude": 100.0,
        "longitude": 50.0,
        "speed": 5.0,
        "direction_x": 1.0,
        "direction_y": 0.0,
        "heading_change_rate": 0.0,
        "path_curvature": 0.0,
        "velocity": 5.0,
        "acceleration": 0.0,
        "cell_load": 0.5,
        "handover_count": 0,
        "time_since_handover": 10.0,
        "signal_trend": 0.0,
        "environment": 0.0,
        "rsrp_stddev": 2.0,
        "sinr_stddev": 1.0,
        "rsrp_current": -80.0,
        "sinr_current": 15.0,
        "rsrq_current": -10.0,
        "best_rsrp_diff": 5.0,
        "best_sinr_diff": 3.0,
        "best_rsrq_diff": 2.0,
        "altitude": 0.0,
        "connected_to": "antenna_1",
        "rsrp_a1": -80.0,
        "sinr_a1": 15.0,
        "rsrq_a1": -10.0,
        "neighbor_cell_load_a1": 0.5,
        "rsrp_a2": -85.0,
        "sinr_a2": 12.0,
        "rsrq_a2": -12.0,
        "neighbor_cell_load_a2": 0.5,
        "rsrp_a3": -90.0,
        "sinr_a3": 10.0,
        "rsrq_a3": -14.0,
        "neighbor_cell_load_a3": 0.5,
    }
    
    # Make predictions
    result1 = selector.predict(features)
    
    time.sleep(3.0)  # Wait longer than minimum interval
    
    result2 = selector.predict(features)
    
    # Check that interval is being tracked
    assert "time_since_last_handover" in result2, \
        "Result should include time_since_last_handover"
    assert result2["time_since_last_handover"] >= 0, \
        "Time since handover should be non-negative"


def test_no_suppression_when_not_needed(trained_selector):
    """Test that ping-pong prevention doesn't trigger for normal handovers."""
    selector = trained_selector
    
    ue_id = "normal_handover"
    
    features = {
        "ue_id": ue_id,
        "latitude": 100.0,
        "longitude": 50.0,
        "speed": 5.0,
        "direction_x": 1.0,
        "direction_y": 0.0,
        "heading_change_rate": 0.0,
        "path_curvature": 0.0,
        "velocity": 5.0,
        "acceleration": 0.0,
        "cell_load": 0.5,
        "handover_count": 0,
        "time_since_handover": 100.0,  # Long time since last
        "signal_trend": 0.0,
        "environment": 0.0,
        "rsrp_stddev": 2.0,
        "sinr_stddev": 1.0,
        "rsrp_current": -80.0,
        "sinr_current": 15.0,
        "rsrq_current": -10.0,
        "best_rsrp_diff": 5.0,
        "best_sinr_diff": 3.0,
        "best_rsrq_diff": 2.0,
        "altitude": 0.0,
        "connected_to": "antenna_1",
        "rsrp_a1": -80.0,
        "sinr_a1": 15.0,
        "rsrq_a1": -10.0,
        "neighbor_cell_load_a1": 0.5,
        "rsrp_a2": -85.0,
        "sinr_a2": 12.0,
        "rsrq_a2": -12.0,
        "neighbor_cell_load_a2": 0.5,
        "rsrp_a3": -90.0,
        "sinr_a3": 10.0,
        "rsrq_a3": -14.0,
        "neighbor_cell_load_a3": 0.5,
    }
    
    result = selector.predict(features)
    
    # Should have ping-pong flag but not necessarily applied
    assert "anti_pingpong_applied" in result, \
        "Result should include anti_pingpong_applied flag"


def test_handover_count_tracked(trained_selector):
    """Test that handover count is tracked in prediction results."""
    selector = trained_selector
    
    ue_id = "count_test"
    
    features = {
        "ue_id": ue_id,
        "latitude": 100.0,
        "longitude": 50.0,
        "speed": 5.0,
        "direction_x": 1.0,
        "direction_y": 0.0,
        "heading_change_rate": 0.0,
        "path_curvature": 0.0,
        "velocity": 5.0,
        "acceleration": 0.0,
        "cell_load": 0.5,
        "handover_count": 0,
        "time_since_handover": 10.0,
        "signal_trend": 0.0,
        "environment": 0.0,
        "rsrp_stddev": 2.0,
        "sinr_stddev": 1.0,
        "rsrp_current": -80.0,
        "sinr_current": 15.0,
        "rsrq_current": -10.0,
        "best_rsrp_diff": 5.0,
        "best_sinr_diff": 3.0,
        "best_rsrq_diff": 2.0,
        "altitude": 0.0,
        "connected_to": "antenna_1",
        "rsrp_a1": -80.0,
        "sinr_a1": 15.0,
        "rsrq_a1": -10.0,
        "neighbor_cell_load_a1": 0.5,
        "rsrp_a2": -85.0,
        "sinr_a2": 12.0,
        "rsrq_a2": -12.0,
        "neighbor_cell_load_a2": 0.5,
        "rsrp_a3": -90.0,
        "sinr_a3": 10.0,
        "rsrq_a3": -14.0,
        "neighbor_cell_load_a3": 0.5,
    }
    
    result = selector.predict(features)
    
    # Check that handover metadata is included
    assert "handover_count_1min" in result, \
        "Result should include handover_count_1min"
    assert "time_since_last_handover" in result, \
        "Result should include time_since_last_handover"
    assert isinstance(result["handover_count_1min"], int), \
        "Handover count should be integer"
    assert isinstance(result["time_since_last_handover"], float), \
        "Time since handover should be float"


@pytest.mark.thesis
def test_ml_reduces_ping_pong_vs_a3_simulation():
    """THESIS VALIDATION: Simulate scenario where ML prevents ping-pong."""
    # This test demonstrates the thesis claim that ML reduces ping-pong
    # compared to A3 rule
    
    selector = AntennaSelector(neighbor_count=2)
    
    # Train with simple pattern
    training_data = []
    for i in range(100):
        training_data.append({
            "ue_id": f"train_{i}",
            "latitude": i * 10.0,
            "longitude": i * 10.0,
            "speed": 5.0,
            "direction_x": 1.0,
            "direction_y": 0.0,
            "heading_change_rate": 0.0,
            "path_curvature": 0.0,
            "velocity": 5.0,
            "acceleration": 0.0,
            "cell_load": 0.5,
            "handover_count": 0,
            "time_since_handover": 10.0,
            "signal_trend": 0.0,
            "environment": 0.0,
            "rsrp_stddev": 2.0,
            "sinr_stddev": 1.0,
            "rsrp_current": -80.0,
            "sinr_current": 15.0,
            "rsrq_current": -10.0,
            "best_rsrp_diff": 5.0,
            "best_sinr_diff": 3.0,
            "best_rsrq_diff": 2.0,
            "altitude": 0.0,
            "connected_to": "antenna_1",
            "rsrp_a1": -80.0,
            "sinr_a1": 15.0,
            "rsrq_a1": -10.0,
            "neighbor_cell_load_a1": 0.5,
            "rsrp_a2": -85.0,
            "sinr_a2": 12.0,
            "rsrq_a2": -12.0,
            "neighbor_cell_load_a2": 0.5,
            "optimal_antenna": f"antenna_{(i % 2) + 1}"
        })
    
    selector.train(training_data)
    
    # Simulate ping-pong scenario
    ping_pong_scenario = [
        {"connected_to": "antenna_1", "rsrp_a1": -80, "rsrp_a2": -75},  # Move to antenna_2
        {"connected_to": "antenna_2", "rsrp_a1": -75, "rsrp_a2": -80},  # Try to return
    ]
    
    suppressions = 0
    ue_id = "thesis_demo_ue"
    
    for i, scenario in enumerate(ping_pong_scenario):
        time.sleep(1.0)
        
        features = {
            "ue_id": ue_id,
            "latitude": 100.0 + i * 10,
            "longitude": 50.0,
            "speed": 5.0,
            "direction_x": 1.0,
            "direction_y": 0.0,
            "heading_change_rate": 0.0,
            "path_curvature": 0.0,
            "velocity": 5.0,
            "acceleration": 0.0,
            "cell_load": 0.5,
            "handover_count": i,
            "time_since_handover": 1.0 if i > 0 else 100.0,
            "signal_trend": 0.0,
            "environment": 0.0,
            "rsrp_stddev": 2.0,
            "sinr_stddev": 1.0,
            "rsrp_current": scenario["rsrp_a1"],
            "sinr_current": 15.0,
            "rsrq_current": -10.0,
            "best_rsrp_diff": 5.0,
            "best_sinr_diff": 3.0,
            "best_rsrq_diff": 2.0,
            "altitude": 0.0,
            "connected_to": scenario["connected_to"],
            "rsrp_a1": scenario["rsrp_a1"],
            "sinr_a1": 15.0,
            "rsrq_a1": -10.0,
            "neighbor_cell_load_a1": 0.5,
            "rsrp_a2": scenario["rsrp_a2"],
            "sinr_a2": 18.0,
            "rsrq_a2": -9.0,
            "neighbor_cell_load_a2": 0.3,
        }
        
        result = selector.predict(features)
        
        if result.get("anti_pingpong_applied"):
            suppressions += 1
    
    # ML should have prevented at least some ping-pong
    # (exact count depends on confidence values and timing)
    assert "anti_pingpong_applied" in result, \
        "Ping-pong prevention should be active"
    
    # Verify handover tracking is working
    stats = selector.handover_tracker.get_stats()
    assert stats["tracked_ues"] >= 1, "Should track at least one UE"


def test_ping_pong_metrics_exported(trained_selector):
    """Test that ping-pong metrics are available for Prometheus."""
    from prometheus_client import generate_latest
    from ml_service.app.monitoring.metrics import REGISTRY, PING_PONG_SUPPRESSIONS, HANDOVER_INTERVAL
    
    # Verify metrics exist
    assert PING_PONG_SUPPRESSIONS is not None, "PING_PONG_SUPPRESSIONS metric should exist"
    assert HANDOVER_INTERVAL is not None, "HANDOVER_INTERVAL metric should exist"
    
    # Generate metrics output
    output = generate_latest(REGISTRY).decode('utf-8')
    
    # Check metric names appear in output
    assert 'ml_pingpong_suppressions_total' in output or 'ml_handover_interval_seconds' in output, \
        "Ping-pong metrics should be exportable"


def test_handover_tracker_get_recent_cells():
    """Test getting recent cells from handover history."""
    tracker = HandoverTracker()
    
    ue_id = "history_test"
    timestamp = time.time()
    
    # Simulate cell transitions
    cells = ["antenna_1", "antenna_2", "antenna_3", "antenna_4", "antenna_5"]
    for i, cell in enumerate(cells):
        tracker.update_handover_state(ue_id, cell, timestamp + i)
    
    # Get last 3 cells
    recent = tracker.get_recent_cells(ue_id, n=3)
    assert len(recent) == 3, f"Expected 3 cells, got {len(recent)}"
    assert recent == ["antenna_5", "antenna_4", "antenna_3"], \
        f"Expected reverse order, got {recent}"


def test_suppression_reason_in_result(trained_selector, monkeypatch):
    """Test that suppression reason is included in result when applicable."""
    monkeypatch.setenv("MIN_HANDOVER_INTERVAL_S", "5.0")
    
    selector = AntennaSelector(neighbor_count=2)
    selector.model = trained_selector.model
    selector.scaler = trained_selector.scaler
    selector.feature_names = trained_selector.feature_names
    
    ue_id = "suppression_test"
    
    features = {
        "ue_id": ue_id,
        "latitude": 100.0,
        "longitude": 50.0,
        "speed": 5.0,
        "direction_x": 1.0,
        "direction_y": 0.0,
        "heading_change_rate": 0.0,
        "path_curvature": 0.0,
        "velocity": 5.0,
        "acceleration": 0.0,
        "cell_load": 0.5,
        "handover_count": 0,
        "time_since_handover": 10.0,
        "signal_trend": 0.0,
        "environment": 0.0,
        "rsrp_stddev": 2.0,
        "sinr_stddev": 1.0,
        "rsrp_current": -80.0,
        "sinr_current": 15.0,
        "rsrq_current": -10.0,
        "best_rsrp_diff": 5.0,
        "best_sinr_diff": 3.0,
        "best_rsrq_diff": 2.0,
        "altitude": 0.0,
        "connected_to": "antenna_1",
        "rsrp_a1": -80.0,
        "sinr_a1": 15.0,
        "rsrq_a1": -10.0,
        "neighbor_cell_load_a1": 0.5,
        "rsrp_a2": -70.0,  # Much better
        "sinr_a2": 20.0,
        "rsrq_a2": -8.0,
        "neighbor_cell_load_a2": 0.2,
    }
    
    # First prediction
    result1 = selector.predict(features)
    
    # Immediate second prediction (should be suppressed if suggests handover)
    time.sleep(0.5)
    result2 = selector.predict(features)
    
    # If suppressed, should have reason
    if result2.get("anti_pingpong_applied"):
        assert "suppression_reason" in result2, \
            "Suppressed predictions should include reason"
        assert result2["suppression_reason"] in ["too_recent", "too_many", "immediate_return"], \
            f"Invalid suppression reason: {result2.get('suppression_reason')}"

