"""Feature extraction utilities for training data collection."""

import logging
from typing import Dict, Any, Optional, Tuple, List
from collections import deque

from ..utils.mobility_metrics import MobilityMetricTracker
from ..utils.memory_managed_dict import UETrackingDict
from ..features import pipeline
from ..utils.antenna_selection import select_optimal_antenna


class FeatureExtractor:
    """Extracts and processes features from raw UE data for ML training."""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
    def extract_rf_features(self, feature_vector: Dict[str, Any]) -> Dict[str, Dict[str, float]]:
        """Extract and validate RF metrics from feature vector.
        
        Args:
            feature_vector: Raw feature vector from NEF client
            
        Returns:
            Dictionary of RF metrics per antenna
        """
        return pipeline.extract_rf_features(feature_vector)
    
    def extract_environment_features(self, feature_vector: Dict[str, Any]) -> Dict[str, Optional[float]]:
        """Extract and validate environment-related features.
        
        Args:
            feature_vector: Raw feature vector from NEF client
            
        Returns:
            Dictionary of environment features
        """
        return pipeline.extract_environment_features(feature_vector)
    
    def determine_optimal_antenna(self, rf_metrics: Dict[str, Dict[str, float]]) -> str:
        """Determine the optimal antenna using shared QoS-aware heuristics."""
        winner, _ = select_optimal_antenna(rf_metrics)
        return winner


