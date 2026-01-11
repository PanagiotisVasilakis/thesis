"""QoS-based prediction bias adjustment.

This module adjusts antenna selection probabilities based on historical
QoS performance. Antennas that have poor QoS track records for a given
service type receive probability penalties.

Production Configuration (via environment variables):
    QOS_BIAS_ENABLED: Enable/disable QoS bias (default: true)
    QOS_BIAS_MIN_SAMPLES: Minimum samples before applying bias (default: 5)
    QOS_BIAS_SUCCESS_THRESHOLD: Success rate threshold (default: 0.9)
    QOS_BIAS_MIN_MULTIPLIER: Minimum probability multiplier (default: 0.35)
"""

import os
import logging
import numpy as np
from typing import Dict, Any, Tuple, Optional

logger = logging.getLogger(__name__)


class QoSBiasManager:
    """Manages QoS-based probability adjustments for antenna selection.
    
    The bias mechanism works by penalizing antennas that have historically
    failed to meet QoS requirements for specific service types. This helps
    the ML model avoid selecting antennas that are unlikely to satisfy
    the UE's service requirements.
    
    Example:
        If antenna_2 has only 60% success rate for URLLC traffic (below the
        90% threshold), its probability is reduced by a factor proportional
        to 60/90 = 0.67, making the model less likely to select it for URLLC.
    """
    
    def __init__(
        self,
        enabled: Optional[bool] = None,
        min_samples: Optional[int] = None,
        success_threshold: Optional[float] = None,
        min_multiplier: Optional[float] = None,
    ):
        """Initialize QoS bias manager.
        
        Args:
            enabled: Enable/disable bias mechanism
            min_samples: Minimum samples required before applying bias
            success_threshold: Success rate below which penalty applies
            min_multiplier: Minimum probability multiplier (floor for penalty)
        """
        self.enabled = enabled if enabled is not None else (
            os.getenv("QOS_BIAS_ENABLED", "1").lower() not in {"0", "false", "no"}
        )
        self.min_samples = min_samples or int(
            os.getenv("QOS_BIAS_MIN_SAMPLES", "5")
        )
        self.success_threshold = success_threshold or float(
            os.getenv("QOS_BIAS_SUCCESS_THRESHOLD", "0.9")
        )
        self.min_multiplier = min_multiplier or float(
            os.getenv("QOS_BIAS_MIN_MULTIPLIER", "0.35")
        )
    
    def apply_bias(
        self,
        probabilities: np.ndarray,
        classes: np.ndarray,
        service_type: Optional[str],
        antenna_profiler: Any,
    ) -> Tuple[np.ndarray, Dict[str, float], bool]:
        """Apply QoS-based bias to prediction probabilities.
        
        Args:
            probabilities: Raw model probabilities for each class
            classes: Antenna IDs corresponding to each probability
            service_type: Service type label (e.g., "urllc", "embb")
            antenna_profiler: AntennaQoSProfiler instance with historical data
        
        Returns:
            Tuple of:
                - adjusted_probabilities: Renormalized probabilities after bias
                - bias_details: Dict mapping antenna_id to multiplier applied
                - bias_applied: Whether any adjustment was made
        """
        if not self.enabled or antenna_profiler is None:
            return probabilities, {}, False
        
        service_label = (service_type or "default").lower()
        adjusted = probabilities.astype(float).copy()
        bias_details: Dict[str, float] = {}
        bias_applied = False
        
        for idx, antenna in enumerate(classes):
            antenna_id = str(antenna)
            profile = antenna_profiler.get_profile(antenna_id, service_label)
            success_rate = profile.get("success_rate")
            sample_count = profile.get("sample_count", 0)
            
            # Skip if insufficient data
            if success_rate is None or sample_count < self.min_samples:
                continue
            
            # Apply penalty if below success threshold
            if success_rate < self.success_threshold:
                penalty = max(
                    self.min_multiplier,
                    success_rate / self.success_threshold,
                )
                adjusted[idx] *= penalty
                bias_details[antenna_id] = float(penalty)
                bias_applied = True
                
                logger.debug(
                    "QoS bias: %s penalized to %.2f for %s (success_rate=%.2f)",
                    antenna_id, penalty, service_label, success_rate
                )
        
        if not bias_applied:
            return probabilities, bias_details, False
        
        # Renormalize probabilities
        total = adjusted.sum()
        if total <= 0:
            return probabilities, bias_details, False
        
        adjusted /= total
        return adjusted, bias_details, True
    
    def get_config(self) -> Dict[str, Any]:
        """Return current configuration for debugging/monitoring."""
        return {
            "enabled": self.enabled,
            "min_samples": self.min_samples,
            "success_threshold": self.success_threshold,
            "min_multiplier": self.min_multiplier,
        }
