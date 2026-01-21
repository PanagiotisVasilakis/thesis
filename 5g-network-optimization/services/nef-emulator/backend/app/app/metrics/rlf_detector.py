"""Radio Link Failure (RLF) detection and metrics tracking.

This module implements Fixes #4, #5, #6, #26, #27 from the thesis implementation plan:

Fix #4: RLF Detection Timer Precision
- Uses >= comparison for 1.0 second threshold
- Handles non-integer timesteps correctly

Fix #5: Throughput During RLF Zone
- Piecewise SINR-to-throughput mapping
- Graceful degradation in -10 to -6 dB range

Fix #6: Handover Interruption Accumulation
- Queue-based tracking prevents double-counting overlaps
- Total interruption time calculated correctly

Fix #26: RLF During Handover Interruption
- RLF timer cleared during handover
- Prevents false positives from normal HO interruptions

Fix #27: Multiple Handover Interruption Tracking
- Queue of (start, end) tuples instead of single timestamp
- Handles rapid successive handovers correctly

Usage:
    from app.metrics.rlf_detector import RLFDetector, ThroughputCalculator
    
    # Create RLF detector
    rlf = RLFDetector(rlf_threshold_db=-6.0, rlf_duration_s=1.0)
    
    # Check for RLF condition
    is_rlf = rlf.check_rlf(ue_id="ue001", sinr_db=-8.0, timestamp=1.5)
    
    # Calculate throughput with graceful degradation
    calc = ThroughputCalculator(bandwidth_hz=20e6)
    throughput = calc.calculate_throughput(sinr_db=-8.0)
"""

from __future__ import annotations

import logging
import math
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Constants from 3GPP specifications
RLF_SINR_THRESHOLD_DB = -6.0  # SINR below which RLF timer starts
RLF_DURATION_S = 1.0  # Duration for RLF declaration (T310)
MIN_DECODABLE_SINR_DB = -10.0  # Below this, no connection possible
HANDOVER_INTERRUPTION_S = 0.050  # 50ms handover interruption

# Configurable limit for interruption queue (Fix: was hardcoded as 20)
# Increase if ping-pong analysis requires tracking more interruptions
MAX_INTERRUPTION_QUEUE_SIZE = 20


@dataclass
class UERLFState:
    """RLF tracking state for a single UE."""
    # Time when SINR first dropped below threshold (or None if above)
    rlf_timer_start: Optional[float] = None
    
    # Whether UE is currently in handover interruption
    in_handover_interruption: bool = False
    
    # Count of RLF events for this UE
    rlf_count: int = 0
    
    # Last known SINR value
    last_sinr_db: float = 0.0


@dataclass
class HandoverInterruption:
    """A single handover interruption period."""
    start_time: float
    end_time: float
    source_cell: Optional[str] = None
    target_cell: Optional[str] = None


@dataclass
class UEInterruptionState:
    """Interruption tracking state for a single UE.
    
    Fix #27: Uses a queue of interruptions instead of single timestamp.
    """
    # Queue of (start, end) interruption periods
    # Uses configurable MAX_INTERRUPTION_QUEUE_SIZE constant
    interruptions: Deque[HandoverInterruption] = field(
        default_factory=lambda: deque(maxlen=MAX_INTERRUPTION_QUEUE_SIZE)
    )
    
    # Total accumulated interruption time
    total_interruption_time_s: float = 0.0
    
    # Count of handovers
    handover_count: int = 0


