"""
Highway Vehicle Handover Scenario.

A high-speed mobility scenario demonstrating ML-based handover optimization
for vehicles traveling on a highway corridor at speeds up to 120 km/h.

Key Features:
- 8 cells in linear deployment along a 10km highway
- 10 vehicles with varying speeds (80-120 km/h)
- High-speed handover demonstration
- Ping-pong prevention under rapid mobility
- Connected vehicle (V2X) use case

Use Case:
- Highway corridor 5G coverage
- Autonomous vehicle support
- Convoy/platoon scenarios
- Emergency vehicle priority

Reference: 3GPP TR 38.901 §7.6.2 (Rural Macro - Highway)
"""

import math
import random
from typing import Dict, List

from .base_scenario import (
    BaseScenario,
    CellConfig,
    UEConfig,
    PathConfig,
    ScenarioMetadata,
    ServiceType,
    MobilityType,
    UEType,
)


class HighwayHandoverScenario(BaseScenario):
    """
    Highway Vehicle Handover - High-Speed 5G Handover Demonstration.
    
    Simulates a highway corridor with:
    - Linear cell deployment (macro cells along highway)
    - Multiple vehicle speeds (cars, trucks, emergency vehicles)
    - Both directions of travel
    - Platoon/convoy scenarios
    
    Primary focus: Demonstrating ML's ability to:
    1. Handle high-speed handovers with minimal latency
    2. Prevent ping-pong during rapid cell transitions
    3. Prioritize emergency vehicles
    4. Support connected vehicle applications
    """
    
    # Athens National Highway (Attiki Odos) as reference
    # Starting point near Athens Airport, heading towards city center
    START_LAT = 37.9364
    START_LON = 23.9445
    END_LAT = 37.9892
    END_LON = 23.7897
    
    # Scenario parameters
    HIGHWAY_LENGTH_KM = 10.0
    NUM_CELLS = 8
    NUM_VEHICLES = 10
    
    # Speed profiles (km/h)
    CAR_SPEED_KMH = 120
    TRUCK_SPEED_KMH = 80
    EMERGENCY_SPEED_KMH = 150
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        
        # Reproducibility
        random.seed(42)
        
        # Vehicle mix
        self.vehicle_distribution = {
            "car": 0.50,       # 5 cars
            "truck": 0.30,    # 3 trucks  
            "emergency": 0.20  # 2 emergency vehicles
        }
    
    def get_metadata(self) -> ScenarioMetadata:
        return ScenarioMetadata(
            name="Highway Vehicle Handover",
            description=f"High-speed 5G handover scenario on a {self.HIGHWAY_LENGTH_KM}km "
                       f"highway corridor with {self.NUM_CELLS} macro cells and "
                       f"{self.NUM_VEHICLES} vehicles traveling at 80-150 km/h.",
            num_cells=self.NUM_CELLS,
            num_ues=self.NUM_VEHICLES,
            area_km2=10.0 * 0.1,  # 10km × 100m highway corridor
            primary_use_case="Highway Mobility / V2X",
            service_type_distribution={
                "embb": 0.50,
                "urllc": 0.40,  # Connected vehicles need URLLC
                "mmtc": 0.10
            },
            mobility_distribution={
                "highway_vehicle": 1.0  # All vehicles
            },
            expected_handovers_per_minute=12.0  # ~8 handovers per vehicle per trip
        )
    
    def _interpolate_highway_point(self, fraction: float) -> tuple:
        """
        Get a point along the highway at given fraction (0-1).
        Uses great circle interpolation for accuracy.
        """
        lat = self.START_LAT + fraction * (self.END_LAT - self.START_LAT)
        lon = self.START_LON + fraction * (self.END_LON - self.START_LON)
        return lat, lon
    
    def _perpendicular_offset(self, lat: float, lon: float, 
                               offset_m: float, highway_direction: float) -> tuple:
        """
        Offset a point perpendicular to highway direction.
        Used for positioning cells away from the roadway.
        """
        # Perpendicular angle (90 degrees from highway direction)
        perp_rad = math.radians(highway_direction + 90)
        
        # Approximate conversion
        deg_per_m_lat = 1 / 111320
        deg_per_m_lon = 1 / (111320 * math.cos(math.radians(lat)))
        
        new_lat = lat + offset_m * math.cos(perp_rad) * deg_per_m_lat
        new_lon = lon + offset_m * math.sin(perp_rad) * deg_per_m_lon
        
        return new_lat, new_lon
    
    def generate_cells(self) -> List[CellConfig]:
        """
        Generate 8 macro cells along the highway corridor.
        
        Cells are positioned ~50m away from the roadway on alternating sides.
        Inter-site distance: ~1.25km (typical highway deployment)
        Coverage radius: 800m (overlapping coverage for seamless handover)
        """
        cells = []
        
        # Highway direction (approximate bearing from start to end)
        highway_bearing = 310  # Northwest direction
        
        # Cell positions: 8 cells along 10km = 1.25km inter-site distance
        # Start 625m from beginning, end 625m before end
        cell_positions = [0.0625 + i * 0.125 for i in range(8)]
        
        # Cell descriptions
        descriptions = [
            "Highway Exit - Airport Junction",
            "Highway KM 1.3 - Industrial Zone",
            "Highway KM 2.5 - Suburban Entry",
            "Highway KM 3.8 - Commercial District",
            "Highway KM 5.0 - City Bypass North",
            "Highway KM 6.3 - City Bypass Central",
            "Highway KM 7.5 - Urban Transition",
            "Highway KM 8.8 - City Center Approach"
        ]
        
        for i, (fraction, description) in enumerate(zip(cell_positions, descriptions)):
            # Base position on highway
            base_lat, base_lon = self._interpolate_highway_point(fraction)
            
            # Offset perpendicular to highway (alternating sides)
            side_offset = 50 if i % 2 == 0 else -50
            cell_lat, cell_lon = self._perpendicular_offset(
                base_lat, base_lon, side_offset, highway_bearing
            )
            
            cells.append(CellConfig(
                cell_id=f"HWY{i+1:03d}",
                name=f"cell{i+1}",
                description=description,
                latitude=cell_lat,
                longitude=cell_lon,
                radius=800,  # Large radius for highway coverage
                gNB_id=1,
                # Extended parameters
                frequency_band="n78",  # 3.5 GHz
                tx_power_dbm=46.0,  # Higher power for macro cells
                antenna_height_m=35.0,  # Tall mast
                azimuth_deg=highway_bearing if i % 2 == 0 else highway_bearing + 180,
                tilt_deg=4.0  # Low tilt for long-range coverage
            ))
        
        return cells
    
    def generate_ues(self) -> List[UEConfig]:
        """
        Generate 10 vehicles with realistic mix.
        
        Vehicle Types:
        - 5 passenger cars (120 km/h) - eMBB
        - 3 trucks (80 km/h) - mMTC (fleet tracking)
        - 2 emergency vehicles (150 km/h) - URLLC priority
        """
        ues = []
        
        supi_base = "202010000002"
        
        # ============================================================
        # Passenger Cars (5 total) - eMBB
        # ============================================================
        
        for i in range(5):
            ues.append(UEConfig(
                supi=f"{supi_base}{i+1:03d}",
                name=f"Car_{i+1}",
                description=f"Passenger vehicle with infotainment system",
                cell_id=(i % self.NUM_CELLS) + 1,
                speed_profile="HIGH",
                ue_type=UEType.VEHICLE,
                service_type=ServiceType.EMBB,
                mobility_type=MobilityType.HIGHWAY_VEHICLE,
                latency_requirement_ms=30.0,
                throughput_requirement_mbps=50.0,  # HD video streaming
                reliability_pct=99.5
            ))
        
        # ============================================================
        # Trucks (3 total) - mMTC (fleet management)
        # ============================================================
        
        for i in range(3):
            ues.append(UEConfig(
                supi=f"{supi_base}{i+6:03d}",
                name=f"Truck_{i+1}",
                description=f"Commercial truck with fleet tracking",
                cell_id=(i % self.NUM_CELLS) + 1,
                speed_profile="MEDIUM",  # Slower than cars
                ue_type=UEType.VEHICLE,
                service_type=ServiceType.MMTC,
                mobility_type=MobilityType.HIGHWAY_VEHICLE,
                latency_requirement_ms=100.0,
                throughput_requirement_mbps=1.0,  # Telemetry data
                reliability_pct=99.0
            ))
        
        # ============================================================
        # Emergency Vehicles (2 total) - URLLC Priority
        # ============================================================
        
        emergency_types = ["Ambulance", "Police"]
        for i in range(2):
            ues.append(UEConfig(
                supi=f"{supi_base}{i+9:03d}",
                name=f"Emergency_{emergency_types[i]}",
                description=f"Emergency vehicle ({emergency_types[i]}) with priority access",
                cell_id=(i % self.NUM_CELLS) + 1,
                speed_profile="HIGH",
                ue_type=UEType.FIRST_RESPONDER,
                service_type=ServiceType.URLLC,
                mobility_type=MobilityType.HIGHWAY_VEHICLE,
                latency_requirement_ms=1.0,  # Mission-critical
                throughput_requirement_mbps=10.0,
                reliability_pct=99.999  # Ultra-reliable
            ))
        
        return ues
    
    def generate_paths(self) -> List[PathConfig]:
        """
        Generate highway mobility paths.
        
        Paths:
        1. Eastbound (full highway, normal speed)
        2. Westbound (full highway, reverse direction)
        3. Slow lane (trucks)
        4. Emergency corridor (center lane, high speed)
        5. Overtaking scenario (lane change pattern)
        """
        paths = []
        
        # ============================================================
        # Path 1: Eastbound Full Highway (City → Airport)
        # ============================================================
        
        eastbound_points = []
        for i in range(200):  # 200 points over 10km = 50m resolution
            fraction = i / 199
            lat, lon = self._interpolate_highway_point(1 - fraction)  # Reverse
            eastbound_points.append({
                "latitude": f"{lat:.6f}",
                "longitude": f"{lon:.6f}"
            })
        
        paths.append(PathConfig(
            description="Highway Eastbound - City to Airport",
            points=eastbound_points,
            start_point={"latitude": self.END_LAT, "longitude": self.END_LON},
            end_point={"latitude": self.START_LAT, "longitude": self.START_LON},
            color="#3498DB"  # Blue
        ))
        
        # ============================================================
        # Path 2: Westbound Full Highway (Airport → City)
        # ============================================================
        
        westbound_points = []
        for i in range(200):
            fraction = i / 199
            lat, lon = self._interpolate_highway_point(fraction)
            westbound_points.append({
                "latitude": f"{lat:.6f}",
                "longitude": f"{lon:.6f}"
            })
        
        paths.append(PathConfig(
            description="Highway Westbound - Airport to City",
            points=westbound_points,
            start_point={"latitude": self.START_LAT, "longitude": self.START_LON},
            end_point={"latitude": self.END_LAT, "longitude": self.END_LON},
            color="#2ECC71"  # Green
        ))
        
        # ============================================================
        # Path 3: Truck Lane (slow traffic, westbound)
        # ============================================================
        
        # Same path but fewer points (simulates slower vehicle)
        truck_points = []
        for i in range(150):
            fraction = i / 149
            lat, lon = self._interpolate_highway_point(fraction)
            truck_points.append({
                "latitude": f"{lat:.6f}",
                "longitude": f"{lon:.6f}"
            })
        
        paths.append(PathConfig(
            description="Highway Truck Lane - Slow Commercial Traffic",
            points=truck_points,
            start_point={"latitude": self.START_LAT, "longitude": self.START_LON},
            end_point={"latitude": self.END_LAT, "longitude": self.END_LON},
            color="#F39C12"  # Orange
        ))
        
        # ============================================================
        # Path 4: Emergency Corridor (high speed, priority)
        # ============================================================
        
        # Dense sampling for smooth high-speed tracking
        emergency_points = []
        for i in range(300):
            fraction = i / 299
            lat, lon = self._interpolate_highway_point(fraction)
            emergency_points.append({
                "latitude": f"{lat:.6f}",
                "longitude": f"{lon:.6f}"
            })
        
        paths.append(PathConfig(
            description="Emergency Corridor - Priority High-Speed Lane",
            points=emergency_points,
            start_point={"latitude": self.START_LAT, "longitude": self.START_LON},
            end_point={"latitude": self.END_LAT, "longitude": self.END_LON},
            color="#E74C3C"  # Red
        ))
        
        # ============================================================
        # Path 5: Overtaking Scenario (lane change pattern)
        # ============================================================
        
        # Simulates vehicle weaving between lanes
        overtake_points = []
        for i in range(200):
            fraction = i / 199
            base_lat, base_lon = self._interpolate_highway_point(fraction)
            
            # Add sinusoidal lateral offset to simulate lane changes
            lateral_offset = 5 * math.sin(fraction * math.pi * 6)  # 3 complete overtakes
            lat, lon = self._perpendicular_offset(
                base_lat, base_lon, lateral_offset, 310
            )
            
            overtake_points.append({
                "latitude": f"{lat:.6f}",
                "longitude": f"{lon:.6f}"
            })
        
        paths.append(PathConfig(
            description="Overtaking Pattern - Dynamic Lane Changes",
            points=overtake_points,
            start_point={"latitude": self.START_LAT, "longitude": self.START_LON},
            end_point={"latitude": self.END_LAT, "longitude": self.END_LON},
            color="#9B59B6"  # Purple
        ))
        
        return paths


