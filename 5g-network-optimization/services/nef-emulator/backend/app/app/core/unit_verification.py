"""Distance and coordinate unit verification utilities.

This module implements Fix #2 from the thesis implementation plan:
Distance Units Verification.

The AR1 shadowing formula uses decorr_distance = 37 meters. This utility
ensures that position coordinates are in meters (not degrees, kilometers,
or arbitrary units).

Usage:
    from app.core.unit_verification import verify_coordinate_units
    
    # Verify units before running experiments
    is_valid, message = verify_coordinate_units(
        pos1=(0, 0, 0),
        pos2=(100, 0, 0),
        expected_distance_m=100.0
    )
"""

from __future__ import annotations

import logging
import math
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def euclidean_distance(
    pos1: Tuple[float, float, float],
    pos2: Tuple[float, float, float],
) -> float:
    """Calculate Euclidean distance between two 3D positions.
    
    Args:
        pos1: First position (x, y, z)
        pos2: Second position (x, y, z)
        
    Returns:
        Distance (units depend on input coordinate system)
    """
    dx = pos2[0] - pos1[0]
    dy = pos2[1] - pos1[1]
    dz = pos2[2] - pos1[2]
    return math.sqrt(dx*dx + dy*dy + dz*dz)


def verify_coordinate_units(
    pos1: Tuple[float, float, float],
    pos2: Tuple[float, float, float],
    expected_distance_m: float,
    tolerance: float = 0.01,
) -> Tuple[bool, str]:
    """Verify that coordinate units are in meters.
    
    This test ensures the position coordinate system uses meters,
    which is required for the AR1 shadowing correlation calculation.
    
    Args:
        pos1: First test position (x, y, z)
        pos2: Second test position (x, y, z)
        expected_distance_m: Expected distance in meters
        tolerance: Relative tolerance for comparison
        
    Returns:
        Tuple of (is_valid, message)
        
    Example:
        >>> verify_coordinate_units((0,0,0), (100,0,0), 100.0)
        (True, "Coordinate units verified: 1 unit = 1 meter")
    """
    calculated = euclidean_distance(pos1, pos2)
    
    if calculated == 0:
        return False, "Cannot verify: positions are identical"
    
    ratio = calculated / expected_distance_m
    
    # Check for common unit mismatches
    if abs(ratio - 1.0) < tolerance:
        return True, f"Coordinate units verified: 1 unit = 1 meter (calculated={calculated:.2f}m)"
    
    elif abs(ratio - 1000.0) < tolerance * 1000:
        return False, (
            f"UNIT MISMATCH: Coordinates appear to be in KILOMETERS (ratio={ratio:.1f}). "
            f"Expected distance {expected_distance_m}m, got {calculated:.4f}. "
            f"ACTION: Convert positions to meters."
        )
    
    elif abs(ratio - 0.001) < tolerance * 0.001:
        return False, (
            f"UNIT MISMATCH: Coordinates appear to be in MILLIMETERS (ratio={ratio:.6f}). "
            f"Expected distance {expected_distance_m}m, got {calculated:.2f}. "
            f"ACTION: Convert positions to meters."
        )
    
    elif ratio < 0.01:
        # Very small - likely degrees
        return False, (
            f"UNIT MISMATCH: Coordinates may be in DEGREES (ratio={ratio:.6f}). "
            f"Expected distance {expected_distance_m}m, got {calculated:.6f}. "
            f"ACTION: Convert lat/lon degrees to local Cartesian (meters)."
        )
    
    else:
        return False, (
            f"UNIT MISMATCH: Unknown coordinate system (ratio={ratio:.4f}). "
            f"Expected distance {expected_distance_m}m, got {calculated:.4f}. "
            f"ACTION: Verify coordinate transformation."
        )