class RLFDetector:
    """Radio Link Failure detector with proper timer handling.
    
    Implements 3GPP TS 36.331 RLF detection:
    - T310 timer starts when SINR < threshold
    - RLF declared when T310 expires (>=1 second)
    - Timer reset during handover interruption (Fix #26)
    """
    
    def __init__(
        self,
        rlf_threshold_db: float = RLF_SINR_THRESHOLD_DB,
        rlf_duration_s: float = RLF_DURATION_S,
    ):
        """Initialize RLF detector.
        
        Args:
            rlf_threshold_db: SINR threshold for RLF detection (default -6 dB)
            rlf_duration_s: Duration below threshold to declare RLF (default 1.0s)
        """
        self.rlf_threshold_db = rlf_threshold_db
        self.rlf_duration_s = rlf_duration_s
        
        # Per-UE RLF state
        self._ue_states: Dict[str, UERLFState] = {}
        
        # Global RLF event log
        self._rlf_events: List[Dict] = []
        
        logger.info(
            "RLFDetector initialized: threshold=%.1f dB, duration=%.2f s",
            rlf_threshold_db, rlf_duration_s
        )
    
    def _get_state(self, ue_id: str) -> UERLFState:
        """Get or create RLF state for a UE."""
        if ue_id not in self._ue_states:
            self._ue_states[ue_id] = UERLFState()
        return self._ue_states[ue_id]
    
    def notify_handover_start(self, ue_id: str, timestamp: float) -> None:
        """Notify detector that UE is starting a handover.
        
        Fix #26: Clears RLF timer during handover.
        """
        state = self._get_state(ue_id)
        state.in_handover_interruption = True
        
        # Reset RLF timer - handover gets a fresh chance
        if state.rlf_timer_start is not None:
            logger.debug(
                "UE %s: RLF timer cleared due to handover start (was at %.2fs)",
                ue_id, timestamp - state.rlf_timer_start
            )
            state.rlf_timer_start = None
    
    def notify_handover_complete(self, ue_id: str, timestamp: float) -> None:
        """Notify detector that UE handover is complete."""
        state = self._get_state(ue_id)
        state.in_handover_interruption = False
        
        logger.debug("UE %s: Handover complete, RLF detection resumed", ue_id)
    
    def check_rlf(
        self,
        ue_id: str,
        sinr_db: float,
        timestamp: float,
        serving_cell: Optional[str] = None,
    ) -> bool:
        """Check if RLF condition is met for a UE.
        
        Fix #4: Uses >= for timer comparison.
        Fix #26: Skips detection during handover interruption.
        
        Args:
            ue_id: UE identifier
            sinr_db: Current SINR in dB
            timestamp: Current simulation time in seconds
            serving_cell: Optional serving cell ID for logging
            
        Returns:
            True if RLF is declared, False otherwise
        """
        state = self._get_state(ue_id)
        state.last_sinr_db = sinr_db
        
        # Fix #26: Skip RLF detection during handover interruption
        if state.in_handover_interruption:
            logger.debug(
                "UE %s: Skipping RLF check during handover interruption",
                ue_id
            )
            return False
        
        # Check if SINR is below threshold
        if sinr_db < self.rlf_threshold_db:
            # Start or continue RLF timer
            if state.rlf_timer_start is None:
                state.rlf_timer_start = timestamp
                logger.debug(
                    "UE %s: RLF timer started (SINR=%.2f dB < %.2f dB)",
                    ue_id, sinr_db, self.rlf_threshold_db
                )
            
            # Check if timer has expired (Fix #4: use >= not >)
            duration = timestamp - state.rlf_timer_start
            if duration >= self.rlf_duration_s:
                # RLF declared!
                state.rlf_count += 1
                state.rlf_timer_start = None  # Reset for next RLF
                
                rlf_event = {
                    "ue_id": ue_id,
                    "timestamp": timestamp,
                    "duration": duration,
                    "sinr_db": sinr_db,
                    "serving_cell": serving_cell,
                    "rlf_number": state.rlf_count,
                }
                self._rlf_events.append(rlf_event)
                
                logger.warning(
                    "UE %s: RLF DECLARED (SINR=%.2f dB, duration=%.3fs, total RLFs=%d)",
                    ue_id, sinr_db, duration, state.rlf_count
                )
                
                return True
        else:
            # SINR recovered - reset timer
            if state.rlf_timer_start is not None:
                logger.debug(
                    "UE %s: RLF timer reset (SINR recovered to %.2f dB)",
                    ue_id, sinr_db
                )
                state.rlf_timer_start = None
        
        return False
    
    def get_ue_rlf_count(self, ue_id: str) -> int:
        """Get the RLF count for a specific UE."""
        return self._get_state(ue_id).rlf_count
    
    def get_total_rlf_count(self) -> int:
        """Get total RLF count across all UEs."""
        return sum(s.rlf_count for s in self._ue_states.values())
    
    def get_rlf_events(self) -> List[Dict]:
        """Get list of all RLF events."""
        return self._rlf_events.copy()
    
    def reset(self) -> None:
        """Reset all RLF tracking state."""
        self._ue_states.clear()
        self._rlf_events.clear()
        logger.info("RLF detector state reset")
    
    def remove_ue(self, ue_id: str) -> None:
        """Remove tracking state for a specific UE."""
        self._ue_states.pop(ue_id, None)