class HandoverTracker:
    """Tracks handover events and timing for UEs with anti-ping-pong support."""
    
    def __init__(self, max_ues: int = 10000, ue_ttl_hours: float = 24.0):
        self.logger = logging.getLogger(__name__)
        
        # Memory-managed tracking dictionaries
        self._prev_cell: UETrackingDict[str] = UETrackingDict(max_ues=max_ues, ue_ttl_hours=ue_ttl_hours)
        self._handover_counts: UETrackingDict[int] = UETrackingDict(max_ues=max_ues, ue_ttl_hours=ue_ttl_hours)
        self._last_handover_ts: UETrackingDict[float] = UETrackingDict(max_ues=max_ues, ue_ttl_hours=ue_ttl_hours)
        # Track cell history for ping-pong detection (stores list of (cell_id, timestamp) tuples)
        self._cell_history: UETrackingDict[list] = UETrackingDict(max_ues=max_ues, ue_ttl_hours=ue_ttl_hours)
        # Track handovers in 1-minute window for ping-pong rate calculation
        self._recent_handovers: UETrackingDict[deque] = UETrackingDict(max_ues=max_ues, ue_ttl_hours=ue_ttl_hours)
    
    def update_handover_state(self, ue_id: str, current_cell: str, timestamp: float) -> Tuple[int, float]:
        """Update handover state for a UE and return metrics.
        
        Args:
            ue_id: UE identifier
            current_cell: Currently connected cell ID
            timestamp: Current timestamp
            
        Returns:
            Tuple of (handover_count, time_since_handover)
        """
        prev_cell = self._prev_cell.get(ue_id)
        
        # Check for handover
        if prev_cell is not None and prev_cell != current_cell:
            self._handover_counts[ue_id] = self._handover_counts.get(ue_id, 0) + 1
            self._last_handover_ts[ue_id] = timestamp
            self.logger.debug(f"Handover detected for UE {ue_id}: {prev_cell} -> {current_cell}")
            
            # Track in recent handovers window (60 seconds)
            if ue_id not in self._recent_handovers:
                self._recent_handovers[ue_id] = deque()
            self._recent_handovers[ue_id].append(timestamp)
            
            # Clean old entries (older than 60 seconds)
            while (self._recent_handovers[ue_id] and 
                   timestamp - self._recent_handovers[ue_id][0] > 60.0):
                self._recent_handovers[ue_id].popleft()
        
        # Update current cell
        self._prev_cell[ue_id] = current_cell
        
        # Track cell history for ping-pong detection
        if ue_id not in self._cell_history:
            self._cell_history[ue_id] = []
        self._cell_history[ue_id].append((current_cell, timestamp))
        
        # Keep only last 10 cells in history
        if len(self._cell_history[ue_id]) > 10:
            self._cell_history[ue_id] = self._cell_history[ue_id][-10:]
        
        # Initialize timestamps for new UEs
        if ue_id not in self._last_handover_ts:
            self._last_handover_ts[ue_id] = timestamp
        
        handover_count = self._handover_counts.get(ue_id, 0)
        time_since_handover = timestamp - self._last_handover_ts.get(ue_id, timestamp)
        
        return handover_count, time_since_handover
    
    def get_recent_cells(self, ue_id: str, n: int = 5) -> List[str]:
        """Get list of recent cells (most recent first).
        
        Args:
            ue_id: UE identifier
            n: Number of recent cells to return
            
        Returns:
            List of recent cell IDs (most recent first)
        """
        history = self._cell_history.get(ue_id, [])
        # Return last n cells in reverse order (most recent first)
        return [cell for cell, _ in history[-n:]][::-1]
    
    def get_handovers_in_window(self, ue_id: str, window_seconds: float = 60.0) -> int:
        """Get number of handovers in the specified time window.
        
        Args:
            ue_id: UE identifier
            window_seconds: Time window in seconds (default: 60)
            
        Returns:
            Number of handovers in the window
        """
        recent = self._recent_handovers.get(ue_id, deque())
        return len(recent)
    
    def check_immediate_pingpong(self, ue_id: str, target_cell: str, window_seconds: float = 10.0) -> bool:
        """Check if handover to target_cell would be an immediate ping-pong.
        
        An immediate ping-pong is detected if the target cell was recently
        (within window_seconds) the serving cell for this UE.
        
        Args:
            ue_id: UE identifier
            target_cell: Target cell for potential handover
            window_seconds: Time window to check (default: 10s)
            
        Returns:
            True if immediate ping-pong detected, False otherwise
        """
        history = self._cell_history.get(ue_id, [])
        if len(history) < 2:
            return False
        
        current_time = history[-1][1] if history else 0.0
        
        # Check if target cell appears in recent history (excluding current)
        # Check last 5 cells before current (most recent first)
        for cell, timestamp in history[-5:-1]:
            if cell == target_cell:
                time_diff = current_time - timestamp
                if time_diff <= window_seconds:
                    return True
        
        return False
    
    def get_stats(self) -> Dict[str, Any]:
        """Get tracking statistics."""
        return {
            "tracked_ues": len(self._prev_cell),
            "total_handovers": sum(self._handover_counts.values()),
            "memory_usage": {
                "prev_cell": self._prev_cell.get_memory_usage(),
                "handover_counts": self._handover_counts.get_memory_usage(),
                "last_handover_ts": self._last_handover_ts.get_memory_usage(),
                "cell_history": self._cell_history.get_memory_usage(),
                "recent_handovers": self._recent_handovers.get_memory_usage()
            }
        }


