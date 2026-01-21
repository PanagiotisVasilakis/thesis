"""Enhanced channel model with proper AR1 shadowing and Doppler handling.

This module implements Fixes #3, #24, and #25 from the thesis implementation plan:

Fix #3: RSRP Component Sign Convention
- Path loss: Always POSITIVE (subtracted from TX power)
- Shadowing: Can be POSITIVE or NEGATIVE (deviation from mean)
- Fading: Expressed as loss, mean-compensated to 0 dB

Fix #24: Doppler Division by Zero Protection
- Minimum velocity threshold (0.1 m/s)
- Stationary UEs get large coherence time (10 seconds)
- Prevents division by zero in Doppler calculations

Fix #25: Shadowing Initial Seeding
- First shadowing value drawn from target distribution N(0, σ_SF)
- Avoids zero-initialization bias
- AR1 process maintains spatial correlation

Usage:
    from rf_models.channel_model import ChannelModel
    
    # Create channel model for a UE
    channel = ChannelModel(
        ue_id="ue001",
        carrier_frequency_ghz=3.5,
        sigma_sf=4.0,
        decorr_distance_m=37.0
    )
    
    # Update channel state based on UE movement
    channel.update(position=(100, 200, 1.5), velocity_mps=33.3)
    
    # Get total signal loss (path_loss + shadowing + fading)
    total_loss = channel.get_total_loss(distance_m=500)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# Constants from the thesis implementation plan
MIN_VELOCITY_THRESHOLD_MPS = 0.1  # 0.36 km/h - slower than walking
STATIONARY_COHERENCE_TIME_S = 10.0  # Large coherence time for stationary UEs
SPEED_OF_LIGHT_MPS = 3e8

# Numerical stability constant
EPSILON = 1e-10

# Rayleigh fading mean compensation (exact value from Euler-Mascheroni constant)
# E[-10*log10(|h|²)] for unit-variance Rayleigh = 10 * γ / ln(10)
# where γ ≈ 0.5772156649 (Euler-Mascheroni constant)
# Exact value: 10 * 0.5772156649 / ln(10) ≈ 2.5066 dB
RAYLEIGH_MEAN_COMPENSATION_DB = 2.5066


@dataclass
class ChannelState:
    """State container for a UE's channel model.
    
    Tracks shadowing and fading state across time for AR1 correlation.
    """
    # Current shadowing value in dB
    shadowing_db: float = 0.0
    
    # Last known position for distance-based correlation
    last_position: Optional[Tuple[float, float, float]] = None
    
    # Current fading coefficient (complex amplitude)
    fading_coefficient: complex = 1.0 + 0j
    
    # Time of last fading update
    last_fading_update_time: float = 0.0
    
    # Coherence time for current velocity
    coherence_time_s: float = STATIONARY_COHERENCE_TIME_S
    
    # Flag indicating if this is the first update
    is_initialized: bool = False


class ChannelModel:
    """Enhanced channel model with AR1 shadowing and Doppler-aware fading.
    
    This model implements:
    1. AR1 (first-order autoregressive) spatially-correlated shadowing
    2. Rayleigh fading with Doppler-based coherence time
    3. Proper handling of stationary UEs
    4. Per-UE RNG for reproducibility
    
    The model maintains state across updates to provide realistic
    temporal and spatial correlation in the channel.
    """
    
    def __init__(
        self,
        ue_id: str,
        carrier_frequency_ghz: float = 3.5,
        sigma_sf: float = 4.0,
        decorr_distance_m: float = 37.0,
        rng: Optional[np.random.RandomState] = None,
    ):
        """Initialize channel model for a specific UE.
        
        Args:
            ue_id: Unique identifier for the UE
            carrier_frequency_ghz: Carrier frequency in GHz
            sigma_sf: Shadow fading standard deviation in dB
            decorr_distance_m: Decorrelation distance for shadowing in meters
            rng: Optional RandomState for reproducibility. If None, creates one
                 using the reproducibility module.
        """
        self.ue_id = ue_id
        self.carrier_frequency_hz = carrier_frequency_ghz * 1e9
        self.sigma_sf = sigma_sf
        self.decorr_distance_m = decorr_distance_m
        
        # Initialize RNG (Fix #1 integration)
        # Try multiple import paths for flexibility
        if rng is None:
            rng_initialized = False
            
            # Try app.core path (within nef-emulator service)
            try:
                from app.core.reproducibility import get_rng_for_ue
                self.rng = get_rng_for_ue(ue_id)
                rng_initialized = True
            except ImportError:
                pass
            
            # Try app.app.core path (alternate structure)
            if not rng_initialized:
                try:
                    from app.app.core.reproducibility import get_rng_for_ue
                    self.rng = get_rng_for_ue(ue_id)
                    rng_initialized = True
                except ImportError:
                    pass
            
            # Try scripts.core path (for standalone scripts)
            if not rng_initialized:
                try:
                    from scripts.core.reproducibility import get_rng_for_ue
                    self.rng = get_rng_for_ue(ue_id)
                    rng_initialized = True
                except ImportError:
                    pass
            
            # Final fallback
            if not rng_initialized:
                logger.warning(
                    "No reproducibility module found, using unseeded RandomState for UE %s",
                    ue_id
                )
                self.rng = np.random.RandomState()
        else:
            self.rng = rng
        
        # Initialize channel state
        self.state = ChannelState()
        
        logger.debug(
            "ChannelModel initialized for UE %s: fc=%.2f GHz, σ_SF=%.1f dB, d_corr=%.1f m",
            ue_id, carrier_frequency_ghz, sigma_sf, decorr_distance_m
        )
    
    def update_shadowing(
        self,
        current_position: Tuple[float, float, float],
    ) -> float:
        """Update shadowing using AR1 process with spatial correlation.
        
        Implements Fix #25: Proper initial seeding from N(0, σ_SF).
        
        The AR1 shadowing model:
            S_new = ρ × S_old + √(1 - ρ²) × N(0, σ_SF)
        
        where:
            ρ = exp(-d_moved / d_corr)
            d_moved = distance moved since last update
            d_corr = decorrelation distance (37m for urban)
        
        Args:
            current_position: Current UE position (x, y, z) in meters
            
        Returns:
            Updated shadowing value in dB
        """
        # Fix #25: First-call initialization
        if not self.state.is_initialized or self.state.last_position is None:
            # Draw initial shadowing from target distribution N(0, σ_SF)
            initial_shadowing = self.rng.normal(0, self.sigma_sf)
            self.state.shadowing_db = initial_shadowing
            self.state.last_position = current_position
            self.state.is_initialized = True
            
            logger.debug(
                "UE %s: Initial shadowing = %.2f dB (from N(0, %.1f))",
                self.ue_id, initial_shadowing, self.sigma_sf
            )
            return self.state.shadowing_db
        
        # Calculate distance moved
        dx = current_position[0] - self.state.last_position[0]
        dy = current_position[1] - self.state.last_position[1]
        dz = current_position[2] - self.state.last_position[2]
        distance_moved = math.sqrt(dx*dx + dy*dy + dz*dz)
        
        # Calculate correlation coefficient
        # ρ = exp(-d / d_corr)
        rho = math.exp(-distance_moved / self.decorr_distance_m)
        
        # AR1 update: S_new = ρ × S_old + √(1 - ρ²) × N(0, σ_SF)
        innovation_scale = math.sqrt(1 - rho * rho)
        innovation = self.rng.normal(0, self.sigma_sf)
        
        new_shadowing = rho * self.state.shadowing_db + innovation_scale * innovation
        
        # Update state
        self.state.shadowing_db = new_shadowing
        self.state.last_position = current_position
        
        logger.debug(
            "UE %s: Shadowing updated: %.2f dB (moved %.1f m, ρ=%.3f)",
            self.ue_id, new_shadowing, distance_moved, rho
        )
        
        return self.state.shadowing_db
    
    def update_fast_fading(
        self,
        velocity_mps: float,
        current_time_s: float,
    ) -> float:
        """Update fast fading based on UE velocity and elapsed time.
        
        Implements Fix #24: Doppler division by zero protection.
        
        For stationary UEs (v < 0.1 m/s):
        - Coherence time = 10 seconds
        - Fading remains stable (realistic for no movement)
        
        For moving UEs:
        - Coherence time = 9 / (16π × f_d)
        - where f_d = v × f_c / c (max Doppler frequency)
        
        Args:
            velocity_mps: UE velocity in m/s
            current_time_s: Current simulation time in seconds
            
        Returns:
            Fading loss in dB (mean-compensated to ~0 dB)
        """
        # Fix #24: Velocity threshold check
        if velocity_mps < MIN_VELOCITY_THRESHOLD_MPS:
            # Stationary UE - use large coherence time
            self.state.coherence_time_s = STATIONARY_COHERENCE_TIME_S
            
            # Check if we need to regenerate fading
            time_since_update = current_time_s - self.state.last_fading_update_time
            
            if time_since_update >= self.state.coherence_time_s:
                # Generate new Rayleigh fading coefficient
                self._generate_new_fading()
                self.state.last_fading_update_time = current_time_s
                
            logger.debug(
                "UE %s: Stationary, coherence_time=%.1fs, fading unchanged",
                self.ue_id, self.state.coherence_time_s
            )
        else:
            # Moving UE - calculate Doppler-based coherence time
            # Max Doppler frequency: f_d = v × f_c / c
            max_doppler_hz = velocity_mps * self.carrier_frequency_hz / SPEED_OF_LIGHT_MPS
            
            # Coherence time: T_c ≈ 9 / (16π × f_d)
            # This is the time over which channel correlation > 0.5
            self.state.coherence_time_s = 9.0 / (16.0 * math.pi * max_doppler_hz)
            
            # Check if we need to regenerate fading
            time_since_update = current_time_s - self.state.last_fading_update_time
            
            if time_since_update >= self.state.coherence_time_s:
                self._generate_new_fading()
                self.state.last_fading_update_time = current_time_s
                
                logger.debug(
                    "UE %s: Moving at %.1f m/s, coherence_time=%.4fs, fading regenerated",
                    self.ue_id, velocity_mps, self.state.coherence_time_s
                )
        
        return self._calculate_fading_loss_db()
    
    def _calculate_fading_loss_db(self) -> float:
        """Calculate fading loss from current coefficient.
        
        Fix #3: Mean compensation so average fading_loss ≈ 0 dB.
        Uses module-level RAYLEIGH_MEAN_COMPENSATION_DB constant.
        
        Returns:
            Fading loss in dB (mean-compensated to ~0 dB)
        """
        fading_power = abs(self.state.fading_coefficient) ** 2
        fading_loss_db = -10 * math.log10(fading_power + EPSILON)
        return fading_loss_db - RAYLEIGH_MEAN_COMPENSATION_DB
    
    def _generate_new_fading(self) -> None:
        """Generate a new Rayleigh fading coefficient.
        
        Rayleigh fading: h = (X + jY) / √2
        where X, Y ~ N(0, 1) independent
        """
        real_part = self.rng.normal(0, 1)
        imag_part = self.rng.normal(0, 1)
        self.state.fading_coefficient = complex(real_part, imag_part) / math.sqrt(2)
    
    def get_shadowing(self) -> float:
        """Get current shadowing value in dB."""
        return self.state.shadowing_db
    
    def get_fading_loss(self) -> float:
        """Get current fading loss in dB (mean-compensated).
        
        Uses the same calculation as _calculate_fading_loss_db() for consistency.
        """
        return self._calculate_fading_loss_db()
    
    def get_total_channel_loss(
        self,
        path_loss_db: float,
        include_fading: bool = True,
    ) -> float:
        """Get total channel loss including all components.
        
        Implements Fix #3: Proper sign convention.
        
        RSRP = TX_power - path_loss - shadowing - fading_loss
        
        Since this returns LOSS, caller should do:
            RSRP = TX_power - get_total_channel_loss(...)
        
        Args:
            path_loss_db: Path loss in dB (positive number)
            include_fading: Whether to include fast fading
            
        Returns:
            Total loss in dB (positive = weaker signal)
        """
        # Fix #3: Clear sign convention
        # - path_loss: POSITIVE (it's a loss)
        # - shadowing: Can be ± (positive = additional loss)
        # - fading_loss: Mean-compensated, can be ±
        
        total_loss = path_loss_db
        total_loss += self.state.shadowing_db  # shadowing adds to loss
        
        if include_fading:
            total_loss += self.get_fading_loss()
        
        return total_loss
    
    def reset(self) -> None:
        """Reset channel state for a new simulation run."""
        self.state = ChannelState()
        logger.debug("UE %s: Channel model reset", self.ue_id)


class ChannelModelManager:
    """Manager for multiple UE channel models.
    
    Provides a centralized way to create and manage channel models
    for all UEs in a simulation.
    """
    
    def __init__(
        self,
        carrier_frequency_ghz: float = 3.5,
        sigma_sf: float = 4.0,
        decorr_distance_m: float = 37.0,
    ):
        """Initialize channel model manager.
        
        Args:
            carrier_frequency_ghz: Default carrier frequency for all UEs
            sigma_sf: Default shadow fading std dev for all UEs
            decorr_distance_m: Default decorrelation distance for all UEs
        """
        self.carrier_frequency_ghz = carrier_frequency_ghz
        self.sigma_sf = sigma_sf
        self.decorr_distance_m = decorr_distance_m
        
        self._channels: Dict[str, ChannelModel] = {}
        
        logger.info(
            "ChannelModelManager initialized: fc=%.2f GHz, σ_SF=%.1f dB, d_corr=%.1f m",
            carrier_frequency_ghz, sigma_sf, decorr_distance_m
        )
    
    def get_channel(self, ue_id: str) -> ChannelModel:
        """Get or create a channel model for a UE.
        
        Args:
            ue_id: Unique identifier for the UE
            
        Returns:
            ChannelModel instance for this UE
        """
        if ue_id not in self._channels:
            self._channels[ue_id] = ChannelModel(
                ue_id=ue_id,
                carrier_frequency_ghz=self.carrier_frequency_ghz,
                sigma_sf=self.sigma_sf,
                decorr_distance_m=self.decorr_distance_m,
            )
        return self._channels[ue_id]
    
    def update_ue(
        self,
        ue_id: str,
        position: Tuple[float, float, float],
        velocity_mps: float,
        current_time_s: float,
    ) -> Tuple[float, float]:
        """Update channel for a UE and return current shadowing and fading.
        
        Args:
            ue_id: UE identifier
            position: Current position (x, y, z) in meters
            velocity_mps: Current velocity in m/s
            current_time_s: Current simulation time in seconds
            
        Returns:
            Tuple of (shadowing_db, fading_loss_db)
        """
        channel = self.get_channel(ue_id)
        shadowing = channel.update_shadowing(position)
        fading = channel.update_fast_fading(velocity_mps, current_time_s)
        return shadowing, fading
    
    def remove_ue(self, ue_id: str) -> None:
        """Remove a UE's channel model."""
        if ue_id in self._channels:
            del self._channels[ue_id]
            logger.debug("Removed channel model for UE %s", ue_id)
    
    def reset_all(self) -> None:
        """Reset all channel models."""
        for channel in self._channels.values():
            channel.reset()
        logger.info("Reset all %d channel models", len(self._channels))
    
    def clear_all(self) -> None:
        """Clear all channel models."""
        self._channels.clear()
        logger.info("Cleared all channel models")
    
    def get_stats(self) -> Dict[str, object]:
        """Get statistics about channel models."""
        if not self._channels:
            return {"count": 0}
        
        shadowing_values = [c.state.shadowing_db for c in self._channels.values()]
        return {
            "count": len(self._channels),
            "shadowing_mean": np.mean(shadowing_values),
            "shadowing_std": np.std(shadowing_values),
            "shadowing_min": np.min(shadowing_values),
            "shadowing_max": np.max(shadowing_values),
        }
