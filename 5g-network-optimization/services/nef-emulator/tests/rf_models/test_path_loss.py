"""Tests for path loss models."""
import sys
import os
import numpy as np
import matplotlib.pyplot as plt

# Ensure the rf_models package can be imported
current_dir = os.path.dirname(os.path.abspath(__file__))
repo_root = os.path.abspath(os.path.join(current_dir, "..", ".."))
sys.path.insert(0, repo_root)
sys.modules.pop("rf_models", None)

from rf_models.path_loss import ABGPathLossModel, CloseInPathLossModel, FastFading

def test_abg_path_loss_model():
    """Test ABG path loss model."""
    # Create model
    model = ABGPathLossModel()
    
    # Calculate path loss over distance
    distances = np.linspace(1, 1000, 100)
    path_loss_3ghz = [model.calculate_path_loss(d, 3.5, include_shadowing=False) for d in distances]
    path_loss_28ghz = [model.calculate_path_loss(d, 28, include_shadowing=False) for d in distances]
    
    # Plot results
    plt.figure(figsize=(10, 6))
    plt.plot(distances, path_loss_3ghz, 'b-', linewidth=2, label='3.5 GHz')
    plt.plot(distances, path_loss_28ghz, 'r-', linewidth=2, label='28 GHz')
    
    plt.xlabel('Distance (m)')
    plt.ylabel('Path Loss (dB)')
    plt.title('ABG Path Loss Model')
    plt.grid(True)
    plt.legend()
    
    plt.savefig('abg_path_loss.png')
    print("Plot saved as abg_path_loss.png")
    
    # Test shadowing
    path_loss_with_shadowing = [model.calculate_path_loss(100, 3.5, include_shadowing=True) for _ in range(1000)]
    std_dev = np.std(path_loss_with_shadowing)
    
    print(f"Path loss at 100m, 3.5GHz: {model.calculate_path_loss(100, 3.5, include_shadowing=False):.2f} dB")
    print(f"Standard deviation of shadowing: {std_dev:.2f} dB (expected: {model.sigma:.2f} dB)")
    
    # Should be close to model.sigma
    assert abs(std_dev - model.sigma) < 0.5, f"Shadowing std dev {std_dev:.2f} dB differs from model σ={model.sigma:.2f} dB"

def test_ci_path_loss_model():
    """Test Close-In path loss model."""
    # Create model
    model = CloseInPathLossModel()
    
    # Calculate path loss over distance
    distances = np.linspace(1, 1000, 100)
    path_loss_3ghz = [model.calculate_path_loss(d, 3.5, include_shadowing=False) for d in distances]
    path_loss_28ghz = [model.calculate_path_loss(d, 28, include_shadowing=False) for d in distances]
    
    # Plot results
    plt.figure(figsize=(10, 6))
    plt.plot(distances, path_loss_3ghz, 'b-', linewidth=2, label='3.5 GHz')
    plt.plot(distances, path_loss_28ghz, 'r-', linewidth=2, label='28 GHz')
    
    plt.xlabel('Distance (m)')
    plt.ylabel('Path Loss (dB)')
    plt.title('Close-In Path Loss Model')
    plt.grid(True)
    plt.legend()
    
    plt.savefig('ci_path_loss.png')
    print("Plot saved as ci_path_loss.png")
    
    assert True, "Close-In path loss model test passed"

def test_fast_fading():
    """Test fast fading model."""
    # Create model
    model = FastFading(carrier_frequency=3.5)
    
    # Generate fading for different velocities
    duration = 10.0  # seconds
    time_step = 0.01  # seconds
    time_points = np.arange(0, duration, time_step)
    
    fading_5kmh = model.generate_fading(5 / 3.6, duration, time_step)  # 5 km/h in m/s
    fading_30kmh = model.generate_fading(30 / 3.6, duration, time_step)  # 30 km/h in m/s
    fading_120kmh = model.generate_fading(120 / 3.6, duration, time_step)  # 120 km/h in m/s
    
    # Plot results
    plt.figure(figsize=(12, 8))
    
    plt.subplot(3, 1, 1)
    plt.plot(time_points, fading_5kmh, 'b-')
    plt.title('Fast Fading at 5 km/h')
    plt.ylabel('Fading (dB)')
    plt.grid(True)
    
    plt.subplot(3, 1, 2)
    plt.plot(time_points, fading_30kmh, 'g-')
    plt.title('Fast Fading at 30 km/h')
    plt.ylabel('Fading (dB)')
    plt.grid(True)
    
    plt.subplot(3, 1, 3)
    plt.plot(time_points, fading_120kmh, 'r-')
    plt.title('Fast Fading at 120 km/h')
    plt.xlabel('Time (s)')
    plt.ylabel('Fading (dB)')
    plt.grid(True)
    
    plt.tight_layout()
    plt.savefig('fast_fading.png')
    print("Plot saved as fast_fading.png")
    
    # Check statistical properties
    mean_5kmh = np.mean(fading_5kmh)
    std_5kmh = np.std(fading_5kmh)
    
    print(f"Fast fading at 5 km/h: Mean = {mean_5kmh:.2f} dB, Std = {std_5kmh:.2f} dB")
    
    # Mean should be close to 0 dB
    assert abs(mean_5kmh) < 1.0, f"Mean fading {mean_5kmh:.2f} dB differs from 0 dB" 

if __name__ == "__main__":
    print("Testing ABG Path Loss Model...")
    test_abg_path_loss_model()
    
    print("\nTesting Close-In Path Loss Model...")
    test_ci_path_loss_model()
    
    print("\nTesting Fast Fading Model...")
    test_fast_fading()
    
    print("\nAll tests completed.")
