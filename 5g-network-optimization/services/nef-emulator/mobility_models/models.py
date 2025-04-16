import numpy as np
import math
from datetime import datetime, timedelta

class MobilityModel:
    """Base class for all mobility models following 3GPP TR 38.901"""
    
    def __init__(self, ue_id, start_time=None, mobility_params=None):
        self.ue_id = ue_id
        self.start_time = start_time or datetime.now()
        self.mobility_params = mobility_params or {}
        self.current_position = None
        self.trajectory = []
    
    def generate_trajectory(self, duration_seconds, time_step=1.0):
        """Generate trajectory points for the specified duration"""
        raise NotImplementedError("Subclasses must implement this method")
    
    def get_position_at_time(self, time):
        """Get interpolated position at specific time"""
        # Implementation for time-based position lookup
        pass


class LinearMobilityModel(MobilityModel):
    """Linear mobility model (3GPP TR 38.901 Section 7.6.3.2)"""
    
    def __init__(self, ue_id, start_position, end_position, speed, start_time=None):
        super().__init__(ue_id, start_time)
        self.start_position = start_position  # (x, y, z) in meters
        self.end_position = end_position  # (x, y, z) in meters
        self.speed = speed  # meters per second
        self.current_position = start_position
    
    def generate_trajectory(self, duration_seconds, time_step=1.0):
        """Generate trajectory points for linear movement"""
        # Calculate direction vector
        dx = self.end_position[0] - self.start_position[0]
        dy = self.end_position[1] - self.start_position[1]
        dz = self.end_position[2] - self.start_position[2]
        
        # Calculate total distance
        distance = math.sqrt(dx**2 + dy**2 + dz**2)
        
        # Normalize direction vector
        if distance > 0:
            dx, dy, dz = dx/distance, dy/distance, dz/distance
        
        # Generate trajectory points
        self.trajectory = []
        current_time = self.start_time
        
        for t in np.arange(0, min(duration_seconds, distance/self.speed), time_step):
            d = min(t * self.speed, distance)
            x = self.start_position[0] + dx * d
            y = self.start_position[1] + dy * d
            z = self.start_position[2] + dz * d
            
            self.trajectory.append({
                'ue_id': self.ue_id,
                'timestamp': current_time + timedelta(seconds=t),
                'position': (x, y, z),
                'speed': self.speed,
                'direction': (dx, dy, dz)
            })
        
        return self.trajectory
