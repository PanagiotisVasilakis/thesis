"""
Base Scenario Infrastructure for Enhanced 5G Network Scenarios.

Provides common functionality for all deployment scenarios:
- Topology generation (cells, gNBs, UEs)
- Mobility pattern creation
- QoS profile assignment
- Experiment orchestration
- Results collection

Aligned with 3GPP TR 38.901 and TS 23.501 specifications.
"""

import json
import math
import random
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import requests


class ServiceType(Enum):
    """5G QoS service types per 3GPP TS 23.501."""
    EMBB = "embb"           # Enhanced Mobile Broadband
    URLLC = "urllc"         # Ultra-Reliable Low-Latency Communications
    MMTC = "mmtc"           # Massive Machine-Type Communications
    DEFAULT = "default"     # Best effort


class MobilityType(Enum):
    """Mobility pattern types per 3GPP TR 38.901."""
    STATIONARY = "stationary"
    PEDESTRIAN = "pedestrian"      # 0-7 km/h
    URBAN_VEHICLE = "urban"        # 15-50 km/h
    HIGHWAY_VEHICLE = "highway"    # 80-150 km/h
    HIGH_SPEED_TRAIN = "train"     # 250-500 km/h


class UEType(Enum):
    """UE device types for scenario generation."""
    SMARTPHONE = "smartphone"
    TABLET = "tablet"
    IOT_SENSOR = "iot_sensor"
    VEHICLE = "vehicle"
    AGV = "agv"  # Automated Guided Vehicle
    DRONE = "drone"
    FIRST_RESPONDER = "first_responder"


@dataclass
class CellConfig:
    """Configuration for a 5G cell (antenna)."""
    cell_id: str
    name: str
    description: str
    latitude: float
    longitude: float
    radius: int  # Coverage radius in meters
    gNB_id: int = 1
    
    # Extended parameters for realistic simulation
    frequency_band: str = "n78"  # 3.5 GHz (common 5G band)
    tx_power_dbm: float = 43.0   # Typical macro cell power
    antenna_height_m: float = 25.0
    azimuth_deg: float = 0.0
    tilt_deg: float = 6.0
    
    def to_api_payload(self) -> Dict:
        """Convert to NEF API payload format."""
        return {
            "cell_id": self.cell_id,
            "name": self.name,
            "description": self.description,
            "gNB_id": self.gNB_id,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "radius": self.radius
        }


@dataclass
class UEConfig:
    """Configuration for a User Equipment."""
    supi: str
    name: str
    description: str
    cell_id: int
    speed_profile: str  # "LOW", "MEDIUM", "HIGH"
    
    # Extended parameters
    ue_type: UEType = UEType.SMARTPHONE
    service_type: ServiceType = ServiceType.EMBB
    mobility_type: MobilityType = MobilityType.PEDESTRIAN
    
    # Network identifiers
    gNB_id: int = 1
    ip_address_v4: str = ""
    ip_address_v6: str = ""
    mac_address: str = ""
    
    # QoS requirements
    latency_requirement_ms: float = 50.0
    throughput_requirement_mbps: float = 100.0
    reliability_pct: float = 99.5
    
    def __post_init__(self):
        # Auto-generate network identifiers if not provided
        # Extract numeric suffix from SUPI, handling leading zeros safely
        try:
            supi_num = int(self.supi[-3:])  # Get last 3 digits as number
        except ValueError:
            supi_num = hash(self.supi) % 254 + 1  # Fallback to hash-based
        
        if not self.ip_address_v4:
            # Ensure IP is in valid range (1-254)
            ip_last_octet = max(1, min(254, supi_num % 255))
            self.ip_address_v4 = f"10.0.0.{ip_last_octet}"
        if not self.ip_address_v6:
            self.ip_address_v6 = f"0:0:0:0:0:0:0:{supi_num}"
        if not self.mac_address:
            # Format as proper MAC with zero-padding
            self.mac_address = f"22-00-00-00-00-{supi_num:02X}"
    
    def to_api_payload(self) -> Dict:
        """Convert to NEF API payload format."""
        return {
            "supi": self.supi,
            "name": self.name,
            "description": self.description,
            "gNB_id": self.gNB_id,
            "Cell_id": self.cell_id,
            "ip_address_v4": self.ip_address_v4,
            "ip_address_v6": self.ip_address_v6,
            "mac_address": self.mac_address,
            "dnn": "province1.mnc01.mcc202.gprs",
            "mcc": 202,
            "mnc": 1,
            "external_identifier": f"{self.supi[-5:]}@domain.com",
            "speed": self.speed_profile
        }


