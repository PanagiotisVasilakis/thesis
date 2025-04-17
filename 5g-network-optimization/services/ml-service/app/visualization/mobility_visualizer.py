# File: visualization/mobility_visualizer.py

import os
import numpy as np
import matplotlib.pyplot as plt
from typing import List, Dict, Any, Tuple, Optional

def visualize_mobility_pattern(
    points: List[Dict[str, Any]],
    output_file: str = "mobility_pattern.png",
    title: str = "Mobility Pattern",
    show_grid: bool = True,
    color: str = "blue",
    figsize: Tuple[int, int] = (10, 8)
) -> str:
    """
    Visualize a mobility pattern from path points.
    
    Args:
        points: List of path points with latitude and longitude
        output_file: Output file path
        title: Plot title
        show_grid: Whether to show grid lines
        color: Line color
        figsize: Figure size (width, height) in inches
        
    Returns:
        Path to the output file
    """
    # Extract coordinates
    latitudes = [point.get("latitude", 0) for point in points]
    longitudes = [point.get("longitude", 0) for point in points]
    
    # Create figure
    plt.figure(figsize=figsize)
    
    # Plot trajectory
    plt.plot(latitudes, longitudes, f"{color}-", linewidth=2)
    
    # Mark start and end points
    if points:
        plt.plot(latitudes[0], longitudes[0], "go", markersize=10, label="Start")
        plt.plot(latitudes[-1], longitudes[-1], "ro", markersize=10, label="End")
    
    # Add labels and title
    plt.xlabel("X position (latitude)")
    plt.ylabel("Y position (longitude)")
    plt.title(title)
    plt.legend()
    
    if show_grid:
        plt.grid(True)
    
    # Save figure
    os.makedirs(os.path.dirname(os.path.abspath(output_file)) or '.', exist_ok=True)
    plt.savefig(output_file)
    plt.close()
    
    return output_file

def visualize_multiple_patterns(
    pattern_list: List[Tuple[List[Dict[str, Any]], str, str]],
    output_file: str = "mobility_patterns.png",
    title: str = "Mobility Patterns Comparison",
    show_grid: bool = True,
    figsize: Tuple[int, int] = (12, 10)
) -> str:
    """
    Visualize multiple mobility patterns for comparison.
    
    Args:
        pattern_list: List of (points, label, color) tuples
        output_file: Output file path
        title: Plot title
        show_grid: Whether to show grid lines
        figsize: Figure size (width, height) in inches
        
    Returns:
        Path to the output file
    """
    # Create figure
    plt.figure(figsize=figsize)
    
    # Plot each pattern
    for points, label, color in pattern_list:
        latitudes = [point.get("latitude", 0) for point in points]
        longitudes = [point.get("longitude", 0) for point in points]
        
        plt.plot(latitudes, longitudes, f"{color}-", linewidth=2, label=label)
        
        # Mark start and end points
        if points:
            plt.plot(latitudes[0], longitudes[0], f"{color}o", markersize=8)
            plt.plot(latitudes[-1], longitudes[-1], f"{color}s", markersize=8)
    
    # Add labels and title
    plt.xlabel("X position (latitude)")
    plt.ylabel("Y position (longitude)")
    plt.title(title)
    plt.legend()
    
    if show_grid:
        plt.grid(True)
    
    # Save figure
    os.makedirs(os.path.dirname(os.path.abspath(output_file)) or '.', exist_ok=True)
    plt.savefig(output_file)
    plt.close()
    
    return output_file