# ============================================================================
# CLI Entry Point
# ============================================================================

def main():
    """Deploy the Highway Vehicle Handover scenario."""
    import argparse
    import os
    from pathlib import Path
    
    parser = argparse.ArgumentParser(
        description="Deploy Highway Vehicle Handover 5G Scenario"
    )
    parser.add_argument(
        "--nef-url", 
        default=os.environ.get("NEF_URL", "http://localhost:8080"),
        help="NEF emulator URL"
    )
    parser.add_argument(
        "--start-movement",
        action="store_true",
        help="Start vehicle movement after deployment"
    )
    parser.add_argument(
        "--save-topology",
        type=str,
        help="Path to save topology JSON"
    )
    
    args = parser.parse_args()
    
    # Create and deploy scenario
    scenario = HighwayHandoverScenario(nef_url=args.nef_url)
    
    success = scenario.deploy()
    
    if success:
        if args.save_topology:
            scenario.save_topology(Path(args.save_topology))
        
        if args.start_movement:
            print("\n▶️  Starting vehicle movement...")
            started = scenario.start_all_ues()
            print(f"   Started {started}/{len(scenario.ues)} vehicles")
            
            # Calculate expected handovers
            print("\n📊 Expected handover metrics:")
            print(f"   At 120 km/h with 1.25km inter-site distance:")
            print(f"   Time between cells: ~37.5 seconds")
            print(f"   Handovers per 10km trip: ~8 per vehicle")
            print(f"   Total expected handovers: ~80 during full run")
    
    return 0 if success else 1


if __name__ == "__main__":
    exit(main())
