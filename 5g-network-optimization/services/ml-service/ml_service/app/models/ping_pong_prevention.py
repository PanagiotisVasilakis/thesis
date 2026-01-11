"""Ping-pong prevention logic for handover decisions.

This module provides a 3-layer ping-pong prevention mechanism that is
critical for the ML handover system's 100% ping-pong elimination rate.

Production Configuration (via environment variables):
    MIN_HANDOVER_INTERVAL_S: Minimum seconds between handovers (default: 2.0)
    MAX_HANDOVERS_PER_MINUTE: Maximum handovers allowed per minute (default: 3)
    PINGPONG_WINDOW_S: Window for detecting immediate ping-pong (default: 10.0)
    PINGPONG_CONFIDENCE_BOOST: Confidence needed to override rate limit (default: 0.9)
"""

import os
import time
import logging
from typing import Dict, Any, Optional, Tuple

from ..config.constants import DEFAULT_IMMEDIATE_RETURN_CONFIDENCE
from ..monitoring import metrics

logger = logging.getLogger(__name__)


class PingPongPrevention:
    """Three-layer ping-pong prevention mechanism.
    
    Layer 1 (Rate Limiting):
        Limits total handovers per time window. If exceeded, requires very
        high confidence to proceed.
    
    Layer 2 (Minimum Interval):
        Enforces minimum time between consecutive handovers. Prevents rapid
        back-and-forth even when confidence is high.
    
    Layer 3 (Immediate Return Detection):
        Detects attempts to return to a recently-visited cell. Requires
        near-certain confidence (95%+) to allow immediate return.
    
    Thesis Results:
        This mechanism achieves 100% ping-pong elimination in experiments,
        compared to 37.5% ping-pong rate with A3-only approach.
    """
    
    def __init__(
        self,
        min_interval_s: Optional[float] = None,
        max_per_minute: Optional[int] = None,
        window_s: Optional[float] = None,
        confidence_boost: Optional[float] = None,
    ):
        """Initialize ping-pong prevention with configurable thresholds.
        
        All parameters default to environment variables or sensible defaults.
        """
        self.min_handover_interval_s = min_interval_s or float(
            os.getenv("MIN_HANDOVER_INTERVAL_S", "2.0")
        )
        self.max_handovers_per_minute = max_per_minute or int(
            os.getenv("MAX_HANDOVERS_PER_MINUTE", "3")
        )
        self.pingpong_window_s = window_s or float(
            os.getenv("PINGPONG_WINDOW_S", "10.0")
        )
        self.pingpong_confidence_boost = confidence_boost or float(
            os.getenv("PINGPONG_CONFIDENCE_BOOST", "0.9")
        )
    
    def should_suppress_handover(
        self,
        ue_id: str,
        current_cell: str,
        predicted_antenna: str,
        confidence: float,
        handover_tracker: Any,
    ) -> Tuple[bool, Optional[str], float]:
        """Determine if a handover should be suppressed.
        
        Args:
            ue_id: UE identifier
            current_cell: Currently connected cell
            predicted_antenna: ML-predicted target cell
            confidence: ML prediction confidence (0.0-1.0)
            handover_tracker: HandoverTracker instance for history access
        
        Returns:
            Tuple of (suppress: bool, reason: Optional[str], new_confidence: float)
            If suppress is True, the handover should be blocked.
        """
        if not current_cell or predicted_antenna == current_cell:
            # No handover suggested, nothing to suppress
            return False, None, confidence
        
        timestamp = time.time()
        handover_count, time_since_last = handover_tracker.update_handover_state(
            ue_id, current_cell, timestamp
        )
        
        # Check 1: Too many handovers in rolling window (rate limiting)
        if handover_count >= self.max_handovers_per_minute:
            handovers_in_window = handover_tracker.get_handovers_in_window(ue_id, 60.0)
            if handovers_in_window >= self.max_handovers_per_minute:
                logger.warning(
                    "Ping-pong detected for %s: %d handovers in last 60s (limit: %d)",
                    ue_id, handovers_in_window, self.max_handovers_per_minute
                )
                # Require much higher confidence to handover
                if confidence < self.pingpong_confidence_boost:
                    metrics.PING_PONG_SUPPRESSIONS.labels(reason="too_many").inc()
                    logger.info(
                        "Ping-pong prevention: %s stays on %s (reason: too_many)",
                        ue_id, current_cell
                    )
                    return True, "too_many", 1.0
        
        # Check 2: Too recent (minimum interval between handovers)
        if time_since_last < self.min_handover_interval_s:
            logger.debug(
                "Suppressing handover for %s: too recent (%.1fs < %.1fs)",
                ue_id, time_since_last, self.min_handover_interval_s
            )
            metrics.PING_PONG_SUPPRESSIONS.labels(reason="too_recent").inc()
            logger.info(
                "Ping-pong prevention: %s stays on %s (reason: too_recent)",
                ue_id, current_cell
            )
            return True, "too_recent", 1.0
        
        # Check 3: Immediate ping-pong (returning to recently-visited cell)
        is_pingpong = handover_tracker.check_immediate_pingpong(
            ue_id, predicted_antenna, self.pingpong_window_s
        )
        if is_pingpong:
            logger.warning(
                "Immediate ping-pong detected for %s: trying to return to %s within %.1fs",
                ue_id, predicted_antenna, self.pingpong_window_s
            )
            # Require very high confidence to return to recent cell
            if confidence < DEFAULT_IMMEDIATE_RETURN_CONFIDENCE:
                metrics.PING_PONG_SUPPRESSIONS.labels(reason="immediate_return").inc()
                logger.info(
                    "Ping-pong prevention: %s stays on %s (reason: immediate_return)",
                    ue_id, current_cell
                )
                return True, "immediate_return", 1.0
        
        # All checks passed, handover is allowed
        return False, None, confidence
    
    def get_handover_stats(
        self,
        ue_id: str,
        current_cell: str,
        handover_tracker: Any,
    ) -> Dict[str, Any]:
        """Get handover statistics for a UE.
        
        Useful for debugging and monitoring.
        """
        timestamp = time.time()
        if not current_cell:
            return {"handover_count_1min": 0, "time_since_last_handover": float("inf")}
        
        handover_count, time_since_last = handover_tracker.update_handover_state(
            ue_id, current_cell, timestamp
        )
        return {
            "handover_count_1min": handover_count,
            "time_since_last_handover": time_since_last,
        }
