"""Antenna radiation patterns based on 3GPP specifications."""
import numpy as np
import math
from abc import ABC, abstractmethod

class AntennaPattern(ABC):
    """Base class for antenna radiation patterns."""

    @abstractmethod
    def calculate_gain(self, azimuth, elevation):
        """Calculate antenna gain in given direction."""
        raise NotImplementedError

class IsotropicPattern(AntennaPattern):
    """
    Isotropic antenna pattern (equal gain in all directions).
    
    This is a simplified model used as a baseline.
    """
    
    def __init__(self, gain_dbi=0.0):
        """
        Initialize isotropic antenna pattern.
        
        Args:
            gain_dbi: Antenna gain in dBi
        """
        super().__init__()
        self.gain_dbi = gain_dbi
    
    def calculate_gain(self, azimuth, elevation):
        """
        Calculate antenna gain in given direction.
        
        Args:
            azimuth: Azimuth angle in degrees
            elevation: Elevation angle in degrees
            
        Returns:
            Antenna gain in dBi
        """
        return self.gain_dbi

class ThreeGPPSectorPattern(AntennaPattern):
    """
    3GPP sector antenna pattern from TR 38.901.
    
    This model combines horizontal and vertical radiation patterns.
    """
    
    def __init__(self, max_gain_dbi=17.0, horizontal_beamwidth=65.0, 
                 vertical_beamwidth=7.5, electrical_downtilt=10.0,
                 front_to_back_ratio=30.0):
        """
        Initialize 3GPP sector antenna pattern.
        
        Args:
            max_gain_dbi: Maximum antenna gain in dBi
            horizontal_beamwidth: Horizontal 3 dB beamwidth in degrees
            vertical_beamwidth: Vertical 3 dB beamwidth in degrees
            electrical_downtilt: Electrical downtilt in degrees
            front_to_back_ratio: Front-to-back ratio in dB
        """
        super().__init__()
        self.max_gain_dbi = max_gain_dbi
        self.horizontal_beamwidth = horizontal_beamwidth
        self.vertical_beamwidth = vertical_beamwidth
        self.electrical_downtilt = electrical_downtilt
        self.front_to_back_ratio = front_to_back_ratio
    
    def calculate_horizontal_pattern(self, azimuth):
        """
        Calculate horizontal antenna pattern.
        
        Args:
            azimuth: Azimuth angle in degrees
            
        Returns:
            Horizontal pattern attenuation in dB
        """
        # Normalize azimuth to range [-180, 180]
        azimuth = ((azimuth + 180) % 360) - 180
        
        # Calculate attenuation using 3GPP formula
        angle_ratio = 2 * azimuth / self.horizontal_beamwidth
        attenuation = -min(12 * angle_ratio**2, self.front_to_back_ratio)
        
        return attenuation
    
    def calculate_vertical_pattern(self, elevation):
        """
        Calculate vertical antenna pattern.
        
        Args:
            elevation: Elevation angle in degrees
            
        Returns:
            Vertical pattern attenuation in dB
        """
        # Calculate effective elevation angle (including downtilt)
        effective_elevation = elevation - self.electrical_downtilt
        
        # Calculate attenuation using 3GPP formula
        angle_ratio = 2 * effective_elevation / self.vertical_beamwidth
        attenuation = -min(12 * angle_ratio**2, self.front_to_back_ratio)
        
        return attenuation
    
    def calculate_gain(self, azimuth, elevation):
        """
        Calculate antenna gain in given direction.
        
        Args:
            azimuth: Azimuth angle in degrees
            elevation: Elevation angle in degrees
            
        Returns:
            Antenna gain in dBi
        """
        # Calculate horizontal and vertical attenuations
        horizontal_attenuation = self.calculate_horizontal_pattern(azimuth)
        vertical_attenuation = self.calculate_vertical_pattern(elevation)
        
        # Combine attenuations (3GPP method)
        total_attenuation = -min(-(horizontal_attenuation + vertical_attenuation), self.front_to_back_ratio)
        
        # Calculate total gain
        gain = self.max_gain_dbi + total_attenuation
        
        return gain

