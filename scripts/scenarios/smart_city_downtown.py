"""
Smart City Downtown Scenario.

A dense urban deployment scenario demonstrating ML-based handover optimization
in a realistic metropolitan environment with diverse mobility patterns.

Key Features:
- 15 small cells in a 2km × 2km downtown area
- 50 UEs with mixed mobility (pedestrians, vehicles, stationary)
- Multiple overlapping coverage zones
- QoS mix: 70% eMBB, 20% URLLC, 10% mMTC
- Manhattan-grid and random waypoint mobility patterns

Use Case:
- Dense urban 5G deployment
- Mixed traffic scenarios
- Load balancing demonstration
- Overlapping coverage handling

Reference: 3GPP TR 38.901 §7.6 (Urban Macro/Micro scenarios)
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


class SmartCityDowntownScenario(BaseScenario):
    """
    Smart City Downtown - Dense Urban 5G Deployment.
    
    Simulates a realistic downtown environment with:
    - Office buildings
    - Shopping districts
    - Transit hubs
    - Public spaces
    
    Network topology inspired by real-world small cell deployments
    in metropolitan areas (e.g., London, NYC, Tokyo).
    """
    
    # Athens downtown center (Syntagma Square area) as reference point
    CENTER_LAT = 37.9755
    CENTER_LON = 23.7348
    
    # Scenario dimensions
    AREA_SIZE_M = 2000  # 2km × 2km
    NUM_CELLS = 15
    NUM_UES = 50
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        
        # Seed for reproducibility
        random.seed(42)
        
        # Distribution parameters
        self.service_distribution = {
            ServiceType.EMBB: 0.70,
            ServiceType.URLLC: 0.20,
            ServiceType.MMTC: 0.10
        }
        
        self.mobility_distribution = {
            MobilityType.STATIONARY: 0.15,
            MobilityType.PEDESTRIAN: 0.45,
            MobilityType.URBAN_VEHICLE: 0.30,
            MobilityType.HIGHWAY_VEHICLE: 0.10
        }
    
    def get_metadata(self) -> ScenarioMetadata:
        return ScenarioMetadata(
            name="Smart City Downtown",
            description="Dense urban 5G deployment in a 2km × 2km downtown area "
                       "with 15 small cells and 50 UEs representing realistic "
                       "metropolitan traffic patterns.",
            num_cells=self.NUM_CELLS,
            num_ues=self.NUM_UES,
            area_km2=4.0,  # 2km × 2km
            primary_use_case="Dense Urban Coverage",
            service_type_distribution={
                "embb": 0.70,
                "urllc": 0.20,
                "mmtc": 0.10
            },
            mobility_distribution={
                "stationary": 0.15,
                "pedestrian": 0.45,
                "urban_vehicle": 0.30,
                "highway_vehicle": 0.10
            },
            expected_handovers_per_minute=25.0  # High due to small cells
        )
    
    def _offset_coordinates(self, lat: float, lon: float, 
                            offset_m_x: float, offset_m_y: float) -> tuple:
        """Calculate new coordinates given meter offsets."""
        # Approximate conversion factors
        deg_per_m_lat = 1 / 111320
        deg_per_m_lon = 1 / (111320 * math.cos(math.radians(lat)))
        
        new_lat = lat + offset_m_y * deg_per_m_lat
        new_lon = lon + offset_m_x * deg_per_m_lon
        
        return new_lat, new_lon
    
    def generate_cells(self) -> List[CellConfig]:
        """
        Generate 15 small cells in a downtown grid pattern.
        
        Layout (approximate):
        - 4 cells in central business district (CBD)
        - 4 cells along main shopping street
        - 3 cells near transit hub
        - 2 cells in residential transition zone
        - 2 cells in public park area
        """
        cells = []
        
        # Cell configurations as (name, description, x_offset_m, y_offset_m, radius)
        cell_configs = [
            # Central Business District (CBD) - high density, small radius
            ("CBD_North", "Central Business District - North Tower", 0, 400, 120),
            ("CBD_South", "Central Business District - South Tower", 0, -400, 120),
            ("CBD_East", "Central Business District - East Plaza", 350, 0, 100),
            ("CBD_West", "Central Business District - West Plaza", -350, 0, 100),
            
            # Main Shopping Street (linear deployment)
            ("Shopping_1", "Main Shopping Street - Section A", -600, 200, 80),
            ("Shopping_2", "Main Shopping Street - Section B", -300, 200, 80),
            ("Shopping_3", "Main Shopping Street - Section C", 300, 200, 80),
            ("Shopping_4", "Main Shopping Street - Section D", 600, 200, 80),
            
            # Transit Hub (metro station, bus terminal)
            ("Transit_Main", "Central Transit Hub - Main Hall", -200, -600, 150),
            ("Transit_Platform", "Central Transit Hub - Platform Area", 0, -700, 100),
            ("Transit_Exit", "Central Transit Hub - Street Exit", 200, -500, 100),
            
            # Residential Transition Zone
            ("Residential_N1", "Residential Zone - Block A", -500, 700, 180),
            ("Residential_N2", "Residential Zone - Block B", 500, 700, 180),
            
            # Public Park / Open Area
            ("Park_Center", "Central Park - Main Area", 700, -200, 200),
            ("Park_South", "Central Park - South Gardens", 600, -500, 150),
        ]
        
        for i, (name, description, x_off, y_off, radius) in enumerate(cell_configs):
            lat, lon = self._offset_coordinates(
                self.CENTER_LAT, self.CENTER_LON, x_off, y_off
            )
            
            cells.append(CellConfig(
                cell_id=f"SMART{i+1:03d}",
                name=f"cell{i+1}",
                description=description,
                latitude=lat,
                longitude=lon,
                radius=radius,
                gNB_id=1,
                # Extended parameters for documentation
                frequency_band="n78",  # 3.5 GHz
                tx_power_dbm=37.0 if radius < 100 else 43.0,  # Lower power for small cells
                antenna_height_m=15.0 if "Shopping" in name else 25.0
            ))
        
        return cells
    
    def generate_ues(self) -> List[UEConfig]:
        """
        Generate 50 UEs with realistic distribution.
        
        Distribution:
        - 35 eMBB devices (smartphones, tablets) - pedestrians & vehicles
        - 10 URLLC devices (emergency services, autonomous vehicles)
        - 5 mMTC devices (IoT sensors, smart city infrastructure)
        """
        ues = []
        
        # Generate SUPI base
        supi_base = "202010000001"
        
        # ============================================================
        # eMBB Devices (35 total)
        # ============================================================
        
        # Pedestrians with smartphones (20)
        for i in range(20):
            ues.append(UEConfig(
                supi=f"{supi_base}{i+1:03d}",
                name=f"Pedestrian_{i+1}",
                description=f"Pedestrian with smartphone in downtown area",
                cell_id=(i % self.NUM_CELLS) + 1,
                speed_profile="LOW",
                ue_type=UEType.SMARTPHONE,
                service_type=ServiceType.EMBB,
                mobility_type=MobilityType.PEDESTRIAN,
                latency_requirement_ms=50.0,
                throughput_requirement_mbps=100.0
            ))
        
        # Urban vehicles (10) - taxis, ride-share, delivery
        for i in range(10):
            ues.append(UEConfig(
                supi=f"{supi_base}{i+21:03d}",
                name=f"Vehicle_{i+1}",
                description=f"Urban vehicle (taxi/delivery) with mobile device",
                cell_id=(i % self.NUM_CELLS) + 1,
                speed_profile="MEDIUM",
                ue_type=UEType.VEHICLE,
                service_type=ServiceType.EMBB,
                mobility_type=MobilityType.URBAN_VEHICLE,
                latency_requirement_ms=30.0,
                throughput_requirement_mbps=50.0
            ))
        
        # Stationary tablets in cafes/offices (5)
        for i in range(5):
            ues.append(UEConfig(
                supi=f"{supi_base}{i+31:03d}",
                name=f"Tablet_{i+1}",
                description=f"Stationary tablet in cafe/office",
                cell_id=(i % self.NUM_CELLS) + 1,
                speed_profile="LOW",
                ue_type=UEType.TABLET,
                service_type=ServiceType.EMBB,
                mobility_type=MobilityType.STATIONARY,
                latency_requirement_ms=100.0,
                throughput_requirement_mbps=150.0
            ))
        
        # ============================================================
        # URLLC Devices (10 total)
        # ============================================================
        
        # First responder devices (5)
        for i in range(5):
            ues.append(UEConfig(
                supi=f"{supi_base}{i+36:03d}",
                name=f"FirstResponder_{i+1}",
                description=f"First responder priority device",
                cell_id=(i % self.NUM_CELLS) + 1,
                speed_profile="HIGH",
                ue_type=UEType.FIRST_RESPONDER,
                service_type=ServiceType.URLLC,
                mobility_type=MobilityType.URBAN_VEHICLE,
                latency_requirement_ms=1.0,
                throughput_requirement_mbps=20.0,
                reliability_pct=99.999
            ))
        
        # Autonomous delivery vehicles (5)
        for i in range(5):
            ues.append(UEConfig(
                supi=f"{supi_base}{i+41:03d}",
                name=f"AutoVehicle_{i+1}",
                description=f"Autonomous delivery vehicle",
                cell_id=(i % self.NUM_CELLS) + 1,
                speed_profile="MEDIUM",
                ue_type=UEType.VEHICLE,
                service_type=ServiceType.URLLC,
                mobility_type=MobilityType.URBAN_VEHICLE,
                latency_requirement_ms=5.0,
                throughput_requirement_mbps=10.0,
                reliability_pct=99.99
            ))
        
        # ============================================================
        # mMTC Devices (5 total)
        # ============================================================
        
        # Smart city sensors
        for i in range(5):
            ues.append(UEConfig(
                supi=f"{supi_base}{i+46:03d}",
                name=f"Sensor_{i+1}",
                description=f"Smart city sensor (air quality/traffic)",
                cell_id=(i % self.NUM_CELLS) + 1,
                speed_profile="LOW",
                ue_type=UEType.IOT_SENSOR,
                service_type=ServiceType.MMTC,
                mobility_type=MobilityType.STATIONARY,
                latency_requirement_ms=1000.0,
                throughput_requirement_mbps=0.1,
                reliability_pct=99.0
            ))
        
        return ues
    
    def generate_paths(self) -> List[PathConfig]:
        """
        Generate realistic mobility paths for downtown area.
        
        Paths:
        1. Main shopping street walk (pedestrian)
        2. CBD circular route (vehicles)
        3. Transit hub to CBD (commuters)
        4. Park walking path (leisure)
        5. Emergency route (high priority)
        """
        paths = []
        
        # Path 1: Shopping Street Walk (800m linear)
        start_lat, start_lon = self._offset_coordinates(
            self.CENTER_LAT, self.CENTER_LON, -600, 200
        )
        end_lat, end_lon = self._offset_coordinates(
            self.CENTER_LAT, self.CENTER_LON, 600, 200
        )
        
        paths.append(PathConfig(
            description="Shopping Street Walk - Main Pedestrian Route",
            points=self.generate_linear_path(
                start_lat, start_lon, end_lat, end_lon, num_points=150
            ),
            start_point={"latitude": start_lat, "longitude": start_lon},
            end_point={"latitude": end_lat, "longitude": end_lon},
            color="#FF6B6B"  # Coral red
        ))
        
        # Path 2: CBD Vehicle Loop (circular)
        cbd_path_points = []
        for angle in range(0, 361, 5):
            rad = math.radians(angle)
            x_off = 400 * math.cos(rad)
            y_off = 400 * math.sin(rad)
            lat, lon = self._offset_coordinates(
                self.CENTER_LAT, self.CENTER_LON, x_off, y_off
            )
            cbd_path_points.append({
                "latitude": f"{lat:.6f}",
                "longitude": f"{lon:.6f}"
            })
        
        paths.append(PathConfig(
            description="CBD Vehicle Loop - Main Traffic Route",
            points=cbd_path_points,
            start_point={"latitude": self.CENTER_LAT + 0.0036, 
                        "longitude": self.CENTER_LON},
            end_point={"latitude": self.CENTER_LAT + 0.0036, 
                      "longitude": self.CENTER_LON},
            color="#4ECDC4"  # Teal
        ))
        
        # Path 3: Transit Hub to CBD (commuter route)
        transit_lat, transit_lon = self._offset_coordinates(
            self.CENTER_LAT, self.CENTER_LON, 0, -700
        )
        
        paths.append(PathConfig(
            description="Transit Hub to CBD - Commuter Route",
            points=self.generate_linear_path(
                transit_lat, transit_lon, 
                self.CENTER_LAT, self.CENTER_LON, 
                num_points=100
            ),
            start_point={"latitude": transit_lat, "longitude": transit_lon},
            end_point={"latitude": self.CENTER_LAT, "longitude": self.CENTER_LON},
            color="#45B7D1"  # Light blue
        ))
        
        # Path 4: Park Walking Path
        park_start_lat, park_start_lon = self._offset_coordinates(
            self.CENTER_LAT, self.CENTER_LON, 700, -200
        )
        park_end_lat, park_end_lon = self._offset_coordinates(
            self.CENTER_LAT, self.CENTER_LON, 600, -500
        )
        
        paths.append(PathConfig(
            description="Central Park Walking Path",
            points=self.generate_linear_path(
                park_start_lat, park_start_lon,
                park_end_lat, park_end_lon,
                num_points=80
            ),
            start_point={"latitude": park_start_lat, "longitude": park_start_lon},
            end_point={"latitude": park_end_lat, "longitude": park_end_lon},
            color="#96CEB4"  # Sage green
        ))
        
        # Path 5: Emergency Response Route (cross-city)
        emergency_start_lat, emergency_start_lon = self._offset_coordinates(
            self.CENTER_LAT, self.CENTER_LON, -800, -800
        )
        emergency_end_lat, emergency_end_lon = self._offset_coordinates(
            self.CENTER_LAT, self.CENTER_LON, 800, 800
        )
        
        paths.append(PathConfig(
            description="Emergency Response Route - High Priority Cross-City",
            points=self.generate_linear_path(
                emergency_start_lat, emergency_start_lon,
                emergency_end_lat, emergency_end_lon,
                num_points=200
            ),
            start_point={"latitude": emergency_start_lat, 
                        "longitude": emergency_start_lon},
            end_point={"latitude": emergency_end_lat, 
                      "longitude": emergency_end_lon},
            color="#D63230"  # Emergency red
        ))
        
        return paths


# ============================================================================
# CLI Entry Point
# ============================================================================

def main():
    """Deploy the Smart City Downtown scenario."""
    import argparse
    from pathlib import Path
    
    parser = argparse.ArgumentParser(
        description="Deploy Smart City Downtown 5G Scenario"
    )
    parser.add_argument(
        "--nef-url", 
        default="http://localhost:8080",
        help="NEF emulator URL"
    )
    parser.add_argument(
        "--start-movement",
        action="store_true",
        help="Start UE movement after deployment"
    )
    parser.add_argument(
        "--save-topology",
        type=str,
        help="Path to save topology JSON"
    )
    
    args = parser.parse_args()
    
    # Create and deploy scenario
    scenario = SmartCityDowntownScenario(nef_url=args.nef_url)
    
    success = scenario.deploy()
    
    if success:
        if args.save_topology:
            scenario.save_topology(Path(args.save_topology))
        
        if args.start_movement:
            print("\n▶️  Starting UE movement...")
            started = scenario.start_all_ues()
            print(f"   Started {started}/{len(scenario.ues)} UEs")
    
    return 0 if success else 1


if __name__ == "__main__":
    exit(main())