@dataclass
class PathConfig:
    """Configuration for a mobility path."""
    description: str
    points: List[Dict[str, str]]  # List of {"latitude": str, "longitude": str}
    start_point: Dict[str, float]
    end_point: Dict[str, float]
    color: str = "#00a3cc"
    
    def to_api_payload(self) -> Dict:
        """Convert to NEF API payload format."""
        return {
            "description": self.description,
            "points": self.points,
            "start_point": self.start_point,
            "end_point": self.end_point,
            "color": self.color
        }


@dataclass
class ScenarioMetadata:
    """Metadata for a scenario experiment."""
    name: str
    description: str
    num_cells: int
    num_ues: int
    area_km2: float
    primary_use_case: str
    service_type_distribution: Dict[str, float]
    mobility_distribution: Dict[str, float]
    expected_handovers_per_minute: float
    
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self) -> Dict:
        return asdict(self)


class BaseScenario(ABC):
    """
    Abstract base class for all enhanced scenarios.
    
    Subclasses must implement:
    - generate_cells(): Create cell configurations
    - generate_ues(): Create UE configurations
    - generate_paths(): Create mobility paths
    - get_metadata(): Return scenario metadata
    """
    
    def __init__(self, 
                 nef_url: str = None,
                 username: str = None,
                 password: str = None):
        import os
        self.nef_url = nef_url or os.environ.get("NEF_URL", "http://localhost:8080")
        self.username = username or os.environ.get("NEF_USERNAME", "admin@my-email.com")
        self.password = password or os.environ.get("NEF_PASSWORD", "pass")
        self.token: Optional[str] = None
        
        self.cells: List[CellConfig] = []
        self.ues: List[UEConfig] = []
        self.paths: List[PathConfig] = []
        self.gnb_id: int = 1
        
        # Track created resources for cleanup
        self._created_cells: List[int] = []
        self._created_ues: List[str] = []
        self._created_paths: List[int] = []
    
    # =========================================================================
    # Abstract methods to be implemented by subclasses
    # =========================================================================
    
    @abstractmethod
    def generate_cells(self) -> List[CellConfig]:
        """Generate cell configurations for this scenario."""
        pass
    
    @abstractmethod
    def generate_ues(self) -> List[UEConfig]:
        """Generate UE configurations for this scenario."""
        pass
    
    @abstractmethod
    def generate_paths(self) -> List[PathConfig]:
        """Generate mobility paths for this scenario."""
        pass
    
    @abstractmethod
    def get_metadata(self) -> ScenarioMetadata:
        """Return metadata describing this scenario."""
        pass
    
    # =========================================================================
    # Authentication
    # =========================================================================
    
    def authenticate(self) -> bool:
        """Authenticate with the NEF emulator."""
        try:
            response = requests.post(
                f"{self.nef_url}/api/v1/login/access-token",
                headers={
                    "accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded"
                },
                data={
                    "username": self.username,
                    "password": self.password,
                    "grant_type": "",
                    "scope": "",
                    "client_id": "",
                    "client_secret": ""
                }
            )
            
            if response.status_code == 200:
                self.token = response.json().get("access_token")
                return True
            else:
                print(f"❌ Authentication failed: {response.status_code}")
                return False
        except requests.RequestException as e:
            print(f"❌ Connection error: {e}")
            return False
    
    def _get_headers(self) -> Dict[str, str]:
        """Get authenticated headers for API calls."""
        headers = {
            "accept": "application/json",
            "Content-Type": "application/json"
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers
    
    # =========================================================================
    # Topology Creation
    # =========================================================================
    
    def create_gnb(self, gnb_id: str = "AAAAA1", name: str = "gNB1") -> bool:
        """Create a gNB (base station)."""
        try:
            response = requests.post(
                f"{self.nef_url}/api/v1/gNBs",
                headers=self._get_headers(),
                json={
                    "gNB_id": gnb_id,
                    "name": name,
                    "description": f"Base station for {self.get_metadata().name}",
                    "location": "scenario_deployment"
                }
            )
            
            if response.status_code in [200, 201]:
                print(f"✅ Created gNB: {name}")
                return True
            elif "already exists" in response.text.lower():
                print(f"ℹ️  gNB {name} already exists")
                return True
            else:
                print(f"❌ Failed to create gNB: {response.status_code}")
                return False
        except requests.RequestException as e:
            print(f"❌ Error creating gNB: {e}")
            return False
    
    def create_cell(self, cell: CellConfig) -> bool:
        """Create a single cell."""
        try:
            response = requests.post(
                f"{self.nef_url}/api/v1/Cells",
                headers=self._get_headers(),
                json=cell.to_api_payload()
            )
            
            if response.status_code in [200, 201]:
                print(f"✅ Created cell: {cell.name} ({cell.description})")
                cell_data = response.json()
                self._created_cells.append(cell_data.get("id", cell.cell_id))
                return True
            elif "already exists" in response.text.lower():
                print(f"ℹ️  Cell {cell.name} already exists")
                return True
            else:
                print(f"❌ Failed to create cell {cell.name}: {response.status_code}")
                print(f"   Response: {response.text[:200]}")
                return False
        except requests.RequestException as e:
            print(f"❌ Error creating cell {cell.name}: {e}")
            return False
    
    def create_ue(self, ue: UEConfig) -> bool:
        """Create a single UE."""
        try:
            response = requests.post(
                f"{self.nef_url}/api/v1/UEs",
                headers=self._get_headers(),
                json=ue.to_api_payload()
            )
            
            if response.status_code in [200, 201]:
                print(f"✅ Created UE: {ue.name} ({ue.ue_type.value}, {ue.service_type.value})")
                self._created_ues.append(ue.supi)
                return True
            elif "already exists" in response.text.lower():
                print(f"ℹ️  UE {ue.name} already exists")
                return True
            else:
                print(f"❌ Failed to create UE {ue.name}: {response.status_code}")
                return False
        except requests.RequestException as e:
            print(f"❌ Error creating UE {ue.name}: {e}")
            return False
    
    def create_path(self, path: PathConfig) -> Optional[int]:
        """Create a mobility path and return its ID."""
        try:
            response = requests.post(
                f"{self.nef_url}/api/v1/paths",
                headers=self._get_headers(),
                json=path.to_api_payload()
            )
            
            if response.status_code in [200, 201]:
                path_data = response.json()
                path_id = path_data.get("id")
                print(f"✅ Created path: {path.description} (ID: {path_id})")
                if path_id:
                    self._created_paths.append(path_id)
                return path_id
            elif "already exists" in response.text.lower():
                print(f"ℹ️  Path {path.description} already exists")
                return None
            else:
                print(f"❌ Failed to create path: {response.status_code}")
                return None
        except requests.RequestException as e:
            print(f"❌ Error creating path: {e}")
            return None
    
    def associate_ue_with_path(self, supi: str, path_id: int) -> bool:
        """Associate a UE with a mobility path."""
        try:
            response = requests.post(
                f"{self.nef_url}/api/v1/UEs/associate/path",
                headers=self._get_headers(),
                json={"supi": supi, "path": path_id}
            )
            
            if response.status_code in [200, 201]:
                print(f"✅ Associated UE {supi} with path {path_id}")
                return True
            else:
                print(f"❌ Failed to associate UE {supi}: {response.status_code}")
                return False
        except requests.RequestException as e:
            print(f"❌ Error associating UE: {e}")
            return False
    
    # =========================================================================
    # UE Movement Control
    # =========================================================================
    
    def start_ue_movement(self, supi: str, timeout: int = 60) -> bool:
        """Start movement loop for a UE.
        
        Args:
            supi: UE identifier
            timeout: HTTP request timeout in seconds (default 60 for cold start)
        """
        try:
            response = requests.post(
                f"{self.nef_url}/api/v1/ue_movement/start-loop",
                headers=self._get_headers(),
                json={"supi": supi},
                timeout=timeout  # Extended timeout for thread startup
            )
            
            if response.status_code in [200, 201]:
                print(f"▶️  Started movement for UE {supi}")
                return True
            else:
                print(f"❌ Failed to start UE {supi}: {response.status_code}")
                return False
        except requests.RequestException as e:
            print(f"❌ Error starting UE movement: {e}")
            return False
    
    def stop_ue_movement(self, supi: str) -> bool:
        """Stop movement loop for a UE."""
        try:
            response = requests.post(
                f"{self.nef_url}/api/v1/ue_movement/stop-loop",
                headers=self._get_headers(),
                json={"supi": supi}
            )
            
            if response.status_code in [200, 201]:
                print(f"⏹️  Stopped movement for UE {supi}")
                return True
            else:
                return False
        except requests.RequestException as e:
            return False
    
    def start_all_ues(self, delay_between_starts: float = 3.0) -> int:
        """Start movement for all UEs with staggered timing.
        
        Args:
            delay_between_starts: Seconds between UE starts to prevent lock contention
            
        Returns:
            Count of successfully started UEs
        """
        print(f"\n▶️  Starting {len(self.ues)} UEs (with {delay_between_starts}s delay between starts)...")
        started = 0
        for i, ue in enumerate(self.ues):
            if self.start_ue_movement(ue.supi):
                started += 1
            if i < len(self.ues) - 1:  # No delay after last UE
                time.sleep(delay_between_starts)
        print(f"✅ Started {started}/{len(self.ues)} UEs")
        return started
    
    def stop_all_ues(self) -> int:
        """Stop movement for all UEs. Returns count of successfully stopped UEs."""
        stopped = 0
        for ue in self.ues:
            if self.stop_ue_movement(ue.supi):
                stopped += 1
        return stopped
    
    # =========================================================================
    # Full Scenario Deployment
    # =========================================================================
    
    def deploy(self) -> bool:
        """
        Deploy the complete scenario topology.
        
        Steps:
        1. Authenticate
        2. Create gNB
        3. Generate and create all cells
        4. Generate and create all paths
        5. Generate and create all UEs
        6. Associate UEs with paths
        """
        print("\n" + "=" * 60)
        print(f"🚀 Deploying Scenario: {self.get_metadata().name}")
        print("=" * 60)
        
        # Step 1: Authenticate
        print("\n📡 Authenticating with NEF...")
        if not self.authenticate():
            print("❌ Failed to authenticate. Aborting deployment.")
            return False
        print("✅ Authentication successful")
        
        # Step 2: Create gNB
        print("\n🗼 Creating Base Station...")
        if not self.create_gnb():
            print("⚠️  gNB creation failed, but continuing...")
        
        # Step 3: Generate and create cells
        self.cells = self.generate_cells()
        print(f"\n📡 Creating {len(self.cells)} cells...")
        for cell in self.cells:
            self.create_cell(cell)
            time.sleep(0.2)
        
        # Step 4: Generate and create paths
        print(f"\n📍 Creating mobility paths...")
        self.paths = self.generate_paths()
        path_ids = []
        for path in self.paths:
            path_id = self.create_path(path)
            if path_id:
                path_ids.append(path_id)
            time.sleep(0.2)
        
        # Step 5: Generate and create UEs
        self.ues = self.generate_ues()
        print(f"\n📱 Creating {len(self.ues)} UEs...")
        for ue in self.ues:
            self.create_ue(ue)
            time.sleep(0.2)
        
        # Step 6: Associate UEs with paths
        print("\n🔗 Associating UEs with paths...")
        if path_ids:
            for i, ue in enumerate(self.ues):
                # Distribute UEs across available paths
                path_id = path_ids[i % len(path_ids)]
                self.associate_ue_with_path(ue.supi, path_id)
                time.sleep(0.2)
        
        # Summary
        metadata = self.get_metadata()
        print("\n" + "=" * 60)
        print("✅ Deployment Complete!")
        print("=" * 60)
        print(f"   Cells: {len(self.cells)}")
        print(f"   UEs: {len(self.ues)}")
        print(f"   Paths: {len(self.paths)}")
        print(f"   Area: {metadata.area_km2} km²")
        print(f"   Use Case: {metadata.primary_use_case}")
        print("=" * 60 + "\n")
        
        return True
    
    def save_topology(self, output_path: Path) -> None:
        """Save the scenario topology to a JSON file."""
        topology = {
            "metadata": self.get_metadata().to_dict(),
            "cells": [asdict(c) for c in self.cells],
            "ues": [asdict(u) for u in self.ues],
            "paths": [asdict(p) for p in self.paths]
        }
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w') as f:
            json.dump(topology, f, indent=2, default=str)
        
        print(f"💾 Saved topology to {output_path}")
    
    # =========================================================================
    # Utility Methods
    # =========================================================================
    
    @staticmethod
    def generate_linear_path(
        start_lat: float, 
        start_lon: float,
        end_lat: float,
        end_lon: float,
        num_points: int = 100
    ) -> List[Dict[str, str]]:
        """Generate a linear path between two points."""
        points = []
        for i in range(num_points):
            frac = i / (num_points - 1)
            lat = start_lat + frac * (end_lat - start_lat)
            lon = start_lon + frac * (end_lon - start_lon)
            points.append({
                "latitude": f"{lat:.6f}",
                "longitude": f"{lon:.6f}"
            })
        return points
    
    @staticmethod
    def generate_grid_path(
        center_lat: float,
        center_lon: float,
        grid_size_m: float = 100,
        blocks: int = 5
    ) -> List[Dict[str, str]]:
        """Generate a Manhattan-grid style path."""
        # Approximate degrees per meter at given latitude
        deg_per_m_lat = 1 / 111320
        deg_per_m_lon = 1 / (111320 * math.cos(math.radians(center_lat)))
        
        points = []
        current_lat = center_lat
        current_lon = center_lon
        
        directions = [(1, 0), (0, 1), (-1, 0), (0, -1)]  # N, E, S, W
        
        for block in range(blocks):
            direction = directions[block % 4]
            
            for step in range(int(grid_size_m)):
                current_lat += direction[0] * deg_per_m_lat
                current_lon += direction[1] * deg_per_m_lon
                
                if step % 5 == 0:  # Sample every 5 meters
                    points.append({
                        "latitude": f"{current_lat:.6f}",
                        "longitude": f"{current_lon:.6f}"
                    })
        
        return points
    
    @staticmethod
    def speed_profile_from_mobility(mobility: MobilityType) -> str:
        """Convert mobility type to NEF speed profile."""
        if mobility in [MobilityType.STATIONARY, MobilityType.PEDESTRIAN]:
            return "LOW"
        elif mobility in [MobilityType.URBAN_VEHICLE]:
            return "MEDIUM"
        else:
            return "HIGH"
    
    @staticmethod
    def qos_requirements_from_service(service: ServiceType) -> Dict[str, float]:
        """Get QoS requirements based on service type per 3GPP TS 23.501."""
        requirements = {
            ServiceType.EMBB: {
                "latency_requirement_ms": 50.0,
                "throughput_requirement_mbps": 100.0,
                "reliability_pct": 99.5
            },
            ServiceType.URLLC: {
                "latency_requirement_ms": 1.0,
                "throughput_requirement_mbps": 10.0,
                "reliability_pct": 99.999
            },
            ServiceType.MMTC: {
                "latency_requirement_ms": 1000.0,
                "throughput_requirement_mbps": 0.1,
                "reliability_pct": 99.0
            },
            ServiceType.DEFAULT: {
                "latency_requirement_ms": 100.0,
                "throughput_requirement_mbps": 10.0,
                "reliability_pct": 99.0
            }
        }
        return requirements.get(service, requirements[ServiceType.DEFAULT])


if __name__ == "__main__":
    # Test that base class cannot be instantiated directly
    try:
        scenario = BaseScenario()
    except TypeError as e:
        print(f"✅ BaseScenario correctly prevents instantiation: {e}")