class MassiveMIMOPattern(AntennaPattern):
    """
    Massive MIMO antenna pattern with beamforming capabilities.
    
    This model simulates an antenna array with beamforming towards a specific direction.
    """
    
    def __init__(self, num_elements_horizontal=8, num_elements_vertical=8, 
                 element_spacing=0.5, carrier_frequency=3.5,
                 max_gain_dbi=25.0):
        """
        Initialize massive MIMO antenna pattern.
        
        Args:
            num_elements_horizontal: Number of antenna elements in horizontal dimension
            num_elements_vertical: Number of antenna elements in vertical dimension
            element_spacing: Spacing between elements in wavelengths
            carrier_frequency: Carrier frequency in GHz
            max_gain_dbi: Maximum antenna gain in dBi
        """
        super().__init__()
        self.num_elements_horizontal = num_elements_horizontal
        self.num_elements_vertical = num_elements_vertical
        self.element_spacing = element_spacing
        self.carrier_frequency = carrier_frequency * 1e9  # Convert to Hz
        self.max_gain_dbi = max_gain_dbi
        self.c = 3e8  # Speed of light in m/s
        self.wavelength = self.c / self.carrier_frequency
        
        # Initialize to boresight
        self.steering_azimuth = 0.0
        self.steering_elevation = 0.0
    
    def set_steering_direction(self, azimuth, elevation):
        """
        Set the steering direction for beamforming.
        
        Args:
            azimuth: Azimuth angle in degrees
            elevation: Elevation angle in degrees
        """
        self.steering_azimuth = azimuth
        self.steering_elevation = elevation
    
    def calculate_array_factor(self, azimuth, elevation):
        """
        Calculate array factor for the antenna array.
        
        Args:
            azimuth: Azimuth angle in degrees
            elevation: Elevation angle in degrees
            
        Returns:
            Array factor gain in linear scale
        """
        # Convert angles to radians
        azimuth_rad = np.deg2rad(azimuth)
        elevation_rad = np.deg2rad(elevation)
        steering_azimuth_rad = np.deg2rad(self.steering_azimuth)
        steering_elevation_rad = np.deg2rad(self.steering_elevation)
        
        # Calculate phase differences
        dx = self.element_spacing * self.wavelength * (np.sin(elevation_rad) * np.cos(azimuth_rad) - 
                                                     np.sin(steering_elevation_rad) * np.cos(steering_azimuth_rad))
        dy = self.element_spacing * self.wavelength * (np.sin(elevation_rad) * np.sin(azimuth_rad) - 
                                                     np.sin(steering_elevation_rad) * np.sin(steering_azimuth_rad))
        
        # Calculate array factors
        if self.num_elements_horizontal > 1:
            array_factor_h = np.abs(np.sin(self.num_elements_horizontal * np.pi * dx / self.wavelength) / 
                                  (self.num_elements_horizontal * np.sin(np.pi * dx / self.wavelength) + 1e-10))
        else:
            array_factor_h = 1.0
            
        if self.num_elements_vertical > 1:
            array_factor_v = np.abs(np.sin(self.num_elements_vertical * np.pi * dy / self.wavelength) / 
                                  (self.num_elements_vertical * np.sin(np.pi * dy / self.wavelength) + 1e-10))
        else:
            array_factor_v = 1.0
        
        # Combined array factor
        array_factor = array_factor_h * array_factor_v
        
        return array_factor**2  # Power gain
    
    def calculate_gain(self, azimuth, elevation):
        """
        Calculate antenna gain in given direction.
        
        Args:
            azimuth: Azimuth angle in degrees
            elevation: Elevation angle in degrees
            
        Returns:
            Antenna gain in dBi
        """
        # Calculate array factor
        array_factor = self.calculate_array_factor(azimuth, elevation)
        
        # Calculate gain in dBi
        gain_dbi = self.max_gain_dbi + 10 * np.log10(array_factor + 1e-10)
        
        # Limit minimum gain
        gain_dbi = max(gain_dbi, self.max_gain_dbi - 30)
        
        return gain_dbi