class SignalProcessor:
    """Processes signal quality metrics and trends with temporal derivatives."""
    
    def __init__(self, signal_window_size: int = 5, max_ues: int = 10000, ue_ttl_hours: float = 24.0):
        self.signal_window_size = signal_window_size
        self.logger = logging.getLogger(__name__)
        
        # Memory-managed tracking dictionaries
        self._prev_signal: UETrackingDict[dict] = UETrackingDict(max_ues=max_ues, ue_ttl_hours=ue_ttl_hours)
        self._signal_buffer: UETrackingDict[dict] = UETrackingDict(max_ues=max_ues, ue_ttl_hours=ue_ttl_hours)
        # Track previous trend values for acceleration calculation
        self._prev_trend: UETrackingDict[dict] = UETrackingDict(max_ues=max_ues, ue_ttl_hours=ue_ttl_hours)
        # EMA tracking for trend divergence
        self._ema_state: UETrackingDict[dict] = UETrackingDict(max_ues=max_ues, ue_ttl_hours=ue_ttl_hours)
    
    def update_signal_metrics(self, ue_id: str, current_rsrp: Optional[float], 
                            current_sinr: Optional[float], current_rsrq: Optional[float]) -> Tuple[float, float]:
        """Update signal metrics and calculate statistics.
        
        Args:
            ue_id: UE identifier
            current_rsrp: Current RSRP value
            current_sinr: Current SINR value
            current_rsrq: Current RSRQ value
            
        Returns:
            Tuple of (rsrp_stddev, sinr_stddev)
        """
        # Initialize signal buffer for new UEs
        if ue_id not in self._signal_buffer:
            self._signal_buffer[ue_id] = {
                "rsrp": deque(maxlen=self.signal_window_size),
                "sinr": deque(maxlen=self.signal_window_size),
            }
        
        buffer = self._signal_buffer[ue_id]
        
        # Add current values to buffer
        if current_rsrp is not None:
            buffer["rsrp"].append(current_rsrp)
        if current_sinr is not None:
            buffer["sinr"].append(current_sinr)
        
        # Calculate standard deviations
        rsrp_stddev = self._calculate_stddev(buffer["rsrp"])
        sinr_stddev = self._calculate_stddev(buffer["sinr"])
        
        return rsrp_stddev, sinr_stddev
    
    def calculate_signal_trend(self, ue_id: str, current_rsrp: Optional[float], 
                             current_sinr: Optional[float], current_rsrq: Optional[float]) -> float:
        """Calculate signal trend based on previous measurements.
        
        Args:
            ue_id: UE identifier
            current_rsrp: Current RSRP value
            current_sinr: Current SINR value
            current_rsrq: Current RSRQ value
            
        Returns:
            Signal trend value
        """
        prev_signal = self._prev_signal.get(ue_id)
        
        if prev_signal is None:
            signal_trend = 0.0
        else:
            diffs = []
            if current_rsrp is not None:
                diffs.append(current_rsrp - prev_signal.get("rsrp", 0))
            if current_sinr is not None:
                diffs.append(current_sinr - prev_signal.get("sinr", 0))
            if current_rsrq is not None:
                diffs.append(current_rsrq - prev_signal.get("rsrq", 0))
            
            signal_trend = sum(diffs) / len(diffs) if diffs else 0.0
        
        # Update previous signal values
        self._prev_signal[ue_id] = {
            "rsrp": current_rsrp or 0,
            "sinr": current_sinr or 0,
            "rsrq": current_rsrq or 0,
        }
        
        return signal_trend
    
    def compute_temporal_features(
        self,
        ue_id: str,
        current_rsrp: Optional[float],
        current_sinr: Optional[float],
    ) -> Dict[str, float]:
        """Compute temporal derivative features for better prediction.
        
        These features capture rate of change and momentum in signals,
        helping the model predict future conditions rather than just
        reacting to current state.
        
        Args:
            ue_id: UE identifier
            current_rsrp: Current RSRP value (dBm)
            current_sinr: Current SINR value (dB)
            
        Returns:
            Dictionary of temporal features:
                - rsrp_acceleration: Rate of change of RSRP trend
                - sinr_acceleration: Rate of change of SINR trend
                - rsrp_ema_short: Short-term EMA (3 samples)
                - rsrp_ema_long: Long-term EMA (10 samples)
                - rsrp_trend_divergence: Difference between short and long EMA
        """
        result = {
            "rsrp_acceleration": 0.0,
            "sinr_acceleration": 0.0,
            "rsrp_ema_short": current_rsrp or -85.0,
            "rsrp_ema_long": current_rsrp or -85.0,
            "rsrp_trend_divergence": 0.0,
        }
        
        # Get previous state
        prev_trend = self._prev_trend.get(ue_id, {})
        ema_state = self._ema_state.get(ue_id, {})
        
        # Calculate current trends
        current_rsrp_trend = 0.0
        current_sinr_trend = 0.0
        
        prev_signal = self._prev_signal.get(ue_id)
        if prev_signal is not None:
            if current_rsrp is not None:
                current_rsrp_trend = current_rsrp - prev_signal.get("rsrp", current_rsrp)
            if current_sinr is not None:
                current_sinr_trend = current_sinr - prev_signal.get("sinr", current_sinr)
        
        # Calculate acceleration (second derivative: rate of change of trend)
        prev_rsrp_trend = prev_trend.get("rsrp_trend", 0.0)
        prev_sinr_trend = prev_trend.get("sinr_trend", 0.0)
        
        result["rsrp_acceleration"] = current_rsrp_trend - prev_rsrp_trend
        result["sinr_acceleration"] = current_sinr_trend - prev_sinr_trend
        
        # Update trend state for next iteration
        self._prev_trend[ue_id] = {
            "rsrp_trend": current_rsrp_trend,
            "sinr_trend": current_sinr_trend,
        }
        
        # Calculate EMAs (Exponential Moving Averages)
        if current_rsrp is not None:
            # Short-term EMA (alpha = 2/(3+1) = 0.5)
            alpha_short = 0.5
            prev_ema_short = ema_state.get("ema_short", current_rsrp)
            ema_short = alpha_short * current_rsrp + (1 - alpha_short) * prev_ema_short
            
            # Long-term EMA (alpha = 2/(10+1) ≈ 0.18)
            alpha_long = 0.18
            prev_ema_long = ema_state.get("ema_long", current_rsrp)
            ema_long = alpha_long * current_rsrp + (1 - alpha_long) * prev_ema_long
            
            result["rsrp_ema_short"] = ema_short
            result["rsrp_ema_long"] = ema_long
            result["rsrp_trend_divergence"] = ema_short - ema_long
            
            # Update EMA state
            self._ema_state[ue_id] = {
                "ema_short": ema_short,
                "ema_long": ema_long,
            }
        
        return result
    
    def _calculate_stddev(self, values: deque) -> float:
        """Calculate standard deviation of values in deque."""
        n = len(values)
        if n == 0:
            return 0.0
        
        mean_val = sum(values) / n
        variance = sum((v - mean_val) ** 2 for v in values) / n
        return variance ** 0.5
    
    def get_stats(self) -> Dict[str, Any]:
        """Get signal processing statistics."""
        return {
            "tracked_ues": len(self._prev_signal),
            "signal_window_size": self.signal_window_size,
            "memory_usage": {
                "prev_signal": self._prev_signal.get_memory_usage(),
                "signal_buffer": self._signal_buffer.get_memory_usage(),
                "prev_trend": self._prev_trend.get_memory_usage(),
                "ema_state": self._ema_state.get_memory_usage(),
            }
        }


