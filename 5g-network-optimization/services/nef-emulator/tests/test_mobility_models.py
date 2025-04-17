# Save this as tests/test_mobility_models.py

import sys
import os
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import mobility models
from mobility_models.models import (
    LinearMobilityModel,
    LShapedMobilityModel,
    RandomWaypointModel,
    UrbanGridMobilityModel,
    GroupMobilityModel
)

def plot_trajectory(model, duration=300, time_step=1.0, filename=None):
    """Generate and plot a trajectory."""
    # Generate trajectory
    trajectory = model.generate_trajectory(duration, time_step)
    
    # Extract coordinates
    positions = [point['position'] for point in trajectory]
    x_coords = [pos[0] for pos in positions]
    y_coords = [pos[1] for pos in positions]
    
    # Plot
    plt.figure(figsize=(10, 8))
    plt.plot(x_coords, y_coords, 'b-', linewidth=1.5)
    plt.plot(x_coords[0], y_coords[0], 'go', markersize=8, label='Start')
    plt.plot(x_coords[-1], y_coords[-1], 'ro', markersize=8, label='End')
    
    # Add direction arrows every 30 points
    for i in range(0, len(trajectory), 30):
        if i < len(trajectory) - 1:
            plt.arrow(x_coords[i], y_coords[i], 
                     (x_coords[i+1] - x_coords[i])*5, 
                     (y_coords[i+1] - y_coords[i])*5, 
                     head_width=20, head_length=20, fc='k', ec='k')
    
    plt.grid(True)
    plt.xlabel('X Position (m)')
    plt.ylabel('Y Position (m)')
    plt.title(f'{model.__class__.__name__} Trajectory')
    plt.legend()
    
    # Save or show
    if filename:
        plt.savefig(filename)
        print(f"Plot saved as {filename}")
    else:
        plt.show()
    
    plt.close()
    
    return trajectory

def test_linear_mobility():
    """Test linear mobility model."""
    print("\nTesting LinearMobilityModel...")
    model = LinearMobilityModel(
        ue_id="test_ue_1",
        start_position=(0, 0, 0),
        end_position=(1000, 500, 0),
        speed=5.0
    )
    
    trajectory = plot_trajectory(model, filename="linear_mobility.png")
    print(f"Generated {len(trajectory)} points")
    
    # Verify start and end positions
    start_pos = trajectory[0]['position']
    end_pos = trajectory[-1]['position']
    
    print(f"Start position: {start_pos}")
    print(f"End position: {end_pos}")
    
    # Verify speed is maintained
    timestamps = [point['timestamp'] for point in trajectory]
    time_diffs = [(timestamps[i+1] - timestamps[i]).total_seconds() 
                 for i in range(len(timestamps)-1)]
    
    positions = [point['position'] for point in trajectory]
    distance_diffs = [((positions[i+1][0] - positions[i][0])**2 + 
                      (positions[i+1][1] - positions[i][1])**2)**0.5 
                     for i in range(len(positions)-1)]
    
    speeds = [dist/time for dist, time in zip(distance_diffs, time_diffs)]
    avg_speed = sum(speeds) / len(speeds)
    
    print(f"Average speed: {avg_speed:.2f} m/s (expected: {model.speed:.2f} m/s)")
    
    return abs(avg_speed - model.speed) < 0.1  # Should be close to specified speed

def test_l_shaped_mobility():
    """Test L-shaped mobility model."""
    print("\nTesting LShapedMobilityModel...")
    model = LShapedMobilityModel(
        ue_id="test_ue_2",
        start_position=(0, 0, 0),
        corner_position=(500, 0, 0),
        end_position=(500, 500, 0),
        speed=5.0
    )
    
    trajectory = plot_trajectory(model, filename="l_shaped_mobility.png")
    print(f"Generated {len(trajectory)} points")
    
    # Verify corner point is in the trajectory
    positions = [point['position'] for point in trajectory]
    distances_to_corner = [((pos[0] - model.corner_position[0])**2 + 
                          (pos[1] - model.corner_position[1])**2)**0.5 
                         for pos in positions]
    
    min_distance = min(distances_to_corner)
    print(f"Minimum distance to corner: {min_distance:.2f} m")
    
    return min_distance < 10.0  # Should pass close to the corner