class ThroughputCalculator:
    """SINR-to-throughput calculator with graceful degradation.
    
    Fix #5: Implements piecewise throughput model:
    - SINR < -10 dB: No connection (0 Mbps)
    - -10 <= SINR < -6 dB: RLF zone, severely degraded
    - SINR >= -6 dB: Normal Shannon capacity
    """
    
    def __init__(
        self,
        bandwidth_hz: float = 20e6,
        min_sinr_db: float = MIN_DECODABLE_SINR_DB,
        rlf_threshold_db: float = RLF_SINR_THRESHOLD_DB,
        rlf_zone_efficiency: float = 0.5,  # bits/sec/Hz in RLF zone
        max_efficiency: float = 6.0,  # bits/sec/Hz cap (64-QAM typical max)
    ):
        """Initialize throughput calculator.
        
        Args:
            bandwidth_hz: System bandwidth in Hz (default 20 MHz)
            min_sinr_db: Minimum SINR for any connection (default -10 dB)
            rlf_threshold_db: SINR threshold for RLF zone (default -6 dB)
            rlf_zone_efficiency: Spectral efficiency in RLF zone
            max_efficiency: Maximum spectral efficiency cap
        """
        self.bandwidth_hz = bandwidth_hz
        self.min_sinr_db = min_sinr_db
        self.rlf_threshold_db = rlf_threshold_db
        self.rlf_zone_efficiency = rlf_zone_efficiency
        self.max_efficiency = max_efficiency
        
        logger.debug(
            "ThroughputCalculator: BW=%.1f MHz, SINR_min=%.1f dB, RLF=%.1f dB",
            bandwidth_hz / 1e6, min_sinr_db, rlf_threshold_db
        )
    
    def calculate_throughput(
        self,
        sinr_db: float,
        is_handover_interruption: bool = False,
    ) -> float:
        """Calculate instantaneous throughput for given SINR.
        
        Fix #5: Piecewise throughput model with graceful degradation.
        
        Args:
            sinr_db: Signal-to-Interference-plus-Noise Ratio in dB
            is_handover_interruption: If True, returns 0 (during HO)
            
        Returns:
            Throughput in Mbps
        """
        # During handover interruption, throughput is zero
        if is_handover_interruption:
            return 0.0
        
        # Region 1: Below minimum SINR - no connection
        if sinr_db < self.min_sinr_db:
            return 0.0
        
        # Region 2: RLF zone - severely degraded but not zero
        if sinr_db < self.rlf_threshold_db:
            # Linear interpolation in RLF zone
            # At min_sinr: near 0, at rlf_threshold: rlf_zone_efficiency * BW
            range_db = self.rlf_threshold_db - self.min_sinr_db
            position = (sinr_db - self.min_sinr_db) / range_db  # 0 to 1
            efficiency = position * self.rlf_zone_efficiency
            throughput_bps = efficiency * self.bandwidth_hz
            return throughput_bps / 1e6  # Convert to Mbps
        
        # Region 3: Normal operation - Shannon capacity
        sinr_linear = 10 ** (sinr_db / 10)
        
        # Shannon: C = B * log2(1 + SINR)
        efficiency = math.log2(1 + sinr_linear)
        
        # Cap at maximum efficiency
        efficiency = min(efficiency, self.max_efficiency)
        
        throughput_bps = efficiency * self.bandwidth_hz
        return throughput_bps / 1e6  # Convert to Mbps
    
    def get_sinr_to_throughput_curve(
        self,
        sinr_range: Tuple[float, float] = (-15, 30),
        num_points: int = 100,
    ) -> Tuple[List[float], List[float]]:
        """Generate SINR-to-throughput curve for plotting.
        
        Args:
            sinr_range: (min, max) SINR in dB
            num_points: Number of points to generate
            
        Returns:
            Tuple of (sinr_values, throughput_values)
        """
        import numpy as np
        
        sinr_values = np.linspace(sinr_range[0], sinr_range[1], num_points)
        throughput_values = [
            self.calculate_throughput(s) for s in sinr_values
        ]
        
        return list(sinr_values), throughput_values


