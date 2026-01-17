#!/usr/bin/env python3
"""
Quick Win: Validate Ping-Pong Prevention
Time: 20-30 minutes (5 min ML + 5 min A3 + analysis)
Impact: PROOF that ping-pong prevention actually works

Creates a UE that rapidly oscillates between cell boundaries.
ML should suppress handovers; A3 should ping-pong.
"""

import sys
import os
import time
import requests
import json
from datetime import datetime
from math import asin, atan2, cos, degrees, radians, sin
from pathlib import Path
from typing import List, Tuple

# Configuration
NEF_BASE_URL = os.environ.get("NEF_URL", "http://localhost:8080")
API_PREFIX = f"{NEF_BASE_URL}/api/v1"
ML_API_PREFIX = f"{API_PREFIX}/ml/ml"
RESULTS_DIR = Path(__file__).parent.parent / "thesis_results" / "pingpong_validation"
TEST_DURATION_SECONDS = 300  # 5 minutes per mode
OSCILLATION_INTERVAL_SECONDS = 10  # Move every 10 seconds


class PingPongValidator:
    """Validates ping-pong prevention by creating deliberate ping-pong scenarios."""
    
    def __init__(self):
        self.results_dir = RESULTS_DIR
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.results_dir / f"validation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        
    def log(self, message: str):
        """Log message to console and file."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_line = f"[{timestamp}] {message}"
        print(log_line)
        
        with open(self.log_file, "a") as f:
            f.write(log_line + "\n")
    
    def section(self, title: str):
        """Print section header."""
        print()
        print("=" * 60)
        print(f" {title}")
        print("=" * 60)
    
    def get_nef_token(self) -> str:
        """Get authentication token from NEF."""
        try:
            response = requests.post(
                f"{API_PREFIX}/login/access-token",
                data={
                    "username": os.environ.get("NEF_USERNAME", "admin@my-email.com"),
                    "password": os.environ.get("NEF_PASSWORD", "pass")
                }
            )
            response.raise_for_status()
            token = response.json()["access_token"]
            self.log(f"✓ Obtained NEF auth token")
            return token
        except Exception as e:
            self.log(f"✗ Failed to get NEF token: {e}")
            sys.exit(1)
    
    def fetch_cells(self, token: str) -> List[dict]:
        """Retrieve configured cells from the NEF."""

        headers = {"Authorization": f"Bearer {token}"}
        try:
            response = requests.get(f"{API_PREFIX}/cells", headers=headers, timeout=5)
            response.raise_for_status()
            cells = response.json() or []
            self.log(f"✓ Retrieved {len(cells)} cell definitions")
            return cells
        except Exception as exc:
            self.log(f"⚠ Failed to load cells: {exc}")
            return []

    # ------------------------------------------------------------------
    # Geodesic helpers for dynamic oscillation points
    # ------------------------------------------------------------------
    @staticmethod
    def _haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Great-circle distance between two latitude/longitude pairs in metres."""

        radius = 6_371_000.0
        d_lat = radians(lat2 - lat1)
        d_lon = radians(lon2 - lon1)
        lat1_rad = radians(lat1)
        lat2_rad = radians(lat2)
        a = (
            sin(d_lat / 2.0) ** 2
            + cos(lat1_rad) * cos(lat2_rad) * sin(d_lon / 2.0) ** 2
        )
        return 2.0 * radius * asin(min(1.0, max(0.0, a)) ** 0.5)

    @staticmethod
    def _bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Initial bearing from (lat1, lon1) to (lat2, lon2) in degrees."""

        lat1_rad = radians(lat1)
        lat2_rad = radians(lat2)
        d_lon = radians(lon2 - lon1)
        y = sin(d_lon) * cos(lat2_rad)
        x = cos(lat1_rad) * sin(lat2_rad) - sin(lat1_rad) * cos(lat2_rad) * cos(d_lon)
        return (degrees(atan2(y, x)) + 360.0) % 360.0

    @staticmethod
    def _destination(lat: float, lon: float, bearing_deg: float, distance_m: float) -> Tuple[float, float]:
        """Return point reached when travelling distance_m towards bearing_deg."""

        radius = 6_371_000.0
        bearing = radians(bearing_deg)
        lat1 = radians(lat)
        lon1 = radians(lon)
        ratio = distance_m / radius

        lat2 = asin(
            sin(lat1) * cos(ratio)
            + cos(lat1) * sin(ratio) * cos(bearing)
        )
        lon2 = lon1 + atan2(
            sin(bearing) * sin(ratio) * cos(lat1),
            cos(ratio) - sin(lat1) * sin(lat2),
        )

        return degrees(lat2), (degrees(lon2) + 540.0) % 360.0 - 180.0

    def determine_pingpong_positions(self, cells: List[dict]) -> Tuple[List[Tuple[float, float]], Tuple[dict, dict]]:
        """Pick two oscillation points anchored to the closest cell pair."""

        viable = [
            cell
            for cell in cells
            if cell.get("latitude") is not None
            and cell.get("longitude") is not None
            and cell.get("radius")
        ]

        if len(viable) < 2:
            return [], ({}, {})

        best_pair: Tuple[float, dict, dict] | None = None
        for idx, cell in enumerate(viable):
            for other in viable[idx + 1 :]:
                distance = self._haversine_distance(
                    cell["latitude"],
                    cell["longitude"],
                    other["latitude"],
                    other["longitude"],
                )
                if best_pair is None or distance < best_pair[0]:
                    best_pair = (distance, cell, other)

        if not best_pair:
            return [], ({}, {})

        distance, cell_a, cell_b = best_pair
        bearing_ab = self._bearing(
            cell_a["latitude"],
            cell_a["longitude"],
            cell_b["latitude"],
            cell_b["longitude"],
        )

        margin = 15.0

        def _offset(radius_value: float) -> float:
            radius_m = max(float(radius_value), margin * 2)
            half_distance = max(distance / 2.0 - margin, margin)
            return max(margin, min(radius_m - margin, half_distance))

        offset_a = _offset(cell_a.get("radius", 75.0))
        offset_b = _offset(cell_b.get("radius", 75.0))

        pos_a = self._destination(
            cell_a["latitude"],
            cell_a["longitude"],
            bearing_ab,
            offset_a,
        )
        pos_b = self._destination(
            cell_b["latitude"],
            cell_b["longitude"],
            (bearing_ab + 180.0) % 360.0,
            offset_b,
        )

        return [pos_a, pos_b], (cell_a, cell_b)

    def create_pingpong_ue(self, ue_id: str, token: str) -> dict:
        """Create a UE at cell boundary (ping-pong prone position)."""
        
        # Position at boundary between antenna_1 and antenna_2
        # Based on NCSRD topology, this is around (250, 250)
        suffix = ue_id[-6:]
        ipv4_octet = int(suffix[-3:]) % 250 + 1
        mac_tail = f"{int(suffix[-2:]):02X}"
        mac_tail2 = f"{(int(suffix[-4:-2]) % 256):02X}"

        ue_data = {
            "supi": ue_id,
            "name": f"UE_{ue_id[-3:]}",
            "description": "Ping-pong validation UE",
            "ip_address_v4": f"10.10.{ipv4_octet}.1",
            "ip_address_v6": f"2001:db8::{ipv4_octet}",
            "mac_address": f"22-00-00-00-{mac_tail2}-{mac_tail}",
            "external_identifier": f"{ue_id}@validation.local",
            "latitude": 37.9942,
            "longitude": 23.8172,
            "speed": "HIGH",
        }
        
        try:
            headers = {"Authorization": f"Bearer {token}"}
            # Ensure stale test UE does not exist
            requests.delete(f"{API_PREFIX}/UEs/{ue_id}", headers=headers, timeout=5)
            response = requests.post(
                f"{API_PREFIX}/UEs",
                json=ue_data,
                headers=headers
            )
            
            if response.status_code in [200, 201]:
                self.log(f"✓ Created UE {ue_id} at cell boundary")
                return ue_data
            else:
                self.log(f"✗ Failed to create UE: {response.status_code} {response.text}")
                return ue_data
        except Exception as e:
            self.log(f"⚠ Error creating UE (may already exist): {e}")
            return ue_data
    
    def oscillate_ue(
        self,
        ue_id: str,
        token: str,
        duration_seconds: int,
        ml_mode: bool,
        ue_template: dict,
        positions: List[Tuple[float, float]],
    ) -> Tuple[int, int]:
        """
        Move UE back and forth across cell boundary.
        
        Returns:
            (handover_count, pingpong_count)
        """
        
        headers = {"Authorization": f"Bearer {token}"}
        
        start_time = datetime.now()
        handover_count = 0
        pingpong_count = 0
        last_antenna = None
        last_handover_time = None
        
        mode_name = "ML" if ml_mode else "A3"
        self.log(f"Starting {mode_name} mode oscillation test for {duration_seconds}s...")
        
        position_idx = 0
        
        while (datetime.now() - start_time).total_seconds() < duration_seconds:
            lat, lon = positions[position_idx]
            position_idx = (position_idx + 1) % len(positions)
            
            # Update UE position
            try:
                payload = {k: v for k, v in ue_template.items() if k != "supi"}
                payload.update({"latitude": lat, "longitude": lon})
                update_response = requests.put(
                    f"{API_PREFIX}/UEs/{ue_id}",
                    json=payload,
                    headers=headers
                )
                
                # Trigger handover decision
                handover_response = requests.post(
                    f"{ML_API_PREFIX}/handover",
                    params={"ue_id": ue_id},
                    headers=headers
                )
                
                if handover_response.status_code == 200:
                    result = handover_response.json()
                    
                    if result.get("handover_applied"):
                        handover_count += 1
                        new_antenna = result.get("target_antenna")
                        
                        # Detect ping-pong (back to previous antenna within 60s)
                        if last_antenna and new_antenna == last_antenna and last_handover_time:
                            time_since_last = (datetime.now() - last_handover_time).total_seconds()
                            if time_since_last < 60:
                                pingpong_count += 1
                                self.log(f"  ⚠ PING-PONG detected: {new_antenna} (after {time_since_last:.1f}s)")
                        
                        self.log(f"  Handover #{handover_count}: → {new_antenna}")
                        last_antenna = new_antenna
                        last_handover_time = datetime.now()
                    
                    elif result.get("reason") == "ping_pong_prevention":
                        self.log(f"  ✓ Ping-pong prevented by ML")
            
            except Exception as e:
                self.log(f"  ⚠ Error during oscillation: {e}")
            
            # Wait before next position change
            time.sleep(OSCILLATION_INTERVAL_SECONDS)
        
        return handover_count, pingpong_count
    
    def set_mode(self, token: str, use_ml: bool):
        """Toggle handover mode via the ML API."""
        try:
            headers = {"Authorization": f"Bearer {token}"}
            response = requests.post(
                f"{ML_API_PREFIX}/mode",
                json={"use_ml": use_ml},
                headers=headers
            )
            if response.status_code == 200:
                mode = response.json().get("mode", "ml" if use_ml else "a3")
                self.log(f"✓ Mode set to {mode}")
            else:
                self.log(f"⚠ Mode toggle returned {response.status_code}: {response.text}")
        except Exception as e:
            self.log(f"⚠ Error toggling mode: {e}")
    
    def run_validation(self):
        """Run full ping-pong validation test."""
        
        self.section("PING-PONG PREVENTION VALIDATION")
        print(f"Test Duration: {TEST_DURATION_SECONDS}s per mode")
        print(f"Oscillation Interval: {OSCILLATION_INTERVAL_SECONDS}s")
        print(f"Expected ML: 1-5 handovers (prevention active)")
        print(f"Expected A3: 15-30 handovers (ping-pong active)")
        print()
        
        # Get authentication
        token = self.get_nef_token()
        
        cells = self.fetch_cells(token)
        positions, cell_pair = self.determine_pingpong_positions(cells)

        if not positions:
            # Fallback to legacy hard-coded coordinates (may be outside coverage)
            positions = [
                (37.9963, 23.8186),
                (37.9975, 23.8185),
            ]
            self.log(
                "⚠ Falling back to static oscillation points; handover volume may be limited"
            )
        else:
            cell_names = (
                cell_pair[0].get("name") or cell_pair[0].get("cell_id"),
                cell_pair[1].get("name") or cell_pair[1].get("cell_id"),
            )
            self.log(
                f"Using cells {cell_names[0]} and {cell_names[1]} for boundary oscillation"
            )
            for idx, (lat, lon) in enumerate(positions, start=1):
                self.log(f"  Oscillation point {idx}: ({lat:.6f}, {lon:.6f})")

        # Test 1: ML Mode
        self.section("Test 1/2: ML Mode (Ping-Pong Prevention)")
        self.set_mode(token, True)
        time.sleep(2)
        
        ml_ue_id = "202010000999001"
        ml_template = self.create_pingpong_ue(ml_ue_id, token)
        time.sleep(2)
        
        ml_handovers, ml_pingpong = self.oscillate_ue(
            ml_ue_id,
            token,
            TEST_DURATION_SECONDS,
            ml_mode=True,
            ue_template=ml_template,
            positions=positions,
        )
        
        self.log(f"\nML Mode Results:")
        self.log(f"  Handovers: {ml_handovers}")
        self.log(f"  Ping-pong events: {ml_pingpong}")
        
        # Cooldown
        time.sleep(10)
        
        # Test 2: A3 Mode
        self.section("Test 2/2: A3 Baseline Mode")
        self.set_mode(token, False)
        time.sleep(2)
        
        a3_ue_id = "202010000999002"
        a3_template = self.create_pingpong_ue(a3_ue_id, token)
        time.sleep(2)
        
        a3_handovers, a3_pingpong = self.oscillate_ue(
            a3_ue_id,
            token,
            TEST_DURATION_SECONDS,
            ml_mode=False,
            ue_template=a3_template,
            positions=positions,
        )
        
        self.log(f"\nA3 Mode Results:")
        self.log(f"  Handovers: {a3_handovers}")
        self.log(f"  Ping-pong events: {a3_pingpong}")
        
        # Analysis
        self.section("VALIDATION RESULTS")
        
        reduction_pct = ((a3_handovers - ml_handovers) / a3_handovers * 100) if a3_handovers > 0 else 0
        
        results = {
            "timestamp": datetime.now().isoformat(),
            "test_duration_seconds": TEST_DURATION_SECONDS,
            "ml_mode": {
                "handovers": ml_handovers,
                "pingpong_events": ml_pingpong,
            },
            "a3_mode": {
                "handovers": a3_handovers,
                "pingpong_events": a3_pingpong,
            },
            "reduction_percentage": round(reduction_pct, 1),
        }
        
        # Save results
        results_file = self.results_dir / "validation_results.json"
        with open(results_file, "w") as f:
            json.dump(results, f, indent=2)
        
        self.log(f"\nHandover Reduction: {reduction_pct:.1f}%")
        
        # Verdict
        if ml_handovers < 5 and a3_handovers > 10:
            self.log("\n✅ SUCCESS: Ping-pong prevention is EFFECTIVE")
            self.log(f"   ML suppressed rapid handovers ({ml_handovers}) while A3 ping-ponged ({a3_handovers})")
            verdict = "PASS"
        elif ml_handovers < a3_handovers / 2:
            self.log("\n✅ PARTIAL SUCCESS: ML reduced handovers significantly")
            self.log(f"   ML: {ml_handovers} vs A3: {a3_handovers}")
            verdict = "PARTIAL_PASS"
        else:
            self.log("\n❌ FAILURE: Ping-pong prevention not working as expected")
            self.log(f"   ML: {ml_handovers} handovers (expected < 5)")
            self.log(f"   A3: {a3_handovers} handovers (expected > 15)")
            verdict = "FAIL"
        
        results["verdict"] = verdict
        
        # Update results file
        with open(results_file, "w") as f:
            json.dump(results, f, indent=2)
        
        self.log(f"\n📊 Results saved to: {results_file}")
        self.log(f"📝 Full log: {self.log_file}")

        # Restore ML mode for subsequent experiments
        self.set_mode(token, True)

        print()
        print("=" * 60)
        print("Use these results in your defense:")
        print(f"  - ML handovers: {ml_handovers}")
        print(f"  - A3 handovers: {a3_handovers}")
        print(f"  - Reduction: {reduction_pct:.1f}%")
        print(f"  - Verdict: {verdict}")
        print("=" * 60)
        print()


def main():
    """Main entry point."""
    
    # Check if NEF is accessible
    try:
        response = requests.get(f"{API_PREFIX}/health", timeout=5)
        if response.status_code != 200:
            print(f"⚠ Warning: NEF health check returned {response.status_code}")
    except Exception as e:
        print(f"❌ Error: Cannot reach NEF at {NEF_BASE_URL}")
        print(f"   {e}")
        print("\nPlease ensure NEF emulator is running:")
        print("  cd 5g-network-optimization")
        print("  docker compose --profile ml up -d")
        sys.exit(1)
    
    # Run validation
    validator = PingPongValidator()
    validator.run_validation()


if __name__ == "__main__":
    main()
