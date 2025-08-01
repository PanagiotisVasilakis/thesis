"""Feature extraction utilities for training data collection."""

import logging
from typing import Dict, Any, Optional, Tuple
from collections import deque

from ..utils.mobility_metrics import MobilityMetricTracker
from ..utils.memory_managed_dict import UETrackingDict


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
        rsrps = feature_vector.get("neighbor_rsrp_dbm", {})
        sinrs = feature_vector.get("neighbor_sinrs", {})
        rsrqs = feature_vector.get("neighbor_rsrqs", {})
        loads = feature_vector.get("neighbor_cell_loads", {})
        
        # Validate and sanitize RF metrics
        if not isinstance(rsrps, dict):
            rsrps = {}
        if not isinstance(sinrs, dict):
            sinrs = {}
        if not isinstance(rsrqs, dict):
            rsrqs = {}
        if not isinstance(loads, dict):
            loads = {}
        
        rf_metrics = {}
        for antenna_id in rsrps.keys():
            rsrp = rsrps.get(antenna_id)
            sinr = sinrs.get(antenna_id)
            rsrq = rsrqs.get(antenna_id)
            load = loads.get(antenna_id)
            
            metrics = {"rsrp": rsrp}
            if sinr is not None:
                metrics["sinr"] = sinr
            if rsrq is not None:
                metrics["rsrq"] = rsrq
            if load is not None:
                metrics["cell_load"] = load
                
            rf_metrics[antenna_id] = metrics
            
        return rf_metrics
    
    def extract_environment_features(self, feature_vector: Dict[str, Any]) -> Dict[str, Optional[float]]:
        """Extract and validate environment-related features.
        
        Args:
            feature_vector: Raw feature vector from NEF client
            
        Returns:
            Dictionary of environment features
        """
        features = {}
        
        # Extract and validate numeric features
        for key in ["cell_load", "environment", "velocity", "acceleration", "signal_trend"]:
            value = feature_vector.get(key)
            if isinstance(value, (int, float)):
                features[key] = float(value)
            else:
                features[key] = None
                
        return features
    
    def determine_optimal_antenna(self, rf_metrics: Dict[str, Dict[str, float]]) -> str:
        """Determine the optimal antenna based on RF metrics.
        
        Uses a simple heuristic: highest RSRP, with SINR as tiebreaker.
        
        Args:
            rf_metrics: RF metrics per antenna
            
        Returns:
            ID of the optimal antenna
        """
        if not rf_metrics:
            return "antenna_1"  # Default fallback
            
        best_antenna = None
        best_rsrp = float("-inf")
        best_sinr = float("-inf")
        
        for antenna_id, metrics in rf_metrics.items():
            rsrp = metrics.get("rsrp", float("-inf"))
            sinr = metrics.get("sinr", float("-inf"))
            
            if rsrp > best_rsrp or (rsrp == best_rsrp and sinr > best_sinr):
                best_rsrp = rsrp
                best_sinr = sinr
                best_antenna = antenna_id
                
        return best_antenna or "antenna_1"


class HandoverTracker:
    """Tracks handover events and timing for UEs."""
    
    def __init__(self, max_ues: int = 10000, ue_ttl_hours: float = 24.0):
        self.logger = logging.getLogger(__name__)
        
        # Memory-managed tracking dictionaries
        self._prev_cell: UETrackingDict[str] = UETrackingDict(max_ues=max_ues, ue_ttl_hours=ue_ttl_hours)
        self._handover_counts: UETrackingDict[int] = UETrackingDict(max_ues=max_ues, ue_ttl_hours=ue_ttl_hours)
        self._last_handover_ts: UETrackingDict[float] = UETrackingDict(max_ues=max_ues, ue_ttl_hours=ue_ttl_hours)
    
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
        
        # Update current cell
        self._prev_cell[ue_id] = current_cell
        
        # Initialize timestamps for new UEs
        if ue_id not in self._last_handover_ts:
            self._last_handover_ts[ue_id] = timestamp
        
        handover_count = self._handover_counts.get(ue_id, 0)
        time_since_handover = timestamp - self._last_handover_ts.get(ue_id, timestamp)
        
        return handover_count, time_since_handover
    
    def get_stats(self) -> Dict[str, Any]:
        """Get tracking statistics."""
        return {
            "tracked_ues": len(self._prev_cell),
            "total_handovers": sum(self._handover_counts.values()),
            "memory_usage": {
                "prev_cell": self._prev_cell.get_memory_usage(),
                "handover_counts": self._handover_counts.get_memory_usage(),
                "last_handover_ts": self._last_handover_ts.get_memory_usage()
            }
        }


class SignalProcessor:
    """Processes signal quality metrics and trends."""
    
    def __init__(self, signal_window_size: int = 5, max_ues: int = 10000, ue_ttl_hours: float = 24.0):
        self.signal_window_size = signal_window_size
        self.logger = logging.getLogger(__name__)
        
        # Memory-managed tracking dictionaries
        self._prev_signal: UETrackingDict[dict] = UETrackingDict(max_ues=max_ues, ue_ttl_hours=ue_ttl_hours)
        self._signal_buffer: UETrackingDict[dict] = UETrackingDict(max_ues=max_ues, ue_ttl_hours=ue_ttl_hours)
    
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
                "signal_buffer": self._signal_buffer.get_memory_usage()
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