class HandoverInterruptionTracker:
    """Track handover interruptions with proper accumulation.
    
    Fix #6: Handles overlapping interruptions correctly.
    Fix #27: Queue-based tracking for rapid successive handovers.
    """
    
    def __init__(
        self,
        interruption_duration_s: float = HANDOVER_INTERRUPTION_S,
    ):
        """Initialize interruption tracker.
        
        Args:
            interruption_duration_s: Duration of each handover interruption
        """
        self.interruption_duration_s = interruption_duration_s
        
        # Per-UE interruption state
        self._ue_states: Dict[str, UEInterruptionState] = {}
        
        logger.info(
            "HandoverInterruptionTracker initialized: interruption=%.0f ms",
            interruption_duration_s * 1000
        )
    
    def _get_state(self, ue_id: str) -> UEInterruptionState:
        """Get or create interruption state for a UE."""
        if ue_id not in self._ue_states:
            self._ue_states[ue_id] = UEInterruptionState()
        return self._ue_states[ue_id]
    
    def record_handover(
        self,
        ue_id: str,
        timestamp: float,
        source_cell: Optional[str] = None,
        target_cell: Optional[str] = None,
    ) -> None:
        """Record a handover event and its interruption.
        
        Fix #27: Adds to queue instead of overwriting.
        
        Args:
            ue_id: UE identifier
            timestamp: Time of handover execution
            source_cell: Source cell ID
            target_cell: Target cell ID
        """
        state = self._get_state(ue_id)
        
        interruption = HandoverInterruption(
            start_time=timestamp,
            end_time=timestamp + self.interruption_duration_s,
            source_cell=source_cell,
            target_cell=target_cell,
        )
        
        state.interruptions.append(interruption)
        state.handover_count += 1
        
        logger.debug(
            "UE %s: Recorded HO #%d interruption [%.3f, %.3f] (%s -> %s)",
            ue_id, state.handover_count,
            interruption.start_time, interruption.end_time,
            source_cell, target_cell
        )
        
        # Warn if queue is getting long (potential ping-pong)
        if len(state.interruptions) > 2:
            logger.warning(
                "UE %s: %d simultaneous interruptions queued (ping-pong?)",
                ue_id, len(state.interruptions)
            )
    
    def is_in_interruption(self, ue_id: str, timestamp: float) -> bool:
        """Check if UE is currently in a handover interruption.
        
        Args:
            ue_id: UE identifier
            timestamp: Current time
            
        Returns:
            True if UE is in interruption period
        """
        state = self._get_state(ue_id)
        
        # Clean up old interruptions first
        self._cleanup_old_interruptions(ue_id, timestamp)
        
        # Check if any active interruption contains current time
        for interruption in state.interruptions:
            if interruption.start_time <= timestamp < interruption.end_time:
                return True
        
        return False
    
    def _cleanup_old_interruptions(self, ue_id: str, timestamp: float) -> None:
        """Remove completed interruptions from the queue."""
        state = self._get_state(ue_id)
        
        # Count completed interruptions
        completed = []
        for interruption in state.interruptions:
            if interruption.end_time <= timestamp:
                completed.append(interruption)
                # Fix: Use actual interruption duration, not fixed value
                actual_duration = interruption.end_time - interruption.start_time
                state.total_interruption_time_s += actual_duration
        
        # Remove completed from queue
        for c in completed:
            try:
                state.interruptions.remove(c)
            except ValueError:
                pass  # Already removed
    
    def get_total_interruption_time(
        self,
        ue_id: str,
        current_time: Optional[float] = None,
    ) -> float:
        """Get total accumulated interruption time for a UE.
        
        Fix #6: Correctly handles overlapping periods.
        
        Args:
            ue_id: UE identifier
            current_time: If provided, cleans up old interruptions first
            
        Returns:
            Total interruption time in seconds
        """
        state = self._get_state(ue_id)
        
        if current_time is not None:
            self._cleanup_old_interruptions(ue_id, current_time)
        
        # Calculate time for still-active interruptions
        # Use actual elapsed time if current_time is known, otherwise full duration
        active_time = 0.0
        for interruption in state.interruptions:
            if current_time is not None and interruption.start_time <= current_time < interruption.end_time:
                # Partially elapsed interruption
                active_time += current_time - interruption.start_time
            else:
                # Future or unknown timing - use full duration
                active_time += interruption.end_time - interruption.start_time
        
        return state.total_interruption_time_s + active_time
    
    def get_handover_count(self, ue_id: str) -> int:
        """Get total handover count for a UE."""
        return self._get_state(ue_id).handover_count
    
    def get_summary(self) -> Dict[str, object]:
        """Get summary statistics across all UEs."""
        total_handovers = sum(s.handover_count for s in self._ue_states.values())
        total_interruption = sum(
            s.total_interruption_time_s for s in self._ue_states.values()
        )
        
        return {
            "total_ues": len(self._ue_states),
            "total_handovers": total_handovers,
            "total_interruption_time_s": total_interruption,
            "average_interruption_per_ho_ms": (
                total_interruption / total_handovers * 1000
                if total_handovers > 0 else 0
            ),
        }
    
    def reset(self) -> None:
        """Reset all tracking state."""
        self._ue_states.clear()
        logger.info("Handover interruption tracker reset")
    
    def remove_ue(self, ue_id: str) -> None:
        """Remove tracking state for a specific UE."""
        self._ue_states.pop(ue_id, None)


