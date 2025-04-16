import sys
import os
import matplotlib.pyplot as plt
from datetime import datetime

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mobility_models.models import LinearMobilityModel

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
    print(f"Generated {len(trajectory)} points")
    print(f"First point: {trajectory[0]}")
    print(f"Last point: {trajectory[-1]}")
    
    # Extract x and y coordinates for plotting
    x_coords = [point['position'][0] for point in trajectory]
    y_coords = [point['position'][1] for point in trajectory]
    
    # Plot trajectory
    plt.figure(figsize=(10, 6))
    plt.plot(x_coords, y_coords, 'b-', linewidth=2)
    plt.plot(x_coords[0], y_coords[0], 'go', markersize=10)  # Start point
    plt.plot(x_coords[-1], y_coords[-1], 'ro', markersize=10)  # End point
    
    plt.xlabel('X position (m)')
    plt.ylabel('Y position (m)')
    plt.title('Linear Mobility Model Trajectory')
    plt.grid(True)
    
    # Save plot
    plt.savefig('linear_trajectory.png')
    print("Plot saved as linear_trajectory.png")
    
    # Show plot if running interactively
    plt.show()
    
    return trajectory

if __name__ == "__main__":
    test_linear_mobility()
