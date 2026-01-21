"""Distance units validation for thesis experiments.

This module implements Fix #2 from the thesis implementation plan:
Distance Units Verification - Runtime Validation

Ensures that all distance-related calculations use consistent units (meters)
throughout the system, preventing unit mismatch errors.

Common sources of unit errors:
- Mixing kilometers and meters
- Mixing miles and meters (if using external data)
- Forgetting conversion when reading from configs in different units

Usage:
    from scripts.validation.distance_units import (
        validate_distance_meters,
        DistanceUnitsError,
        assert_meters,
    )
    
    # Validate individual value
    distance = validate_distance_meters(500.0, "cell_spacing")
    
    # Use decorator for automatic validation
    @assert_meters("distance_to_cell", "decorr_distance")
    def calculate_path_loss(distance_to_cell: float, decorr_distance: float):
        ...

Note:
    The system convention is:
    - All distances in METERS (m)
    - All velocities in METERS PER SECOND (m/s)
    - All frequencies in HERTZ (Hz) internally, GHz in configs
"""

from __future__ import annotations

import functools
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple, TypeVar, Union

logger = logging.getLogger(__name__)

# Type variable for decorators
F = TypeVar('F', bound=Callable[..., Any])


class DistanceUnit(Enum):
    """Supported distance units."""
    METERS = "m"
    KILOMETERS = "km"
    MILES = "mi"
    FEET = "ft"


# Conversion factors TO meters
UNIT_TO_METERS: Dict[DistanceUnit, float] = {
    DistanceUnit.METERS: 1.0,
    DistanceUnit.KILOMETERS: 1000.0,
    DistanceUnit.MILES: 1609.344,
    DistanceUnit.FEET: 0.3048,
}


class DistanceUnitsError(ValueError):
    """Raised when distance value appears to be in wrong units."""
    pass


@dataclass
class DistanceValidationConfig:
    """Configuration for distance validation.
    
    Attributes:
        min_value: Minimum expected value in meters (0 by default)
        max_value: Maximum expected value in meters
        context: Description of what the distance represents
        allow_zero: Whether zero is a valid value
        suspect_if_below: If value < this, might be in wrong units (e.g., km)
        suspect_if_above: If value > this, might be in wrong units (e.g., mm)
    """
    min_value: float = 0.0
    max_value: float = float('inf')
    context: str = "distance"
    allow_zero: bool = True
    suspect_if_below: Optional[float] = None
    suspect_if_above: Optional[float] = None


# Pre-defined validation configs for common distance parameters
DISTANCE_VALIDATION_CONFIGS: Dict[str, DistanceValidationConfig] = {
    # Cell-related distances
    "cell_spacing": DistanceValidationConfig(
        min_value=50.0,      # Min 50m between cells (dense urban)
        max_value=5000.0,    # Max 5km between cells (rural)
        context="cell spacing",
        allow_zero=False,
        suspect_if_below=10.0,   # If < 10, might be in km
        suspect_if_above=10000.0,  # If > 10000, might be in mm or wrong
    ),
    "cell_radius": DistanceValidationConfig(
        min_value=25.0,
        max_value=3000.0,
        context="cell radius",
        allow_zero=False,
        suspect_if_below=5.0,
    ),
    
    # UE distances
    "distance_to_cell": DistanceValidationConfig(
        min_value=0.0,
        max_value=10000.0,   # Max 10km from any cell
        context="distance to cell",
        allow_zero=True,
    ),
    "distance_to_target": DistanceValidationConfig(
        min_value=0.0,
        max_value=10000.0,
        context="distance to target cell",
        allow_zero=True,
    ),
    
    # Channel model distances
    "decorr_distance": DistanceValidationConfig(
        min_value=10.0,
        max_value=200.0,     # Typically 20-50m for urban
        context="decorrelation distance",
        allow_zero=False,
        suspect_if_below=1.0,
    ),
    "coherence_distance": DistanceValidationConfig(
        min_value=0.01,      # Can be very small at high frequency
        max_value=50.0,
        context="coherence distance",
        allow_zero=False,
    ),
    
    # Trajectory distances  
    "trajectory_length": DistanceValidationConfig(
        min_value=100.0,
        max_value=100000.0,  # Max 100km trajectory
        context="trajectory length",
        allow_zero=False,
        suspect_if_below=10.0,  # If < 10, might be in km
    ),
    "position_x": DistanceValidationConfig(
        min_value=-50000.0,  # Allow negative coords
        max_value=50000.0,
        context="X position",
        allow_zero=True,
    ),
    "position_y": DistanceValidationConfig(
        min_value=-50000.0,
        max_value=50000.0,
        context="Y position",
        allow_zero=True,
    ),
    "position_z": DistanceValidationConfig(
        min_value=0.0,       # Height above ground
        max_value=500.0,     # Max 500m (drone/aircraft)
        context="Z position (height)",
        allow_zero=True,
    ),
    
    # Speed-related (m/s)
    "velocity": DistanceValidationConfig(
        min_value=0.0,
        max_value=100.0,     # Max ~360 km/h (high-speed train)
        context="velocity (m/s)",
        allow_zero=True,
        suspect_if_above=150.0,  # If > 150 m/s, might be km/h
    ),
}