def verify_topology_units(
    antennas: dict,
    reference_cell_spacing_m: Optional[float] = None,
) -> Tuple[bool, str]:
    """Verify units across an entire network topology.
    
    Args:
        antennas: Dict mapping antenna_id to antenna object (with .position attribute)
        reference_cell_spacing_m: Optional expected inter-cell distance
        
    Returns:
        Tuple of (is_valid, message)
    """
    if not antennas or len(antennas) < 2:
        return True, "Cannot verify: need at least 2 antennas"
    
    positions = []
    for ant_id, ant in antennas.items():
        if hasattr(ant, 'position'):
            positions.append((ant_id, ant.position))
    
    if len(positions) < 2:
        return True, "Cannot verify: no antenna positions found"
    
    # Calculate distances between all pairs
    distances = []
    for i in range(len(positions)):
        for j in range(i + 1, len(positions)):
            dist = euclidean_distance(positions[i][1], positions[j][1])
            distances.append((positions[i][0], positions[j][0], dist))
    
    min_dist = min(d[2] for d in distances)
    max_dist = max(d[2] for d in distances)
    avg_dist = sum(d[2] for d in distances) / len(distances)
    
    # Check for reasonable cell spacing (typically 200m - 2000m for urban macro)
    issues = []
    
    if min_dist < 10:
        issues.append(
            f"WARNING: Very small inter-cell distance ({min_dist:.2f}m) - "
            "positions may be in wrong units or cells overlap"
        )
    
    if max_dist > 100000:
        issues.append(
            f"WARNING: Very large inter-cell distance ({max_dist:.2f}m) - "
            "positions may be in wrong units or extreme deployment"
        )
    
    if min_dist < 50 and max_dist > 50000:
        issues.append(
            "WARNING: Mix of very small and large distances - "
            "check coordinate transformation consistency"
        )
    
    # If reference spacing provided, check against it
    if reference_cell_spacing_m is not None:
        # Find nearest-neighbor distances
        nn_distances = []
        for i, (aid, pos) in enumerate(positions):
            min_nn = float('inf')
            for j, (aid2, pos2) in enumerate(positions):
                if i != j:
                    d = euclidean_distance(pos, pos2)
                    min_nn = min(min_nn, d)
            if min_nn < float('inf'):
                nn_distances.append(min_nn)
        
        avg_nn = sum(nn_distances) / len(nn_distances) if nn_distances else 0
        ratio = avg_nn / reference_cell_spacing_m if reference_cell_spacing_m > 0 else 0
        
        if abs(ratio - 1.0) > 0.5:
            issues.append(
                f"WARNING: Average nearest-neighbor distance ({avg_nn:.1f}m) differs "
                f"significantly from expected cell spacing ({reference_cell_spacing_m:.1f}m), "
                f"ratio={ratio:.2f}"
            )
    
    summary = (
        f"Topology analysis: {len(positions)} cells, "
        f"distances: min={min_dist:.1f}m, max={max_dist:.1f}m, avg={avg_dist:.1f}m"
    )
    
    if issues:
        return False, summary + "\n" + "\n".join(issues)
    
    return True, summary + " - All distances appear reasonable"


def convert_latlon_to_local(
    lat: float,
    lon: float,
    ref_lat: float,
    ref_lon: float,
) -> Tuple[float, float]:
    """Convert lat/lon to local Cartesian coordinates in meters.
    
    Uses equirectangular approximation (valid for small areas).
    
    Args:
        lat: Latitude in degrees
        lon: Longitude in degrees
        ref_lat: Reference latitude (origin)
        ref_lon: Reference longitude (origin)
        
    Returns:
        Tuple of (x_meters, y_meters) relative to reference
    """
    EARTH_RADIUS_M = 6_371_000.0
    
    # Convert degrees to radians
    lat_rad = math.radians(lat)
    lon_rad = math.radians(lon)
    ref_lat_rad = math.radians(ref_lat)
    ref_lon_rad = math.radians(ref_lon)
    
    # Equirectangular projection
    x = EARTH_RADIUS_M * (lon_rad - ref_lon_rad) * math.cos(ref_lat_rad)
    y = EARTH_RADIUS_M * (lat_rad - ref_lat_rad)
    
    return x, y


def run_unit_verification_test() -> bool:
    """Run standard unit verification test.
    
    Creates two test positions 100m apart and verifies the
    Euclidean distance calculation returns 100.0m.
    
    Returns:
        True if verification passes
    """
    # Test 1: Basic 100m separation
    is_valid, msg = verify_coordinate_units(
        pos1=(0, 0, 0),
        pos2=(100, 0, 0),
        expected_distance_m=100.0
    )
    logger.info("Unit verification test 1: %s - %s", "PASS" if is_valid else "FAIL", msg)
    
    if not is_valid:
        return False
    
    # Test 2: 3D distance
    is_valid, msg = verify_coordinate_units(
        pos1=(0, 0, 0),
        pos2=(300, 400, 0),
        expected_distance_m=500.0  # 3-4-5 triangle scaled
    )
    logger.info("Unit verification test 2: %s - %s", "PASS" if is_valid else "FAIL", msg)
    
    if not is_valid:
        return False
    
    # Test 3: Typical cell spacing
    is_valid, msg = verify_coordinate_units(
        pos1=(0, 0, 25),
        pos2=(500, 0, 25),
        expected_distance_m=500.0
    )
    logger.info("Unit verification test 3: %s - %s", "PASS" if is_valid else "FAIL", msg)
    
    return is_valid


# Run verification when module is imported (for early failure detection)
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    success = run_unit_verification_test()
    print(f"\nUnit verification: {'PASSED' if success else 'FAILED'}")
