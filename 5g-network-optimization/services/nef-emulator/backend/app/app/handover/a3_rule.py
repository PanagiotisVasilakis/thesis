"""Event A3 handover rule with hysteresis and time-to-trigger."""
from datetime import datetime, timedelta
from typing import Dict, Optional, Union


class A3EventRule:
    """Implements 3GPP Event A3 hysteresis/time-to-trigger logic with enhanced features."""

    def __init__(self, 
                 hysteresis_db: float = 2.0, 
                 ttt_seconds: float = 0.0,
                 use_rsrq: bool = True,
                 rsrq_threshold: float = -10.0,
                 event_type: str = "rsrp_based"):
        """
        Initialize A3 event rule with configurable parameters.
        
        Args:
            hysteresis_db: Hysteresis margin in dB (A3-Offset)
            ttt_seconds: Time-to-Trigger in seconds
            use_rsrq: Whether to consider RSRQ in evaluation (3GPP allows mixed criteria)
            rsrq_threshold: Minimum RSRQ threshold for the target cell
            event_type: Type of A3 evaluation ("rsrp_based", "rsrq_based", "mixed")
        """
        if hysteresis_db < 0:
            raise ValueError("hysteresis_db must be non-negative")
        if ttt_seconds < 0:
            raise ValueError("ttt_seconds must be non-negative")
        if event_type not in ["rsrp_based", "rsrq_based", "mixed"]:
            raise ValueError("event_type must be one of: 'rsrp_based', 'rsrq_based', 'mixed'")

        self.hysteresis_db = hysteresis_db
        self.ttt = timedelta(seconds=ttt_seconds)
        self.use_rsrq = use_rsrq
        self.rsrq_threshold = rsrq_threshold
        self.event_type = event_type
        self._event_start_time: Optional[datetime] = None

    def check_condition(
        self,
        serving_metrics: Union[float, Dict[str, float]],
        target_metrics: Union[float, Dict[str, float]],
    ) -> bool:
        """
        Check if A3 condition is met (pure signal comparison, no TTT).
        
        This is the core A3 event condition check without Time-to-Trigger logic.
        TTT should be managed externally (e.g., per-UE in HandoverEngine) to support
        proper multi-UE scenarios.
        
        Args:
            serving_metrics: Either RSRP value or dict with 'rsrp' and 'rsrq' keys
            target_metrics: Either RSRP value or dict with 'rsrp' and 'rsrq' keys
            
        Returns:
            True if A3 condition is satisfied (target better than serving + hysteresis)
        """
        # Handle both single value and dict input
        if isinstance(serving_metrics, dict):
            serving_rsrp = serving_metrics.get('rsrp', float('-inf'))
            serving_rsrq = serving_metrics.get('rsrq', float('-inf'))
        else:
            serving_rsrp = serving_metrics
            serving_rsrq = float('-inf')
            
        if isinstance(target_metrics, dict):
            target_rsrp = target_metrics.get('rsrp', float('-inf'))
            target_rsrq = target_metrics.get('rsrq', float('-inf'))
        else:
            target_rsrp = target_metrics
            target_rsrq = float('-inf')

        # Check A3 condition based on event type
        if self.event_type == "rsrp_based":
            return (target_rsrp - serving_rsrp) > self.hysteresis_db
            
        elif self.event_type == "rsrq_based":
            return (target_rsrq - serving_rsrq) > self.hysteresis_db
            
        elif self.event_type == "mixed":
            rsrp_condition = (target_rsrp - serving_rsrp) > self.hysteresis_db
            rsrq_condition = target_rsrq >= self.rsrq_threshold
            return rsrp_condition and rsrq_condition
        
        return False

    def check(
        self, 
        serving_metrics: Union[float, Dict[str, float]], 
        target_metrics: Union[float, Dict[str, float]], 
        now: datetime
    ) -> bool:
        """
        Return True if the A3 condition has been met for the TTT duration.
        
        Note: This method uses a single global timer. For multi-UE scenarios,
        use check_condition() and manage TTT externally per-UE in HandoverEngine.
        
        Args:
            serving_metrics: Either RSRP value or dict with 'rsrp' and 'rsrq' keys
            target_metrics: Either RSRP value or dict with 'rsrp' and 'rsrq' keys
            now: Current timestamp
        """
        a3_condition_met = self.check_condition(serving_metrics, target_metrics)

        if a3_condition_met:
            if self.ttt.total_seconds() == 0:
                self._reset()
                return True

            # Start timing if not already started
            if self._event_start_time is None:
                self._event_start_time = now
            # Check if time-to-trigger has been satisfied
            elif now - self._event_start_time >= self.ttt:
                # Reset and return True
                self._reset()
                return True
        else:
            # Reset timer if condition is not met
            self._reset()
            
        return False
    
    def _reset(self) -> None:
        """Reset the internal timer state."""
        self._event_start_time = None

    def get_status(self) -> Dict[str, Union[datetime, bool, float, str]]:
        """Get current status of the A3 event evaluation."""
        return {
            "hysteresis_db": self.hysteresis_db,
            "ttt_seconds": self.ttt.total_seconds(),
            "use_rsrq": self.use_rsrq,
            "rsrq_threshold": self.rsrq_threshold,
            "event_type": self.event_type,
            "is_event_active": self._event_start_time is not None,
            "event_start_time": self._event_start_time,
        }