def validate_distance_meters(
    value: float,
    param_name: str = "distance",
    config: Optional[DistanceValidationConfig] = None,
    strict: bool = False,
) -> float:
    """Validate that a distance value is in meters and within expected range.
    
    Args:
        value: The distance value to validate
        param_name: Name of the parameter (for error messages)
        config: Validation config, or looked up from DISTANCE_VALIDATION_CONFIGS
        strict: If True, raise on warnings. If False, just log warnings.
        
    Returns:
        The validated value (unchanged if valid)
        
    Raises:
        DistanceUnitsError: If value is invalid or strongly suspected wrong units
        ValueError: If value is NaN or infinite
    """
    # Check for NaN/Inf
    if value != value:  # NaN check
        raise ValueError(f"{param_name}: distance value is NaN")
    if abs(value) == float('inf'):
        raise ValueError(f"{param_name}: distance value is infinite")
    
    # Get config
    if config is None:
        config = DISTANCE_VALIDATION_CONFIGS.get(
            param_name,
            DistanceValidationConfig(context=param_name)
        )
    
    # Check zero
    if value == 0.0 and not config.allow_zero:
        raise DistanceUnitsError(
            f"{config.context}: zero not allowed (got {value})"
        )
    
    # Check minimum
    if value < config.min_value:
        raise DistanceUnitsError(
            f"{config.context}: {value}m below minimum {config.min_value}m. "
            f"Value may be in wrong units?"
        )
    
    # Check maximum
    if value > config.max_value:
        raise DistanceUnitsError(
            f"{config.context}: {value}m above maximum {config.max_value}m. "
            f"Value may be in wrong units?"
        )
    
    # Suspect checks (warnings or errors depending on strict mode)
    if config.suspect_if_below is not None and 0 < value < config.suspect_if_below:
        msg = (
            f"{config.context}: value {value}m seems too small. "
            f"Did you mean {value * 1000}m (value might be in km)?"
        )
        if strict:
            raise DistanceUnitsError(msg)
        logger.warning(msg)
    
    if config.suspect_if_above is not None and value > config.suspect_if_above:
        msg = (
            f"{config.context}: value {value}m seems too large. "
            f"Did you mean {value / 1000}m (value might be in mm)?"
        )
        if strict:
            raise DistanceUnitsError(msg)
        logger.warning(msg)
    
    return value


def convert_to_meters(
    value: float,
    from_unit: Union[DistanceUnit, str],
    param_name: str = "distance",
) -> float:
    """Convert a distance from any supported unit to meters.
    
    Args:
        value: The distance value
        from_unit: Source unit (DistanceUnit enum or string like 'm', 'km')
        param_name: Parameter name for error messages
        
    Returns:
        Distance in meters
    """
    if isinstance(from_unit, str):
        from_unit_lower = from_unit.lower().strip()
        unit_map = {
            'm': DistanceUnit.METERS,
            'meters': DistanceUnit.METERS,
            'km': DistanceUnit.KILOMETERS,
            'kilometers': DistanceUnit.KILOMETERS,
            'mi': DistanceUnit.MILES,
            'miles': DistanceUnit.MILES,
            'ft': DistanceUnit.FEET,
            'feet': DistanceUnit.FEET,
        }
        if from_unit_lower not in unit_map:
            raise ValueError(f"Unknown distance unit: {from_unit}")
        from_unit = unit_map[from_unit_lower]
    
    meters = value * UNIT_TO_METERS[from_unit]
    
    logger.debug(
        "Converted %s: %f %s -> %f m",
        param_name, value, from_unit.value, meters
    )
    
    return meters


