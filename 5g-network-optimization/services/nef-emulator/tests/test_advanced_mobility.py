# File: tests/test_advanced_mobility.py

"""Test script for advanced mobility models."""
import sys
import os
import matplotlib.pyplot as plt
import numpy as np

# Add the root directory to the path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mobility_models.models import (
    LinearMobilityModel,
    LShapedMobilityModel,
    RandomDirectionalMobilityModel,
    UrbanGridMobilityModel,
    GroupMobilityModel
)

def test_all_models():
    """Test all mobility models and visualize their trajectories."""
    # Create output directory
    os.makedirs('test_output', exist_ok=True)
    
    # Test LinearMobilityModel
    print("Testing LinearMobilityModel...")
    linear_model = LinearMobilityModel(
        ue_id="test_linear",
        start_position=(0, 0, 0),
        end_position=(1000, 500, 0),
        speed=10.0
    )
    linear_trajectory = linear_model.generate_trajectory(120, time_step=1.0)
    
    # Test LShapedMobilityModel
    print("Testing LShapedMobilityModel...")
    l_shaped_model = LShapedMobilityModel(
        ue_id="test_l_shaped",
        start_position=(0, 0, 0),
        corner_position=(500, 0, 0),
        end_position=(500, 500, 0),
        speed=10.0
    )
    l_shaped_trajectory = l_shaped_model.generate_trajectory(120, time_step=1.0)
    
    # Test RandomDirectionalMobilityModel
    print("Testing RandomDirectionalMobilityModel...")
    random_model = RandomDirectionalMobilityModel(
        ue_id="test_random",
        start_position=(500, 500, 0),
        speed=10.0,
        area_bounds=[(0, 1000), (0, 1000), (0, 0)],
        direction_change_mean=20.0
    )
    random_trajectory = random_model.generate_trajectory(120, time_step=1.0)
    
    # Test UrbanGridMobilityModel
    print("Testing UrbanGridMobilityModel...")
    urban_model = UrbanGridMobilityModel(
        ue_id="test_urban",
        start_position=(50, 50, 0),
        speed=10.0,
        grid_size=100.0,
        turn_probability=0.3
    )
    urban_trajectory = urban_model.generate_trajectory(120, time_step=1.0)
    
    # Test GroupMobilityModel
    print("Testing GroupMobilityModel...")
    # Use the linear model as reference
    group_model = GroupMobilityModel(
        ue_id="test_group",
        reference_model=linear_model,
        relative_position=(50, 50, 0),
        max_deviation=20.0
    )
    group_trajectory = group_model.generate_trajectory(120, time_step=1.0)
    
    # Create visualization
    plt.figure(figsize=(12, 10))
    
    # Plot each trajectory with different color
    models = [
        (linear_trajectory, "Linear", "b"),
        (l_shaped_trajectory, "L-shaped", "g"),
        (random_trajectory, "Random", "r"),
        (urban_trajectory, "Urban Grid", "m"),
        (group_trajectory, "Group", "c")
    ]
    
    for trajectory, label, color in models:
        x = [point['position'][0] for point in trajectory]
        y = [point['position'][1] for point in trajectory]
        plt.plot(x, y, color=color, label=label)
        plt.plot(x[0], y[0], color + 'o', markersize=8)
        plt.plot(x[-1], y[-1], color + 's', markersize=8)
    
    plt.xlabel("X position")
    plt.ylabel("Y position")
    plt.title("Mobility Model Trajectories")
    plt.legend()
    plt.grid(True)
    
    # Save visualization
    plt.savefig("test_output/mobility_models.png")
    print("Visualization saved to test_output/mobility_models.png")
    
    return True

if __name__ == "__main__":
    success = test_all_models()
    if success:
        print("All mobility models tested successfully!")
    else:
        print("Test failed!")