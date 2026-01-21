"""Validation utilities for thesis experiments.

This package provides:
- A3 baseline validation criteria (Fix #7)
- Distance units runtime validation (Fix #2)
"""

from .a3_baseline_criteria import (
    ScenarioCriteria,
    ValidationResult,
    SCENARIO_CRITERIA,
    validate_a3_baseline,
    get_scenario_criteria,
    format_validation_report,
    list_available_scenarios,
    get_all_criteria,
)

from .distance_units import (
    DistanceUnit,
    DistanceUnitsError,
    DistanceValidationConfig,
    DISTANCE_VALIDATION_CONFIGS,
    validate_distance_meters,
    convert_to_meters,
    assert_meters,
    validate_position_meters,
    validate_velocity_mps,
    create_distance_audit_report,
)

__all__ = [
    # A3 baseline validation
    "ScenarioCriteria",
    "ValidationResult",
    "SCENARIO_CRITERIA",
    "validate_a3_baseline",
    "get_scenario_criteria",
    "format_validation_report",
    "list_available_scenarios",
    "get_all_criteria",
    # Distance units validation
    "DistanceUnit",
    "DistanceUnitsError",
    "DistanceValidationConfig",
    "DISTANCE_VALIDATION_CONFIGS",
    "validate_distance_meters",
    "convert_to_meters",
    "assert_meters",
    "validate_position_meters",
    "validate_velocity_mps",
    "create_distance_audit_report",
]