def assert_meters(*param_names: str) -> Callable[[F], F]:
    """Decorator to validate distance parameters are in meters.
    
    Validates specified parameters when the decorated function is called.
    
    Args:
        param_names: Names of parameters to validate
        
    Usage:
        @assert_meters("distance_to_cell", "cell_radius")
        def calculate_path_loss(distance_to_cell: float, cell_radius: float):
            ...
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            import inspect
            sig = inspect.signature(func)
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            
            for param_name in param_names:
                if param_name in bound.arguments:
                    value = bound.arguments[param_name]
                    if isinstance(value, (int, float)):
                        validate_distance_meters(value, param_name)
                    elif isinstance(value, (list, tuple)):
                        for i, v in enumerate(value):
                            if isinstance(v, (int, float)):
                                validate_distance_meters(
                                    v, f"{param_name}[{i}]"
                                )
            
            return func(*args, **kwargs)
        return wrapper  # type: ignore
    return decorator


def validate_position_meters(
    position: Tuple[float, float, float],
    context: str = "position",
) -> Tuple[float, float, float]:
    """Validate a 3D position tuple is in meters.
    
    Args:
        position: (x, y, z) tuple in meters
        context: Description for error messages
        
    Returns:
        Validated position tuple
    """
    x, y, z = position
    
    validate_distance_meters(x, "position_x")
    validate_distance_meters(y, "position_y")
    validate_distance_meters(z, "position_z")
    
    return position


def validate_velocity_mps(
    velocity: float,
    context: str = "velocity",
) -> float:
    """Validate velocity is in meters per second (m/s).
    
    Common mistake: passing km/h instead of m/s
    - 120 km/h = 33.33 m/s
    - If someone passes 120 meaning km/h, that would be 120 m/s = 432 km/h!
    
    Args:
        velocity: Speed in m/s
        context: Description for error messages
        
    Returns:
        Validated velocity
        
    Raises:
        DistanceUnitsError: If velocity seems wrong
    """
    if velocity < 0:
        raise DistanceUnitsError(f"{context}: velocity cannot be negative ({velocity})")
    
    # Maximum realistic velocity: ~100 m/s (360 km/h, high-speed train)
    if velocity > 100.0:
        logger.warning(
            "%s: velocity %f m/s (= %f km/h) is very high. "
            "Did you pass km/h instead of m/s?",
            context, velocity, velocity * 3.6
        )
    
    # Common mistake: passing km/h value directly
    # If value looks like common km/h speeds but as m/s, warn
    common_kmh_speeds = [30, 50, 60, 80, 100, 120]  # km/h
    for kmh in common_kmh_speeds:
        if abs(velocity - kmh) < 1.0:  # Within 1 m/s of common km/h value
            logger.warning(
                "%s: velocity %f m/s matches common km/h value. "
                "If you meant %d km/h, use %f m/s instead.",
                context, velocity, kmh, kmh / 3.6
            )
            break
    
    return velocity


def create_distance_audit_report(
    distances: Dict[str, float],
    strict: bool = False,
) -> Dict[str, Any]:
    """Audit a set of distance values and create a validation report.
    
    Args:
        distances: Dict mapping parameter names to distance values
        strict: Whether to fail on warnings
        
    Returns:
        Dict with 'valid', 'errors', 'warnings' keys
    """
    report = {
        "valid": True,
        "errors": [],
        "warnings": [],
        "validated": {},
    }
    
    for name, value in distances.items():
        try:
            validated = validate_distance_meters(value, name, strict=strict)
            report["validated"][name] = validated
            
        except (DistanceUnitsError, ValueError) as e:
            report["valid"] = False
            report["errors"].append(f"{name}: {e}")
    
    return report


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    'DistanceUnit',
    'DistanceUnitsError',
    'DistanceValidationConfig',
    'DISTANCE_VALIDATION_CONFIGS',
    'UNIT_TO_METERS',
    'validate_distance_meters',
    'convert_to_meters',
    'assert_meters',
    'validate_position_meters',
    'validate_velocity_mps',
    'create_distance_audit_report',
]