def test_random_waypoint_mobility():
    """Test random waypoint mobility model."""
    print("\nTesting RandomWaypointModel...")
    model = RandomWaypointModel(
        ue_id="test_ue_3",
        area_size=(1000, 1000, 0),
        min_speed=1.0,
        max_speed=10.0,
        pause_time=5.0
    )
    
    trajectory = plot_trajectory(model, duration=600, filename="random_waypoint_mobility.png")
    print(f"Generated {len(trajectory)} points")
    
    # Verify speed ranges
    speeds = [point['speed'] for point in trajectory if point['speed'] > 0]
    min_speed = min(speeds)
    max_speed = max(speeds)
    
    print(f"Speed range: {min_speed:.2f} m/s to {max_speed:.2f} m/s")
    
    return (min_speed >= model.min_speed - 0.1 and 
            max_speed <= model.max_speed + 0.1)

def test_urban_grid_mobility():
    """Test urban grid mobility model."""
    print("\nTesting UrbanGridMobilityModel...")
    model = UrbanGridMobilityModel(
        ue_id="test_ue_4",
        grid_size=(1000, 1000),
        block_size=(100, 100),
        speed=5.0
    )
    
    trajectory = plot_trajectory(model, duration=600, filename="urban_grid_mobility.png")
    print(f"Generated {len(trajectory)} points")
    
    # Verify movement follows grid pattern
    positions = [point['position'] for point in trajectory]
    
    # Function to check if a point is near a grid line
    def is_on_grid(pos, block_size):
        x_on_grid = abs(pos[0] % block_size[0]) < 5 or abs(pos[0] % block_size[0] - block_size[0]) < 5
        y_on_grid = abs(pos[1] % block_size[1]) < 5 or abs(pos[1] % block_size[1] - block_size[1]) < 5
        return x_on_grid or y_on_grid
    
    grid_points = [is_on_grid(pos, model.block_size) for pos in positions]
    grid_percentage = sum(grid_points) / len(grid_points)
    
    print(f"Percentage of points on grid: {grid_percentage:.2%}")
    
    return grid_percentage > 0.90  # At least 90% of points should be on grid

def test_group_mobility():
    """Test group mobility model."""
    print("\nTesting GroupMobilityModel...")
    
    # Create a reference model for the group center
    reference_model = LinearMobilityModel(
        ue_id="group_center",
        start_position=(0, 0, 0),
        end_position=(1000, 500, 0),
        speed=5.0
    )
    
    model = GroupMobilityModel(
        ue_id="test_ue_5",
        reference_model=reference_model,
        max_distance=100.0,
        speed_factor=0.8
    )
    
    trajectory = plot_trajectory(model, duration=300, filename="group_mobility.png")
    print(f"Generated {len(trajectory)} points")
    
    # Generate reference trajectory for comparison
    ref_trajectory = reference_model.generate_trajectory(300, 1.0)
    
    # Calculate distances to reference at each point
    distances = []
    for i in range(len(trajectory)):
        if i < len(ref_trajectory):
            pos = trajectory[i]['position']
            ref_pos = ref_trajectory[i]['position']
            distance = ((pos[0] - ref_pos[0])**2 + 
                        (pos[1] - ref_pos[1])**2)**0.5
            distances.append(distance)
    
    max_distance = max(distances)
    avg_distance = sum(distances) / len(distances)
    
    print(f"Maximum distance from reference: {max_distance:.2f} m")
    print(f"Average distance from reference: {avg_distance:.2f} m")
    
    # Plot both trajectories
    plt.figure(figsize=(10, 8))
    
    ref_positions = [point['position'] for point in ref_trajectory]
    ref_x_coords = [pos[0] for pos in ref_positions]
    ref_y_coords = [pos[1] for pos in ref_positions]
    
    positions = [point['position'] for point in trajectory]
    x_coords = [pos[0] for pos in positions]
    y_coords = [pos[1] for pos in positions]
    
    plt.plot(ref_x_coords, ref_y_coords, 'r-', linewidth=1.5, label='Reference')
    plt.plot(x_coords, y_coords, 'b-', linewidth=1.5, label='UE')
    
    plt.grid(True)
    plt.xlabel('X Position (m)')
    plt.ylabel('Y Position (m)')
    plt.title('Group Mobility Comparison')
    plt.legend()
    
    plt.savefig("group_mobility_comparison.png")
    plt.close()
    
    return max_distance <= model.max_distance

if __name__ == "__main__":
    print("Testing Mobility Models...")
    
    results = []
    results.append(("Linear Mobility", test_linear_mobility()))
    results.append(("L-Shaped Mobility", test_l_shaped_mobility()))
    results.append(("Random Waypoint Mobility", test_random_waypoint_mobility()))
    results.append(("Urban Grid Mobility", test_urban_grid_mobility()))
    results.append(("Group Mobility", test_group_mobility()))
    
    print("\nSummary of Results:")
    for test_name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status} - {test_name}")