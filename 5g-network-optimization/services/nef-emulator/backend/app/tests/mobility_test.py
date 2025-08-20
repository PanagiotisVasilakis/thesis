"""Basic test for mobility models."""
import sys
import os
import matplotlib.pyplot as plt
from datetime import datetime
import logging
import shutil

# Add parent directory to path to find our mobility_models package
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger(__name__)

# Create the mobility models module if it doesn't exist
if not os.path.exists(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'mobility_models')):
    os.makedirs(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'mobility_models'))
    with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'mobility_models', '__init__.py'), 'w') as f:
        f.write('# Mobility Models package\n')

# Define a simple Linear Mobility Model
class MobilityModel:
    def __init__(self, ue_id, start_time=None):
        self.ue_id = ue_id
        self.start_time = start_time or datetime.now()
        self.trajectory = []
        
class LinearMobilityModel(MobilityModel):
    def __init__(self, ue_id, start_position, end_position, speed, start_time=None):
        super().__init__(ue_id, start_time)
        self.start_position = start_position
        self.end_position = end_position
        self.speed = speed
        
    def generate_trajectory(self, duration_seconds, time_step=1.0):
        import math
        
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
        
        for t in range(0, min(int(duration_seconds), int(distance/self.speed))+1, int(time_step)):
            d = min(t * self.speed, distance)
            x = self.start_position[0] + dx * d
            y = self.start_position[1] + dy * d
            z = self.start_position[2] + dz * d
            
            self.trajectory.append({
                'ue_id': self.ue_id,
                'timestamp': current_time,
                'position': (x, y, z),
                'speed': self.speed,
                'direction': (dx, dy, dz)
            })
            
        return self.trajectory

def test_linear_mobility():
    """Test linear mobility model and visualize trajectory"""
    
    # Create model
    ue_id = "test_ue_1"
    start_position = (0, 0, 0)
    end_position = (1000, 500, 0)
    speed = 10  # m/s
    
    model = LinearMobilityModel(ue_id, start_position, end_position, speed)
    
    # Generate trajectory for 2 minutes
    trajectory = model.generate_trajectory(120, time_step=1.0)
    
    # Print some information
    logger.info(f"Generated {len(trajectory)} points")
    logger.info(f"First point: {trajectory[0]['position']}")
    logger.info(f"Last point: {trajectory[-1]['position']}")
    
    # Extract x and y coordinates for plotting
    x_coords = [point['position'][0] for point in trajectory]
    y_coords = [point['position'][1] for point in trajectory]
    
    try:
        # Plot trajectory
        plt.figure(figsize=(10, 6))
        plt.plot(x_coords, y_coords, 'b-', linewidth=2)
        plt.plot(x_coords[0], y_coords[0], 'go', markersize=10)  # Start point
        plt.plot(x_coords[-1], y_coords[-1], 'ro', markersize=10)  # End point

        plt.xlabel('X position (m)')
        plt.ylabel('Y position (m)')
        plt.title('Linear Mobility Model Trajectory')
        plt.grid(True)

        # Save plot inside output/mobility
        out_dir = os.path.join('output', 'mobility')
        os.makedirs(out_dir, exist_ok=True)
        filepath = os.path.join(out_dir, 'linear_trajectory.png')
        plt.savefig(filepath)
        logger.info(f"Plot saved as {filepath}")
    except Exception as e:
        logger.error(f"Could not create plot: {e}")
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)

    assert len(trajectory) > 0
