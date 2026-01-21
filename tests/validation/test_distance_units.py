"""Tests for distance units validation module.

Tests Fix #2: Distance Units Verification - Runtime Validation
"""
import pytest
from scripts.validation.distance_units import (
    validate_distance_meters,
    validate_velocity_mps,
    validate_position_meters,
    convert_to_meters,
    assert_meters,
    create_distance_audit_report,
    DistanceUnitsError,
    DistanceUnit,
    DistanceValidationConfig,
)


class TestValidateDistanceMeters:
    """Tests for validate_distance_meters function."""
    
    def test_valid_cell_spacing(self):
        """Test valid cell spacing value."""
        result = validate_distance_meters(500.0, "cell_spacing")
        assert result == 500.0
    
    def test_valid_distance_to_cell(self):
        """Test valid distance to cell value."""
        result = validate_distance_meters(0.0, "distance_to_cell")
        assert result == 0.0
    
    def test_invalid_zero_cell_spacing(self):
        """Test that zero cell spacing raises error."""
        with pytest.raises(DistanceUnitsError):
            validate_distance_meters(0.0, "cell_spacing")
    
    def test_below_minimum(self):
        """Test value below minimum raises error."""
        with pytest.raises(DistanceUnitsError):
            validate_distance_meters(10.0, "cell_spacing")  # Min is 50m
    
    def test_above_maximum(self):
        """Test value above maximum raises error."""
        with pytest.raises(DistanceUnitsError):
            validate_distance_meters(10000.0, "cell_spacing")  # Max is 5000m
    
    def test_nan_raises_error(self):
        """Test NaN value raises error."""
        import math
        with pytest.raises(ValueError):
            validate_distance_meters(math.nan, "distance")
    
    def test_inf_raises_error(self):
        """Test infinite value raises error."""
        import math
        with pytest.raises(ValueError):
            validate_distance_meters(math.inf, "distance")
    
    def test_unknown_param_uses_default_config(self):
        """Test unknown parameter name uses default permissive config."""
        # Should not raise with reasonable value
        result = validate_distance_meters(100.0, "unknown_param")
        assert result == 100.0
    
    def test_suspect_warning_logged(self, caplog):
        """Test that suspect values log warnings."""
        import logging
        caplog.set_level(logging.WARNING)
        
        # Value of 5 for cell_spacing is below minimum and will raise
        # Test with a value that is IN range but suspect (e.g., 55 which is valid but small)
        validate_distance_meters(55.0, "cell_spacing", strict=False)
        
        # For this test, use a custom config that has suspect range
        config = DistanceValidationConfig(
            min_value=1.0,
            max_value=1000.0,
            context="test_distance",
            suspect_if_below=10.0,  # Values < 10 are suspect
        )
        validate_distance_meters(5.0, "test", config=config, strict=False)
        
        # Should have logged a warning about possible wrong units
        assert any("seems too small" in record.message for record in caplog.records)
    
    def test_strict_mode_raises_on_suspect(self):
        """Test strict mode raises error on suspect values."""
        with pytest.raises(DistanceUnitsError):
            validate_distance_meters(5.0, "cell_spacing", strict=True)


class TestValidateVelocityMps:
    """Tests for validate_velocity_mps function."""
    
    def test_valid_velocity(self):
        """Test valid velocity value."""
        result = validate_velocity_mps(33.33)  # 120 km/h
        assert result == 33.33
    
    def test_zero_velocity(self):
        """Test zero velocity is valid."""
        result = validate_velocity_mps(0.0)
        assert result == 0.0
    
    def test_negative_velocity_raises(self):
        """Test negative velocity raises error."""
        with pytest.raises(DistanceUnitsError):
            validate_velocity_mps(-10.0)
    
    def test_high_velocity_warning(self, caplog):
        """Test very high velocity logs warning."""
        import logging
        caplog.set_level(logging.WARNING)
        
        # 120 m/s = 432 km/h, suspiciously high
        validate_velocity_mps(120.0)
        
        assert any("km/h" in record.message for record in caplog.records)


