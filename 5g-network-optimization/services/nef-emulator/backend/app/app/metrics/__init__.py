"""Metrics collection utilities for the RAN simulator.

This package provides:
- RLF (Radio Link Failure) detection with proper timer handling
- Throughput calculation with graceful degradation in RLF zone
- Handover interruption tracking with queue-based overlap handling

Implements Fixes #4, #5, #6, #26, #27 from the thesis implementation plan.
"""

from .rlf_detector import (
    RLFDetector,
    ThroughputCalculator,
    HandoverInterruptionTracker,
    MetricsCollector,
    UERLFState,
    UEInterruptionState,
    HandoverInterruption,
    RLF_SINR_THRESHOLD_DB,
    RLF_DURATION_S,
    MIN_DECODABLE_SINR_DB,
    HANDOVER_INTERRUPTION_S,
)

__all__ = [
    "RLFDetector",
    "ThroughputCalculator",
    "HandoverInterruptionTracker",
    "MetricsCollector",
    "UERLFState",
    "UEInterruptionState",
    "HandoverInterruption",
    "RLF_SINR_THRESHOLD_DB",
    "RLF_DURATION_S",
    "MIN_DECODABLE_SINR_DB",
    "HANDOVER_INTERRUPTION_S",
]