class MobilityProcessor:
    """Processes mobility-related features and metrics."""
    
    def __init__(self, position_window_size: int = 5, max_ues: int = 10000, ue_ttl_hours: float = 24.0):
        self.tracker = MobilityMetricTracker(position_window_size)
        self.logger = logging.getLogger(__name__)
        
        # Memory-managed tracking for speed calculations
        self._prev_speed: UETrackingDict[float] = UETrackingDict(max_ues=max_ues, ue_ttl_hours=ue_ttl_hours)
    
    def update_mobility_metrics(self, ue_id: str, latitude: float, longitude: float, 
                               speed: Optional[float]) -> Tuple[float, float, float]:
        """Update mobility metrics for a UE.
        
        Args:
            ue_id: UE identifier
            latitude: Current latitude
            longitude: Current longitude
            speed: Current speed (optional)
            
        Returns:
            Tuple of (heading_change_rate, path_curvature, calculated_acceleration)
        """
        # Update position-based metrics
        heading_change_rate, path_curvature = self.tracker.update_position(ue_id, latitude, longitude)
        
        # Calculate acceleration if speed is available
        acceleration = 0.0
        if speed is not None:
            prev_speed = self._prev_speed.get(ue_id)
            if prev_speed is not None:
                acceleration = speed - prev_speed
            self._prev_speed[ue_id] = speed
        
        return heading_change_rate, path_curvature, acceleration
    
    def get_stats(self) -> Dict[str, Any]:
        """Get mobility processing statistics."""
        return {
            "tracked_ues": len(self._prev_speed),
            "memory_usage": {
                "prev_speed": self._prev_speed.get_memory_usage()
            }
        }