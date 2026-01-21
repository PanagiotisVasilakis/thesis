"""A3 baseline validation criteria for thesis experiments.

This module implements Fix #7 from the thesis implementation plan:
A3 Baseline Quantitative Acceptance Criteria.

Defines expected performance bounds for different scenarios to validate
that the channel model produces realistic conditions (not too smooth,
not too harsh).

Usage:
    from scripts.validation.a3_baseline_criteria import (
        validate_a3_baseline,
        get_scenario_criteria,
        ValidationResult
    )
    
    # After running A3 baseline experiment
    result = validate_a3_baseline(
        scenario="highway_highspeed",
        handover_count=18,
        pingpong_count=3,
        rlf_count=2,
        late_handover_ratio=0.25
    )
    
    if not result.is_valid:
        print(f"Validation failed: {result.issues}")
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class ScenarioCriteria:
    """Acceptance criteria for a specific scenario.
    
    These bounds define the expected range of A3 baseline performance.
    Values outside these ranges indicate issues with channel model tuning.
    """
    scenario_name: str
    description: str
    duration_s: float
    
    # Handover count bounds
    handover_count_min: int
    handover_count_max: int
    
    # Ping-pong bounds (as fraction of total handovers)
    pingpong_ratio_min: float
    pingpong_ratio_max: float
    
    # RLF bounds
    rlf_count_min: int
    rlf_count_max: int
    
    # Late handover bounds (SINR < -3 dB at HO execution)
    late_ho_ratio_min: float
    late_ho_ratio_max: float
    
    # Optional: expected throughput degradation
    throughput_degradation_max: float = 0.5  # Max 50% loss from optimal
    
    # Diagnostic hints
    hint_too_few_handovers: str = ""
    hint_too_many_handovers: str = ""
    hint_too_few_rlfs: str = ""
    hint_too_many_rlfs: str = ""
    hint_too_few_pingpongs: str = ""
    hint_too_many_pingpongs: str = ""


# Define criteria for each scenario
# =============================================================================
# DERIVATION OF ACCEPTANCE BOUNDS
# =============================================================================
# These bounds are derived from:
#   1. 3GPP TR 36.839 (mobility performance evaluation methodology)
#   2. Literature survey: IEEE/ACM papers on A3 handover evaluation
#   3. Empirical calibration with realistic channel models
#
# Key assumptions:
#   - Standard A3 parameters: Hysteresis=3dB, TTT=160ms
#   - Urban propagation: 3GPP UMi street canyon model
#   - Shadowing: sigma_SF=4-8 dB, decorr_distance=37m
#
# Bounds indicate REALISTIC A3 behavior. Values outside these ranges
# suggest either channel model misconfiguration or non-standard A3 params.
# =============================================================================

SCENARIO_CRITERIA: Dict[str, ScenarioCriteria] = {
    
    # =========================================================================
    # STATIONARY CELL EDGE SCENARIO
    # =========================================================================
    # Physical setup: UE placed at exact cell boundary where serving and
    # neighbor cell have equal average RSRP.
    #
    # Key dynamics:
    # - No mobility → all events from fading fluctuations
    # - Rayleigh fading coherence time ~10s for stationary UE
    # - At cell edge, 3dB hysteresis margin crossed frequently
    #
    # Handover count derivation (8-15 HOs in 60s):
    # - Fading correlation time ~10s for stationary UE
    # - Each correlation interval may trigger 0-2 A3 events
    # - 60s / 10s = ~6 intervals → 6-12 potential events
    # - Add margin for shadowing: 8-15 expected
    #
    # Ping-pong ratio (40-60%):
    # - Cell edge oscillation is the PRIMARY behavior here
    # - Each crossing may immediately reverse → high ping-pong
    # - Literature: 3GPP TR 36.839 shows 40-60% at cell edge
    # =========================================================================
    "stationary_cell_edge": ScenarioCriteria(
        scenario_name="stationary_cell_edge",
        description="Stationary UE at cell edge (60 seconds)",
        duration_s=60.0,
        # Bounds: ~0.13 to 0.25 HO/sec from fading-induced triggers
        # Derivation: 60s duration, fading coherence ~10s, 0-2 events per interval
        handover_count_min=8,   # Conservative: 60s/10s × 1.3 events ≈ 8
        handover_count_max=15,  # Upper: 60s/10s × 2.5 events ≈ 15
        # High ping-pong expected: 40-60% due to cell edge oscillation
        # Source: 3GPP TR 36.839 Section 9.1.3 (cell-edge ping-pong analysis)
        pingpong_ratio_min=0.4,  # 40% - minimum expected at exact cell edge
        pingpong_ratio_max=0.6,  # 60% - indicates unstable boundary condition
        # RLFs: unlikely for stationary UE with proper A3 tuning
        # Rationale: No mobility → no "too late" handovers
        rlf_count_min=0,
        rlf_count_max=1,  # Allow 1 for rare deep fade events
        late_ho_ratio_min=0.0,
        late_ho_ratio_max=0.2,  # Up to 20% may have marginal SINR at execution
        hint_too_few_handovers="Channel fading too weak - increase fading variance",
        hint_too_many_handovers="Channel too harsh OR hysteresis too low - check A3 parameters",
        hint_too_few_pingpongs="Shadowing transitions too smooth - increase sigma_SF",
        hint_too_many_pingpongs="Shadowing too abrupt - increase decorrelation distance",
        hint_too_few_rlfs="Expected 0-1 RLF for stationary UE",
        hint_too_many_rlfs="RLF threshold may be too sensitive for stationary case",
    ),
    
    # =========================================================================
    # HIGHWAY HIGH-SPEED SCENARIO
    # =========================================================================
    # Physical setup: Vehicle at 120 km/h (33.33 m/s) on highway with
    # cells spaced ~500m apart.
    #
    # Key dynamics:
    # - Fast Doppler shift → coherence time ~1ms
    # - Unidirectional motion → fewer ping-pongs than stationary
    # - TTT=160ms covers ~5.3m at 33 m/s → may miss optimal HO point
    #
    # Handover count derivation (15-25 HOs in 300s):
    # - Distance traveled: 33.33 m/s × 300s = 10 km
    # - Cell spacing: ~500m → 10km / 500m = 20 cell crossings (nominal)
    # - Add variance for cell geometry: 15-25 expected
    #
    # Late handover ratio (20-30%):
    # - At 33 m/s, TTT=160ms means HO executes 5.3m past trigger
    # - Cell edge crossings happen mid-TTT → some execute post-optimal
    # - Source: 3GPP TR 36.839 high-speed mobility evaluation
    # =========================================================================
    "highway_highspeed": ScenarioCriteria(
        scenario_name="highway_highspeed",
        description="High-speed vehicle at 120 km/h (300 seconds)",
        duration_s=300.0,
        # Bounds: trajectory of ~10km, 500m cells = 20±5 HOs
        # Derivation: 33.33 m/s × 300s = 10km; 10km / 500m = 20 cells
        handover_count_min=15,  # Allow for larger cells or edge effects
        handover_count_max=25,  # Allow for smaller cells or multi-path
        # Lower ping-pong than stationary due to unidirectional motion
        # Rationale: Once past a cell, unlikely to return
        pingpong_ratio_min=0.1,   # 10% - some may still occur at boundaries
        pingpong_ratio_max=0.25,  # 25% - upper limit for healthy A3
        # RLF bounds: TTT delay at high speed causes some RLFs
        # Derivation: 160ms TTT at 33 m/s = 5.3m late, some cross coverage edge
        rlf_count_min=1,  # At least 1 expected with realistic channel
        rlf_count_max=3,  # More indicates TTT too long for speed
        # Late HOs: 20-30% expected at high speed (per 3GPP TR 36.839)
        # Source: 3GPP TR 36.839 Section 9.2 (high-speed handover performance)
        late_ho_ratio_min=0.2,  # 20% - inherent TTT delay effect
        late_ho_ratio_max=0.3,  # 30% - beyond indicates TTT tuning issue
        hint_too_few_handovers="Check cell spacing and trajectory length",
        hint_too_many_handovers="TTT may be too short for high speed",
        hint_too_few_rlfs="TTT too short (HOs happen too fast) OR channel too smooth",
        hint_too_many_rlfs="TTT too long (HOs delayed) OR channel too harsh",
        hint_too_few_pingpongs="Good - highway scenario should have few ping-pongs",
        hint_too_many_pingpongs="Consider increasing hysteresis for high-speed case",
    ),
    
    # =========================================================================
    # URBAN CANYON SCENARIO
    # =========================================================================
    # Physical setup: Pedestrian/vehicle in urban street canyon with
    # building-induced shadowing zones.
    #
    # Key dynamics:
    # - Sigma_SF = 6-8 dB (higher than rural due to buildings)
    # - Decorrelation distance ~20m (buildings create abrupt transitions)
    # - Moderate speed ~5-15 m/s → coherence time ~100ms
    #
    # Handover count derivation (10-18 HOs in 300s):
    # - At ~10 m/s for 300s = 3km trajectory
    # - With ~300m effective cell coverage in urban = ~10 cell crossings
    # - Shadowing may trigger additional HOs: 10-18 expected
    #
    # Ping-pong ratio (15-35%):
    # - Building shadows create temporary coverage "holes"
    # - UE may switch back after exiting shadow zone
    # - Higher than highway, lower than stationary edge
    # =========================================================================
    "urban_canyon": ScenarioCriteria(
        scenario_name="urban_canyon",
        description="Urban canyon with shadowing zones (300 seconds)",
        duration_s=300.0,
        # Derivation: 3km trajectory / 300m cells ≈ 10 crossings + shadow events
        handover_count_min=10,  # Minimum for realistic urban channel
        handover_count_max=18,  # Upper bound including shadow-triggered HOs
        # Ping-pong from building shadow transitions
        pingpong_ratio_min=0.15,  # 15% - lower bound for urban environment
        pingpong_ratio_max=0.35,  # 35% - shadows cause temporary reversals
        # RLFs: building blockage may cause some
        rlf_count_min=0,   # Possible to avoid RLFs with good A3 tuning
        rlf_count_max=2,   # Shadow fade events may cause RLFs
        # Late HOs: shadows may delay optimal HO point
        late_ho_ratio_min=0.1,   # 10% - some late HOs expected
        late_ho_ratio_max=0.25,  # 25% - urban shadowing effect
        hint_too_few_handovers="Shadowing zones may not be harsh enough",
        hint_too_many_handovers="Shadowing zones too frequent or abrupt",
        hint_too_few_pingpongs="Shadowing zones not harsh enough",
        hint_too_many_pingpongs="Zone transitions too abrupt - increase spatial smoothing",
        hint_too_few_rlfs="Urban scenario should produce some RLFs",
        hint_too_many_rlfs="Shadowing may be too severe - check sigma_SF",
    ),
    
    # =========================================================================
    # SMART CITY DOWNTOWN SCENARIO
    # =========================================================================
    # Physical setup: Dense urban deployment with 15 small cells, 50 UEs
    # with mixed mobility (pedestrians + vehicles).
    #
    # Key dynamics:
    # - High cell density → frequent cell boundaries
    # - Mixed UE speeds (1-20 m/s) → varying Doppler
    # - Heavy traffic → some load-based handovers
    #
    # Handover count derivation (150-400 HOs in 900s for 50 UEs):
    # - Average ~3-8 HOs per UE over 900s
    # - 50 UEs × 3 HOs = 150 (minimum)
    # - 50 UEs × 8 HOs = 400 (dense, active scenario)
    #
    # System-level validation:
    # - This scenario tests aggregate behavior, not individual UE paths
    # - Bounds are for total system, not per-UE
    # =========================================================================
    "smart_city_downtown": ScenarioCriteria(
        scenario_name="smart_city_downtown",
        description="Dense urban deployment (15 cells, 50 UEs, 900 seconds)",
        duration_s=900.0,
        # Derivation: 50 UEs × (3-8) HOs each = 150-400 system total
        handover_count_min=150,  # 50 UEs × 3 HOs minimum
        handover_count_max=400,  # 50 UEs × 8 HOs maximum
        # Ping-pong in dense networks: balanced between mobility benefits and overhead
        pingpong_ratio_min=0.15,  # 15% - good load balancing may keep this low
        pingpong_ratio_max=0.30,  # 30% - upper limit before intervention needed
        # RLFs in dense deployments: coverage gaps at edges
        # Derivation: 50 UEs over 15 cells, some will hit coverage gaps
        rlf_count_min=2,    # Minimum expected: ~4% of UEs hit coverage edge
        rlf_count_max=15,   # Maximum: ~30% of UEs experience 1 RLF
        # Late HOs: mixed speeds create varied late HO distribution
        late_ho_ratio_min=0.1,   # 10% - pedestrians have lower late HO rate
        late_ho_ratio_max=0.3,   # 30% - vehicles in mix increase late HO rate
        hint_too_few_handovers="Dense deployment should produce many handovers",
        hint_too_many_handovers="May indicate excessive cell overlap or low hysteresis",
        hint_too_few_pingpongs="Good - dense network may naturally have fewer ping-pongs",
        hint_too_many_pingpongs="Consider per-cell hysteresis tuning",
        hint_too_few_rlfs="Dense network should have some RLFs at coverage edges",
        hint_too_many_rlfs="May indicate poor cell planning or coverage gaps",
    ),
}


@dataclass
class ValidationResult:
    """Result of A3 baseline validation."""
    scenario_name: str
    is_valid: bool
    issues: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    metrics: Dict[str, object] = field(default_factory=dict)


def get_scenario_criteria(scenario_name: str) -> Optional[ScenarioCriteria]:
    """Get validation criteria for a scenario.
    
    Args:
        scenario_name: Name of the scenario
        
    Returns:
        ScenarioCriteria or None if scenario not found
    """
    # Try exact match first
    if scenario_name in SCENARIO_CRITERIA:
        return SCENARIO_CRITERIA[scenario_name]
    
    # Try partial match
    for key, criteria in SCENARIO_CRITERIA.items():
        if key in scenario_name.lower() or scenario_name.lower() in key:
            return criteria
    
    return None


def validate_a3_baseline(
    scenario: str,
    handover_count: int,
    pingpong_count: int,
    rlf_count: int,
    late_handover_count: int = 0,
    total_duration_s: Optional[float] = None,
) -> ValidationResult:
    """Validate A3 baseline results against acceptance criteria.
    
    Args:
        scenario: Scenario name (must match SCENARIO_CRITERIA)
        handover_count: Total number of handovers
        pingpong_count: Number of ping-pong handovers
        rlf_count: Number of RLF events
        late_handover_count: Number of handovers with SINR < -3 dB
        total_duration_s: Actual simulation duration (for scaling)
        
    Returns:
        ValidationResult with pass/fail status and diagnostic info
    """
    criteria = get_scenario_criteria(scenario)
    
    if criteria is None:
        return ValidationResult(
            scenario_name=scenario,
            is_valid=False,
            issues=[f"Unknown scenario '{scenario}'. Valid scenarios: {list(SCENARIO_CRITERIA.keys())}"],
        )
    
    result = ValidationResult(
        scenario_name=criteria.scenario_name,
        is_valid=True,
        metrics={
            "handover_count": handover_count,
            "pingpong_count": pingpong_count,
            "rlf_count": rlf_count,
            "late_handover_count": late_handover_count,
        }
    )
    
    # Scale criteria if duration differs
    duration_scale = 1.0
    if total_duration_s is not None and total_duration_s != criteria.duration_s:
        duration_scale = total_duration_s / criteria.duration_s
        result.warnings.append(
            f"Duration differs from standard ({total_duration_s}s vs {criteria.duration_s}s), "
            f"scaling bounds by {duration_scale:.2f}"
        )
    
    # Scaled bounds (use round for fairness, ceil for max bounds to be conservative)
    ho_min = max(1, round(criteria.handover_count_min * duration_scale))
    ho_max = round(criteria.handover_count_max * duration_scale)
    rlf_min = round(criteria.rlf_count_min * duration_scale)
    rlf_max = math.ceil(criteria.rlf_count_max * duration_scale)
    
    # Validate handover count
    if handover_count < ho_min:
        result.is_valid = False
        result.issues.append(
            f"Handover count ({handover_count}) below minimum ({ho_min})"
        )
        result.recommendations.append(criteria.hint_too_few_handovers)
    elif handover_count > ho_max:
        result.is_valid = False
        result.issues.append(
            f"Handover count ({handover_count}) above maximum ({ho_max})"
        )
        result.recommendations.append(criteria.hint_too_many_handovers)
    
    # Validate ping-pong ratio
    if handover_count > 0:
        pingpong_ratio = pingpong_count / handover_count
        result.metrics["pingpong_ratio"] = pingpong_ratio
        
        if pingpong_ratio < criteria.pingpong_ratio_min:
            result.warnings.append(
                f"Ping-pong ratio ({pingpong_ratio:.2%}) below expected "
                f"({criteria.pingpong_ratio_min:.0%}-{criteria.pingpong_ratio_max:.0%})"
            )
            result.recommendations.append(criteria.hint_too_few_pingpongs)
        elif pingpong_ratio > criteria.pingpong_ratio_max:
            result.is_valid = False
            result.issues.append(
                f"Ping-pong ratio ({pingpong_ratio:.2%}) above maximum "
                f"({criteria.pingpong_ratio_max:.0%})"
            )
            result.recommendations.append(criteria.hint_too_many_pingpongs)
    
    # Validate RLF count
    if rlf_count < rlf_min:
        result.warnings.append(
            f"RLF count ({rlf_count}) below expected minimum ({rlf_min})"
        )
        result.recommendations.append(criteria.hint_too_few_rlfs)
    elif rlf_count > rlf_max:
        result.is_valid = False
        result.issues.append(
            f"RLF count ({rlf_count}) above maximum ({rlf_max})"
        )
        result.recommendations.append(criteria.hint_too_many_rlfs)
    
    # Validate late handover ratio
    if handover_count > 0:
        late_ho_ratio = late_handover_count / handover_count
        result.metrics["late_handover_ratio"] = late_ho_ratio
        
        if late_ho_ratio > criteria.late_ho_ratio_max:
            result.warnings.append(
                f"Late handover ratio ({late_ho_ratio:.2%}) above expected "
                f"({criteria.late_ho_ratio_max:.0%}) - TTT may be too long"
            )
    
    # Log result
    if result.is_valid:
        logger.info(
            "A3 baseline validation PASSED for %s: %d HOs, %d ping-pongs, %d RLFs",
            scenario, handover_count, pingpong_count, rlf_count
        )
    else:
        logger.warning(
            "A3 baseline validation FAILED for %s: %s",
            scenario, "; ".join(result.issues)
        )
    
    return result


def format_validation_report(result: ValidationResult) -> str:
    """Format validation result as a readable report.
    
    Args:
        result: ValidationResult to format
        
    Returns:
        Formatted string report
    """
    lines = [
        "=" * 60,
        f"A3 BASELINE VALIDATION REPORT: {result.scenario_name}",
        "=" * 60,
        "",
        f"Status: {'✅ PASSED' if result.is_valid else '❌ FAILED'}",
        "",
        "Metrics:",
    ]
    
    for key, value in result.metrics.items():
        if isinstance(value, float):
            lines.append(f"  - {key}: {value:.3f}")
        else:
            lines.append(f"  - {key}: {value}")
    
    if result.issues:
        lines.extend(["", "Issues:"])
        for issue in result.issues:
            lines.append(f"  ❌ {issue}")
    
    if result.warnings:
        lines.extend(["", "Warnings:"])
        for warning in result.warnings:
            lines.append(f"  ⚠️  {warning}")
    
    if result.recommendations:
        lines.extend(["", "Recommendations:"])
        for rec in result.recommendations:
            lines.append(f"  → {rec}")
    
    lines.append("")
    lines.append("=" * 60)
    
    return "\n".join(lines)


def list_available_scenarios() -> List[str]:
    """List all available scenario names."""
    return list(SCENARIO_CRITERIA.keys())


def get_all_criteria() -> Dict[str, Dict]:
    """Get all criteria as a dict for documentation/export."""
    return {
        name: {
            "description": c.description,
            "duration_s": c.duration_s,
            "handover_count": f"{c.handover_count_min}-{c.handover_count_max}",
            "pingpong_ratio": f"{c.pingpong_ratio_min:.0%}-{c.pingpong_ratio_max:.0%}",
            "rlf_count": f"{c.rlf_count_min}-{c.rlf_count_max}",
            "late_ho_ratio": f"{c.late_ho_ratio_min:.0%}-{c.late_ho_ratio_max:.0%}",
        }
        for name, c in SCENARIO_CRITERIA.items()
    }


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Data classes
    'ScenarioCriteria',
    'ValidationResult',
    
    # Scenario criteria dictionary
    'SCENARIO_CRITERIA',
    
    # Validation functions
    'validate_a3_baseline',
    'get_scenario_criteria',
    'format_validation_report',
    
    # Utility functions
    'list_available_scenarios',
    'get_all_criteria',
]
