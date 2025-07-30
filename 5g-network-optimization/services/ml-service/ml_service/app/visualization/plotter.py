"""Visualization tools for antenna selection."""
import os
import logging
from datetime import datetime

import matplotlib.pyplot as plt
import numpy as np

from ..models.antenna_selector import DEFAULT_TEST_FEATURES
from ..utils import get_output_dir

logger = logging.getLogger(__name__)


def _get_distance_based_assignment(position, antennas):
    """Assign antenna based on the closest distance."""
    distances = {
        ant_id: np.sqrt((position[0] - pos[0]) ** 2 + (position[1] - pos[1]) ** 2)
        for ant_id, pos in antennas.items()
    }
    return min(distances, key=distances.get)


def plot_antenna_coverage(model, output_dir="output"):
    """
    Visualize antenna selection across a geographic area.

    Args:
        model: Trained AntennaSelector model
        output_dir: Directory to save the visualization
    """
    # Resolve output directory and ensure the "coverage" subfolder exists
    output_dir = get_output_dir(os.path.join(output_dir, "coverage"))

    # Define a grid of positions
    resolution = 50
    x_values = np.linspace(0, 1000, resolution)
    y_values = np.linspace(0, 866, resolution)
    X, Y = np.meshgrid(x_values, y_values)

    # Define antennas (triangle formation)
    antennas = {"antenna_1": (0, 0), "antenna_2": (1000, 0), "antenna_3": (500, 866)}

    # Predict antenna selection for each position
    Z = np.zeros((resolution, resolution), dtype=object)

    # First check if model is trained by making a test prediction
    try:
        model.predict(DEFAULT_TEST_FEATURES)
        model_trained = True
    except Exception as e:
        logger.warning(f"Model not properly trained: {e}")
        logger.info("Will use distance-based assignment instead")
        model_trained = False

    for i in range(resolution):
        for j in range(resolution):
            position = (X[i, j], Y[i, j])

            if model_trained:
                # Use ML model for prediction
                ue_data = {
                    "latitude": X[i, j],
                    "longitude": Y[i, j],
                    "speed": 1.0,  # Fixed for visualization
                    "direction": [1, 0, 0],  # Fixed for visualization
                    "connected_to": "antenna_1",  # Arbitrary initial connection
                    "rf_metrics": {},
                }

                # Add synthetic RF metrics
                for antenna_id, pos in antennas.items():
                    dist = np.sqrt((X[i, j] - pos[0]) ** 2 + (Y[i, j] - pos[1]) ** 2)
                    rsrp = -60 - 20 * np.log10(max(1, dist / 10))
                    sinr = 20 * (1 - dist / 1500)
                    ue_data["rf_metrics"][antenna_id] = {"rsrp": rsrp, "sinr": sinr}

                # Make prediction
                try:
                    features = model.extract_features(ue_data)
                    result = model.predict(features)
                    Z[i, j] = result["antenna_id"]
                except Exception:
                    # Fallback to distance-based assignment
                    Z[i, j] = _get_distance_based_assignment(position, antennas)
            else:
                # Use simple distance-based assignment
                Z[i, j] = _get_distance_based_assignment(position, antennas)

    # Convert to numeric for plotting
    Z_numeric = np.zeros((resolution, resolution))
    for i in range(resolution):
        for j in range(resolution):
            if Z[i, j] == 'antenna_1':
                Z_numeric[i, j] = 1
            elif Z[i, j] == 'antenna_2':
                Z_numeric[i, j] = 2
            elif Z[i, j] == 'antenna_3':
                Z_numeric[i, j] = 3
    
    # Create the plot
    plt.figure(figsize=(12, 10))
    
    # Plot the coverage areas
    plt.contourf(X, Y, Z_numeric, levels=3, alpha=0.6, cmap='viridis')
    
    # Plot antenna locations
    for antenna_id, pos in antennas.items():
        plt.plot(pos[0], pos[1], 'ro', markersize=10)
        plt.text(pos[0] + 20, pos[1] + 20, antenna_id)
    
    plt.xlabel('X Position (m)')
    plt.ylabel('Y Position (m)')
    
    if model_trained:
        plt.title('ML-based Antenna Selection Map')
    else:
        plt.title('Distance-based Antenna Selection Map (Model not trained)')
        
    plt.colorbar(label='Antenna ID')
    
    # Save the plot with absolute path
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = os.path.join(output_dir, f'antenna_coverage_{timestamp}.png')
    plt.savefig(filename)
    plt.close()
    
    # Log the file path for debugging
    logger.info(f"Saved coverage map to: {filename}")
    
    return filename

def plot_movement_trajectory(movement_data, output_dir='output'):
    """
    Visualize UE movement trajectory and antenna handovers.
    
    Args:
        movement_data: List of UE position and antenna data over time
        output_dir: Directory to save the visualization
    """
    # Resolve output directory and ensure the "trajectory" subfolder exists
    output_dir = get_output_dir(os.path.join(output_dir, "trajectory"))
    
    # Extract trajectory data
    positions = [(d['latitude'], d['longitude']) for d in movement_data]
    antennas = [d['connected_to'] for d in movement_data]
    
    # Find unique antennas
    unique_antennas = list(set(antennas))
    color_map = {ant: plt.cm.tab10(i) for i, ant in enumerate(unique_antennas)}
    
    # Create plot
    plt.figure(figsize=(12, 8))
    
    # Plot trajectory segments by antenna
    current_antenna = antennas[0]
    segment_x, segment_y = [], []
    
    for i, ((x, y), antenna) in enumerate(zip(positions, antennas)):
        segment_x.append(x)
        segment_y.append(y)
        
        # If antenna changes or we're at the end, plot this segment
        if antenna != current_antenna or i == len(positions) - 1:
            plt.plot(segment_x, segment_y, '-', color=color_map[current_antenna], 
                     linewidth=2, label=current_antenna if current_antenna not in plt.gca().get_legend_handles_labels()[1] else "")
            # Mark handover point
            if i < len(positions) - 1:
                plt.plot(x, y, 'o', color='red', markersize=8)
            
            # Start new segment
            segment_x, segment_y = [x], [y]
            current_antenna = antenna
    
    # Mark start and end
    plt.plot(positions[0][0], positions[0][1], 'go', markersize=10, label='Start')
    plt.plot(positions[-1][0], positions[-1][1], 'ro', markersize=10, label='End')
    
    plt.xlabel('X Position (m)')
    plt.ylabel('Y Position (m)')
    plt.title('UE Movement Trajectory with Antenna Handovers')
    plt.legend()
    plt.grid(True)
    
    # Save the plot with absolute path
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = os.path.join(output_dir, f'trajectory_{timestamp}.png')
    plt.savefig(filename)
    plt.close()
    
    # Log the file path for debugging
    logger.info(f"Saved trajectory visualization to: {filename}")
    
    return filename