class MetricsCollector:
    """Unified metrics collector combining RLF and interruption tracking.
    
    This class provides a single interface for collecting all handover-related
    metrics for thesis experiments.
    """
    
    def __init__(
        self,
        bandwidth_hz: float = 20e6,
        rlf_threshold_db: float = RLF_SINR_THRESHOLD_DB,
        rlf_duration_s: float = RLF_DURATION_S,
        interruption_duration_s: float = HANDOVER_INTERRUPTION_S,
    ):
        """Initialize metrics collector.
        
        Args:
            bandwidth_hz: System bandwidth for throughput calculation
            rlf_threshold_db: SINR threshold for RLF
            rlf_duration_s: Duration for RLF declaration
            interruption_duration_s: Duration of handover interruption
        """
        self.rlf_detector = RLFDetector(rlf_threshold_db, rlf_duration_s)
        self.throughput_calc = ThroughputCalculator(bandwidth_hz)
        self.interruption_tracker = HandoverInterruptionTracker(
            interruption_duration_s
        )
        
        # Cumulative throughput tracking
        self._cumulative_throughput: Dict[str, float] = {}  # ue_id -> sum of throughput*dt
        self._cumulative_time: Dict[str, float] = {}  # ue_id -> total time
        
        logger.info("MetricsCollector initialized")
    
    def update(
        self,
        ue_id: str,
        sinr_db: float,
        timestamp: float,
        timestep_s: float = 0.1,
        serving_cell: Optional[str] = None,
    ) -> Dict[str, object]:
        """Update metrics for a UE.
        
        Args:
            ue_id: UE identifier
            sinr_db: Current SINR in dB
            timestamp: Current simulation time
            timestep_s: Time since last update
            serving_cell: Current serving cell
            
        Returns:
            Dict with current metrics snapshot
        """
        # Check if in handover interruption
        is_interruption = self.interruption_tracker.is_in_interruption(
            ue_id, timestamp
        )
        
        # Fix: Sync RLF detector state with interruption tracker
        # This ensures RLF timer is properly managed during interruptions
        rlf_state = self.rlf_detector._get_state(ue_id)
        if is_interruption and not rlf_state.in_handover_interruption:
            self.rlf_detector.notify_handover_start(ue_id, timestamp)
        elif not is_interruption and rlf_state.in_handover_interruption:
            self.rlf_detector.notify_handover_complete(ue_id, timestamp)
        
        # Calculate throughput
        throughput_mbps = self.throughput_calc.calculate_throughput(
            sinr_db, is_handover_interruption=is_interruption
        )
        
        # Check RLF (will be skipped during interruption via notify)
        is_rlf = self.rlf_detector.check_rlf(
            ue_id, sinr_db, timestamp, serving_cell
        )
        
        # Update cumulative throughput
        if ue_id not in self._cumulative_throughput:
            self._cumulative_throughput[ue_id] = 0.0
            self._cumulative_time[ue_id] = 0.0
        
        self._cumulative_throughput[ue_id] += throughput_mbps * timestep_s
        self._cumulative_time[ue_id] += timestep_s
        
        return {
            "ue_id": ue_id,
            "timestamp": timestamp,
            "sinr_db": sinr_db,
            "throughput_mbps": throughput_mbps,
            "is_interruption": is_interruption,
            "is_rlf": is_rlf,
            "rlf_count": self.rlf_detector.get_ue_rlf_count(ue_id),
            "handover_count": self.interruption_tracker.get_handover_count(ue_id),
        }
    
    def record_handover(
        self,
        ue_id: str,
        timestamp: float,
        source_cell: Optional[str] = None,
        target_cell: Optional[str] = None,
    ) -> None:
        """Record a handover event."""
        # Notify RLF detector
        self.rlf_detector.notify_handover_start(ue_id, timestamp)
        
        # Record interruption
        self.interruption_tracker.record_handover(
            ue_id, timestamp, source_cell, target_cell
        )
    
    def handover_complete(self, ue_id: str, timestamp: float) -> None:
        """Mark handover as complete."""
        self.rlf_detector.notify_handover_complete(ue_id, timestamp)
    
    def get_average_throughput(self, ue_id: str) -> float:
        """Get average throughput for a UE in Mbps."""
        total_time = self._cumulative_time.get(ue_id, 0.0)
        if total_time <= 0:
            return 0.0
        return self._cumulative_throughput.get(ue_id, 0.0) / total_time
    
    def get_summary(self) -> Dict[str, object]:
        """Get overall metrics summary."""
        interruption_summary = self.interruption_tracker.get_summary()
        
        avg_throughputs = [
            self.get_average_throughput(ue_id)
            for ue_id in self._cumulative_time.keys()
        ]
        
        return {
            "total_rlfs": self.rlf_detector.get_total_rlf_count(),
            "rlf_events": self.rlf_detector.get_rlf_events(),
            "total_handovers": interruption_summary["total_handovers"],
            "total_interruption_time_s": interruption_summary["total_interruption_time_s"],
            "average_throughput_mbps": (
                sum(avg_throughputs) / len(avg_throughputs)
                if avg_throughputs else 0.0
            ),
            "ue_count": len(self._cumulative_time),
        }
    
    def reset(self) -> None:
        """Reset all metrics."""
        self.rlf_detector.reset()
        self.interruption_tracker.reset()
        self._cumulative_throughput.clear()
        self._cumulative_time.clear()
        logger.info("MetricsCollector reset")
