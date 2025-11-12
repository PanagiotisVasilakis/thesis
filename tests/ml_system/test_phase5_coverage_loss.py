"""Unit tests for Phase 5: Coverage loss detection logic."""
from __future__ import annotations

import pytest


def test_haversine_distance_calculation():
    """Verify haversine distance formula is accurate."""
    from ml_service.app.config.cells import haversine_distance
    
    # Test known distance: ~111km per degree at equator
    lat1, lon1 = 0.0, 0.0
    lat2, lon2 = 0.0, 1.0
    
    distance = haversine_distance(lat1, lon1, lat2, lon2)
    
    # Should be approximately 111km (111,320 meters)
    assert 110_000 < distance < 112_000


def test_haversine_zero_distance():
    """Same coordinates should return zero distance."""
    from ml_service.app.config.cells import haversine_distance
    
    distance = haversine_distance(37.999, 23.819, 37.999, 23.819)
    
    assert distance == pytest.approx(0.0, abs=0.1)


def test_cell_config_has_required_fields():
    """All cell configurations should have required fields."""
    from ml_service.app.config.cells import CELL_CONFIGS
    
    assert len(CELL_CONFIGS) >= 4
    
    for antenna_id, config in CELL_CONFIGS.items():
        assert "id" in config
        assert "latitude" in config
        assert "longitude" in config
        assert "radius_meters" in config
        assert "max_distance_multiplier" in config
        
        assert config["id"] == antenna_id
        assert isinstance(config["latitude"], (int, float))
        assert isinstance(config["longitude"], (int, float))
        assert config["radius_meters"] > 0
        assert config["max_distance_multiplier"] >= 1.0


def test_get_cell_config_returns_valid_config():
    """get_cell_config should return configuration for valid antenna."""
    from ml_service.app.config.cells import get_cell_config
    
    config = get_cell_config("antenna_1")
    
    assert config is not None
    assert config["id"] == "antenna_1"
    assert "latitude" in config


def test_get_cell_config_returns_none_for_invalid():
    """get_cell_config should return None for unknown antenna."""
    from ml_service.app.config.cells import get_cell_config
    
    config = get_cell_config("antenna_999")
    
    assert config is None


def test_coverage_loss_scenario():
    """Simulate coverage loss: UE far from current cell."""
    from ml_service.app.config.cells import CELL_CONFIGS, haversine_distance
    
    # Antenna 1 at (0.0, 0.0) with 600m radius
    cell_config = CELL_CONFIGS["antenna_1"]
    max_distance = cell_config["radius_meters"] * cell_config["max_distance_multiplier"]
    
    # UE at (10.0, 10.0) - very far from antenna_1
    ue_lat, ue_lon = 10.0, 10.0
    
    distance = haversine_distance(
        ue_lat, ue_lon,
        cell_config["latitude"], cell_config["longitude"]
    )
    
    # Should be far outside coverage
    assert distance > max_distance
    
    # Distance should be approximately 1570 km
    assert distance > 1_000_000  # > 1000 km


def test_normal_coverage_scenario():
    """Simulate normal coverage: UE within cell radius."""
    from ml_service.app.config.cells import CELL_CONFIGS, haversine_distance
    
    # Antenna 1 at (0.0, 0.0) with 600m radius
    cell_config = CELL_CONFIGS["antenna_1"]
    max_distance = cell_config["radius_meters"] * cell_config["max_distance_multiplier"]
    
    # UE very close to antenna_1 (0.001 degrees ~ 111m)
    ue_lat, ue_lon = 0.001, 0.001
    
    distance = haversine_distance(
        ue_lat, ue_lon,
        cell_config["latitude"], cell_config["longitude"]
    )
    
    # Should be well within coverage
    assert distance < max_distance
    assert distance < cell_config["radius_meters"]


def test_find_nearest_cell_logic():
    """Verify logic for finding nearest cell."""
    from ml_service.app.config.cells import CELL_CONFIGS, haversine_distance
    
    # UE near antenna_4 at (1000.0, 866.0)
    ue_lat, ue_lon = 999.0, 865.0
    
    nearest_cell = None
    min_distance = float('inf')
    
    for antenna_id, config in CELL_CONFIGS.items():
        distance = haversine_distance(
            ue_lat, ue_lon,
            config["latitude"], config["longitude"]
        )
        
        if distance < min_distance:
            min_distance = distance
            nearest_cell = antenna_id
    
    # Should identify antenna_4 as nearest
    assert nearest_cell == "antenna_4"
    assert min_distance < 200_000  # < 200km (should be ~157m)