class TestConvertToMeters:
    """Tests for convert_to_meters function."""
    
    def test_kilometers_to_meters(self):
        """Test km to m conversion."""
        result = convert_to_meters(1.5, "km")
        assert abs(result - 1500.0) < 0.001
    
    def test_miles_to_meters(self):
        """Test miles to m conversion."""
        result = convert_to_meters(1.0, "mi")
        assert abs(result - 1609.344) < 0.001
    
    def test_feet_to_meters(self):
        """Test feet to m conversion."""
        result = convert_to_meters(100.0, "ft")
        assert abs(result - 30.48) < 0.001
    
    def test_meters_unchanged(self):
        """Test m to m is unchanged."""
        result = convert_to_meters(500.0, "m")
        assert result == 500.0
    
    def test_enum_unit(self):
        """Test using DistanceUnit enum."""
        result = convert_to_meters(2.0, DistanceUnit.KILOMETERS)
        assert abs(result - 2000.0) < 0.001
    
    def test_unknown_unit_raises(self):
        """Test unknown unit raises error."""
        with pytest.raises(ValueError):
            convert_to_meters(100.0, "parsecs")


class TestValidatePositionMeters:
    """Tests for validate_position_meters function."""
    
    def test_valid_position(self):
        """Test valid 3D position."""
        result = validate_position_meters((100.0, 200.0, 1.5))
        assert result == (100.0, 200.0, 1.5)
    
    def test_origin_position(self):
        """Test origin position is valid."""
        result = validate_position_meters((0.0, 0.0, 0.0))
        assert result == (0.0, 0.0, 0.0)
    
    def test_negative_coords_valid(self):
        """Test negative x/y coordinates are valid."""
        result = validate_position_meters((-500.0, -500.0, 10.0))
        assert result == (-500.0, -500.0, 10.0)


class TestAssertMetersDecorator:
    """Tests for @assert_meters decorator."""
    
    def test_decorator_validates_param(self):
        """Test decorator validates specified parameter."""
        @assert_meters("distance")
        def my_func(distance: float, name: str):
            return distance * 2
        
        # Should work with valid value
        result = my_func(100.0, "test")
        assert result == 200.0
    
    def test_decorator_allows_unvalidated_params(self):
        """Test decorator doesn't affect unspecified params."""
        @assert_meters("distance")
        def my_func(distance: float, other: float):
            return distance + other
        
        # other is not validated, so any value works
        # Use a value that wouldn't pass cell_spacing validation
        result = my_func(100.0, other=10.0)
        assert result == 110.0


class TestCreateDistanceAuditReport:
    """Tests for create_distance_audit_report function."""
    
    def test_valid_distances_report(self):
        """Test report with all valid distances."""
        distances = {
            "cell_spacing": 500.0,
            "cell_radius": 250.0,
            "distance_to_cell": 100.0,
        }
        report = create_distance_audit_report(distances)
        
        assert report["valid"] is True
        assert len(report["errors"]) == 0
    
    def test_invalid_distances_report(self):
        """Test report with invalid distances."""
        distances = {
            "cell_spacing": 10.0,  # Below minimum
        }
        report = create_distance_audit_report(distances)
        
        assert report["valid"] is False
        assert len(report["errors"]) > 0
    
    def test_mixed_distances_report(self):
        """Test report with mix of valid and invalid."""
        distances = {
            "cell_spacing": 500.0,  # Valid
            "cell_radius": 5.0,     # Invalid - too small
        }
        report = create_distance_audit_report(distances)
        
        assert report["valid"] is False


class TestDistanceValidationConfig:
    """Tests for DistanceValidationConfig dataclass."""
    
    def test_custom_config(self):
        """Test using custom validation config."""
        config = DistanceValidationConfig(
            min_value=10.0,
            max_value=100.0,
            context="custom distance",
            allow_zero=False,
        )
        
        # Should pass
        result = validate_distance_meters(50.0, config=config)
        assert result == 50.0
        
        # Should fail
        with pytest.raises(DistanceUnitsError):
            validate_distance_meters(5.0, config=config)
