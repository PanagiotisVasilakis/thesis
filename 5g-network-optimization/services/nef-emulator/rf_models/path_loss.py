"""Path loss models based on 3GPP TR 38.901."""
import math
import numpy as np
from abc import ABC, abstractmethod

class PathLossModel(ABC):
    """Base class for path loss models."""

    @abstractmethod
    def calculate_path_loss(self, distance, frequency, include_shadowing=True):
        """Calculate path loss at given distance and frequency."""
        raise NotImplementedError

class ABGPathLossModel(PathLossModel):
    """
    Alpha-Beta-Gamma (ABG) path loss model from 3GPP TR 38.901.
    
    PL = 10 * alpha * log10(d) + beta + 10 * gamma * log10(f) + X_sigma
    
    Where:
    - d is distance in meters
    - f is frequency in GHz
    - alpha, beta, gamma are model parameters
    - X_sigma is shadow fading (log-normal random variable)
    """
    
    def __init__(self, alpha=3.5, beta=22.4, gamma=2.0, sigma=4.0):
        """
        Initialize ABG path loss model.
        
        Args:
            alpha: Distance-dependent path loss exponent
            beta: Floating intercept in dB
            gamma: Frequency-dependent path loss exponent
            sigma: Shadow fading standard deviation in dB
        """
        super().__init__()
        self.alpha = alpha
        self.beta = beta
        self.gamma = gamma
        self.sigma = sigma
    
    def calculate_path_loss(self, distance, frequency, include_shadowing=True):
        """
        Calculate path loss at given distance and frequency.
        
        Args:
            distance: Distance in meters
            frequency: Frequency in GHz
            include_shadowing: Whether to include shadow fading
            
        Returns:
            Path loss in dB
        """
        # Ensure distance is at least 1 meter
        distance = max(1.0, distance)
        
        # Calculate path loss using ABG model
        pl = 10 * self.alpha * math.log10(distance) + self.beta + 10 * self.gamma * math.log10(frequency)
        
        # Add shadow fading if requested
        if include_shadowing:
            pl += np.random.normal(0, self.sigma)
        
        return pl

class CloseInPathLossModel(PathLossModel):
    """
    Close-In (CI) path loss model from 3GPP TR 38.901.
    
    PL = 32.4 + 10 * n * log10(d) + 20 * log10(f) + X_sigma
    
    Where:
    - d is distance in meters
    - f is frequency in GHz
    - n is the path loss exponent
    - X_sigma is shadow fading (log-normal random variable)
    """
    
    def __init__(self, n=2.0, sigma=4.0):
        """
        Initialize CI path loss model.
        
        Args:
            n: Path loss exponent
            sigma: Shadow fading standard deviation in dB
        """
        super().__init__()
        self.n = n
        self.sigma = sigma
    
    def calculate_path_loss(self, distance, frequency, include_shadowing=True):
        """
        Calculate path loss at given distance and frequency.
        
        Args:
            distance: Distance in meters
            frequency: Frequency in GHz
            include_shadowing: Whether to include shadow fading
            
        Returns:
            Path loss in dB
        """
        # Ensure distance is at least 1 meter
        distance = max(1.0, distance)
        
        # Calculate path loss using CI model
        pl = 32.4 + 10 * self.n * math.log10(distance) + 20 * math.log10(frequency)
        
        # Add shadow fading if requested
        if include_shadowing:
            pl += np.random.normal(0, self.sigma)
        
        return pl

class FastFading:
    """
    Fast fading model based on UE velocity and carrier frequency.
    
    This model simulates Doppler effects and multipath fading.
    """
    
    def __init__(self, carrier_frequency=3.5, doppler_model="Jakes"):
        """
        Initialize fast fading model.
        
        Args:
            carrier_frequency: Carrier frequency in GHz
            doppler_model: Doppler spectrum model ("Jakes" or "Flat")
        """
        self.carrier_frequency = carrier_frequency * 1e9  # Convert to Hz
        self.doppler_model = doppler_model
        self.c = 3e8  # Speed of light in m/s
    
    def calculate_doppler_shift(self, velocity, angle):
        """
        Calculate Doppler shift.
        
        Args:
            velocity: UE velocity in m/s
            angle: Angle between UE movement direction and signal arrival in radians
            
        Returns:
            Doppler shift in Hz
        """
        return velocity * self.carrier_frequency * math.cos(angle) / self.c
    
    def generate_fading(self, velocity, duration, time_step):
        """
        Generate fast fading samples.
        
        Args:
            velocity: UE velocity in m/s
            duration: Duration in seconds
            time_step: Time step in seconds
            
        Returns:
            Array of fading values in dB
        """
        num_samples = int(duration / time_step)
        max_doppler = velocity * self.carrier_frequency / self.c
        
        if self.doppler_model == "Jakes":
            # Simplified Jakes model
            time_points = np.arange(num_samples) * time_step
            phase = 2 * np.pi * max_doppler * time_points
            fading = np.zeros(num_samples)
            
            # Sum contributions from multiple paths
            num_paths = 20
            for i in range(num_paths):
                angle = np.random.uniform(0, 2*np.pi)
                amplitude = np.random.rayleigh(1.0/math.sqrt(num_paths))
                doppler = self.calculate_doppler_shift(velocity, angle)
                fading += amplitude * np.cos(2 * np.pi * doppler * time_points + np.random.uniform(0, 2*np.pi))
            
            # Convert to dB
            fading_db = 20 * np.log10(np.abs(fading))
            
            # Normalize
            fading_db -= np.mean(fading_db)
            
            return fading_db
        else:
            # Flat Doppler spectrum (simplified)
            return np.random.normal(0, 3, num_samples)
