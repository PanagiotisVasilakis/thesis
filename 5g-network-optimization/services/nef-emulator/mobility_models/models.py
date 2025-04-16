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

class LShapedMobilityModel(MobilityModel):
    """L-shaped mobility model with a 90-degree turn (3GPP TR 38.901)"""
    
    def __init__(self, ue_id, start_position, corner_position, end_position, speed, start_time=None):
        super().__init__(ue_id, start_time)
        self.start_position = start_position  # (x, y, z) in meters
        self.corner_position = corner_position  # (x, y, z) in meters
        self.end_position = end_position  # (x, y, z) in meters
        self.speed = speed  # meters per second
        self.current_position = start_position
    
    def generate_trajectory(self, duration_seconds, time_step=1.0):
        """Generate trajectory for L-shaped movement with 90-degree turn"""
        # Create linear models for each segment
        first_segment = LinearMobilityModel(
            self.ue_id, 
            self.start_position, 
            self.corner_position, 
            self.speed, 
            self.start_time
        )
        
        # Calculate when we reach the corner
        dx1 = self.corner_position[0] - self.start_position[0]
        dy1 = self.corner_position[1] - self.start_position[1]
        dz1 = self.corner_position[2] - self.start_position[2]
        segment1_distance = math.sqrt(dx1**2 + dy1**2 + dz1**2)
        segment1_time = segment1_distance / self.speed
        
        # Start time for second segment
        second_segment_start_time = self.start_time + timedelta(seconds=segment1_time)
        
        second_segment = LinearMobilityModel(
            self.ue_id, 
            self.corner_position, 
            self.end_position, 
            self.speed, 
            second_segment_start_time
        )
        
        # Generate trajectories for both segments
        first_traj = first_segment.generate_trajectory(segment1_time, time_step)
        
        # Remaining time for second segment
        remaining_time = max(0, duration_seconds - segment1_time)
        second_traj = []
        if remaining_time > 0:
            second_traj = second_segment.generate_trajectory(remaining_time, time_step)
            # Skip the first point as it's the same as the last point of first segment
            second_traj = second_traj[1:] if second_traj else []
        
        # Combine trajectories
        self.trajectory = first_traj + second_traj
        
        return self.trajectory
