#!/usr/bin/env python3
"""
Enhanced Scenario Experiment Runner.

This script runs comparative ML vs A3 experiments using the enhanced
real-life scenarios for presentation-quality results.

Features:
- Multiple scenario support (smart_city, highway, etc.)
- Automated metrics collection
- Comparative visualization generation
- Presentation-ready output

Usage:
    python scripts/run_enhanced_experiment.py --scenario smart_city --duration 10
    python scripts/run_enhanced_experiment.py --scenario highway --duration 15
    python scripts/run_enhanced_experiment.py --list-scenarios
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# Add paths for imports
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.scenarios.base_scenario import BaseScenario, ScenarioMetadata
from scripts.scenarios.smart_city_downtown import SmartCityDowntownScenario
from scripts.scenarios.highway_handover import HighwayHandoverScenario


# ============================================================================
# Scenario Registry
# ============================================================================

SCENARIOS = {
    "smart_city": {
        "class": SmartCityDowntownScenario,
        "description": "Dense urban deployment (15 cells, 50 UEs)",
        "recommended_duration": 15,
    },
    "highway": {
        "class": HighwayHandoverScenario,
        "description": "High-speed vehicle handover (8 cells, 10 vehicles at 120 km/h)",
        "recommended_duration": 10,
    },
}


# ============================================================================
# Helper Functions
# ============================================================================

def list_scenarios() -> None:
    """Print available scenarios."""
    print("\n" + "=" * 70)
    print("Available Enhanced Scenarios")
    print("=" * 70)
    
    for name, info in SCENARIOS.items():
        status = "✅ Ready"
        print(f"\n  {name}")
        print(f"    Status: {status}")
        print(f"    Description: {info['description']}")
        print(f"    Recommended duration: {info['recommended_duration']} minutes")
    
    print("\n" + "=" * 70 + "\n")


def get_scenario(name: str) -> Optional[BaseScenario]:
    """Get a scenario instance by name."""
    if name not in SCENARIOS:
        print(f"❌ Unknown scenario: {name}")
        list_scenarios()
        return None
    
    scenario_class = SCENARIOS[name]["class"]
    if scenario_class is None:
        print(f"❌ Scenario '{name}' is not yet implemented.")
        return None
    
    return scenario_class()


def wait_for_services(nef_url: Optional[str] = None,
                       ml_url: Optional[str] = None,
                       max_attempts: int = 30) -> bool:
    """Wait for NEF and ML services to be ready."""
    import os
    import requests
    
    nef_url = nef_url or os.environ.get("NEF_URL")
    ml_url = ml_url or os.environ.get("ML_URL")
    if not nef_url or not ml_url:
        raise ValueError("NEF_URL and ML_URL must be set")
    
    print("⏳ Waiting for services to be ready...")
    
    for attempt in range(max_attempts):
        try:
            # Check NEF
            nef_resp = requests.get(f"{nef_url}/docs", timeout=5)
            if nef_resp.status_code != 200:
                raise RuntimeError(f"NEF not ready: HTTP {nef_resp.status_code}")
            
            # Check ML service
            ml_resp = requests.get(f"{ml_url}/api/health", timeout=5)
            if ml_resp.status_code != 200:
                raise RuntimeError(f"ML service not ready: HTTP {ml_resp.status_code}")
            
            print("✅ All services ready")
            return True
            
        except (requests.RequestException, RuntimeError) as exc:
            print(f"   Attempt {attempt + 1}/{max_attempts}: {exc}")
            time.sleep(2)
    
    print("❌ Services failed to start")
    return False


def collect_prometheus_metrics(output_path: Path, mode: str) -> Dict:
    """Collect metrics from Prometheus."""
    import requests
    
    import os
    prom_url = os.environ.get("PROMETHEUS_URL")
    if not prom_url:
        raise ValueError("PROMETHEUS_URL must be set")
    metrics = {}
    
    queries = {
        "total_handovers": 'sum(nef_handover_decisions_total{outcome="applied"})',
        "skipped_handovers": 'sum(nef_handover_decisions_total{outcome="skipped"})',
        "pingpong_suppressions": "sum(ml_pingpong_suppressions_total)",
        "qos_compliance_ok": 'sum(nef_handover_compliance_total{outcome="ok"})',
        "qos_compliance_failed": 'sum(nef_handover_compliance_total{outcome="failed"})',
        "avg_confidence": "avg(ml_prediction_confidence_avg)",
    }
    
    for name, query in queries.items():
        try:
            resp = requests.get(
                f"{prom_url}/api/v1/query",
                params={"query": query},
                timeout=10
            )
            if resp.status_code == 200:
                result = resp.json()
                if result["data"]["result"]:
                    metrics[name] = float(result["data"]["result"][0]["value"][1])
                else:
                    metrics[name] = 0
        except requests.RequestException as e:
            raise RuntimeError(f"Failed to query Prometheus metric {name}: {e}") from e
    
    # Save metrics
    metrics_file = output_path / f"{mode}_mode_metrics.json"
    with open(metrics_file, 'w') as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "mode": mode,
            "metrics": metrics
        }, f, indent=2)
    
    return metrics


def generate_visualizations(output_dir: Path) -> bool:
    """Generate comparison visualizations using the existing script."""
    vis_script = REPO_ROOT / "scripts" / "compare_ml_vs_a3_visual.py"
    
    ml_metrics = output_dir / "metrics" / "ml_mode_metrics.json"
    a3_metrics = output_dir / "metrics" / "a3_mode_metrics.json"
    
    if not ml_metrics.exists():
        print("⚠️  ML metrics not found, skipping visualization.")
        return False
    
    if vis_script.exists() and a3_metrics.exists():
        print("📊 Generating comparison visualizations...")
        try:
            result = subprocess.run(
                [sys.executable, str(vis_script),
                 "--ml-metrics", str(ml_metrics),
                 "--a3-metrics", str(a3_metrics),
                 "--output", str(output_dir)],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                print("✅ Visualizations generated")
                return True
            else:
                print(f"⚠️  Visualization generation failed: {result.stderr[:200]}")
                return False
        except OSError as e:
            print(f"⚠️  Error generating visualizations: {e}")
            return False
    else:
        print("ℹ️  Visualization script or A3 metrics not available")
        return False


def cleanup_docker(compose_file: Path) -> None:
    """Ensure Docker Compose is stopped and clean."""
    print("🧹 Cleaning up Docker environment...")
    subprocess.run(
        ["docker-compose", "-f", str(compose_file), "down", "-v"],
        capture_output=True
    )
    time.sleep(5)


# ============================================================================
# Main Experiment Runner
# ============================================================================

def run_experiment(
    scenario_name: str,
    duration_minutes: int,
    output_dir: Path,
    skip_a3: bool = False
) -> bool:
    """
    Run a complete ML vs A3 comparative experiment.
    
    Steps:
    1. Deploy scenario topology
    2. Run ML mode experiment
    3. Run A3 mode experiment (if not skipped)
    4. Generate comparison visualizations
    5. Create summary report
    """
    
    # Get scenario
    scenario = get_scenario(scenario_name)
    if not scenario:
        return False
    
    metadata = scenario.get_metadata()
    
    print("\n" + "=" * 70)
    print(f"🚀 Enhanced Experiment: {metadata.name}")
    print("=" * 70)
    print(f"   Cells: {metadata.num_cells}")
    print(f"   UEs: {metadata.num_ues}")
    print(f"   Area: {metadata.area_km2} km²")
    print(f"   Duration: {duration_minutes} minutes per mode")
    print(f"   Output: {output_dir}")
    print("=" * 70 + "\n")
    
    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "metrics").mkdir(exist_ok=True)
    (output_dir / "logs").mkdir(exist_ok=True)
    
    # Save scenario metadata
    scenario.save_topology(output_dir / "topology.json")
    
    # ================================================================
    # Phase 1: ML Mode Experiment
    # ================================================================
    
    print("\n" + "=" * 50)
    print("Phase 1: ML Mode Experiment")
    print("=" * 50)
    
    # Start Docker Compose in ML mode
    compose_file = REPO_ROOT / "5g-network-optimization" / "docker-compose.yml"
    
    print("Starting Docker Compose in ML mode...")
    env = os.environ.copy()
    env["ML_HANDOVER_ENABLED"] = "1"
    env["COMPOSE_PROFILES"] = "ml"
    env["ML_LOCAL"] = "ml"
    
    subprocess.run(
        ["docker-compose", "-f", str(compose_file), "up", "-d"],
        env=env,
        capture_output=True
    )
    
    # Wait for services
    if not wait_for_services():
        print("❌ Services failed to start. Aborting.")
        return False
    
    # Wait for ML model to be ready
    print("⏳ Waiting for ML model initialization...")
    import requests
    ml_url = os.environ.get("ML_URL")
    if not ml_url:
        raise ValueError("ML_URL must be set")
    model_ready = False
    for attempt in range(60):
        try:
            resp = requests.get(f"{ml_url}/api/model-health", timeout=5)
            resp.raise_for_status()
            if resp.json().get("ready"):
                print("✅ ML model ready")
                model_ready = True
                break
        except (requests.RequestException, ValueError) as exc:
            print(f"   Model readiness attempt {attempt + 1}/60: {exc}")
        time.sleep(5)
    if not model_ready:
        print("❌ ML model did not report ready. Aborting.")
        return False
    
    # Deploy scenario
    print("\n📍 Deploying scenario topology...")
    if not scenario.deploy():
        print("❌ Scenario deployment failed. Aborting.")
        return False
    
    # Start UE movement
    print("\n▶️  Starting UE movement...")
    scenario.start_all_ues()
    
    # Run experiment
    print(f"\n⏱️  Running ML experiment for {duration_minutes} minutes...")
    start_time = datetime.now()
    duration_seconds = duration_minutes * 60
    
    while True:
        elapsed = (datetime.now() - start_time).total_seconds()
        if elapsed >= duration_seconds:
            break
        remaining = int(duration_seconds - elapsed)
        print(f"   Progress: {int(elapsed)}s / {duration_seconds}s ({remaining}s remaining)")
        time.sleep(30)
    
    print("✅ ML experiment complete")
    
    # Collect metrics
    ml_metrics = collect_prometheus_metrics(output_dir / "metrics", "ml")
    
    # Stop UE movement
    scenario.stop_all_ues()
    
    # Stop ML mode
    print("\n⏹️  Stopping ML mode...")
    subprocess.run(
        ["docker-compose", "-f", str(compose_file), "down"],
        capture_output=True
    )
    time.sleep(10)
    
    # ================================================================
    # Phase 2: A3 Mode Experiment (if not skipped)
    # ================================================================
    
    a3_metrics = None
    if not skip_a3:
        print("\n" + "=" * 50)
        print("Phase 2: A3 Mode Experiment")
        print("=" * 50)
        
        # Start Docker Compose in A3 mode
        print("Starting Docker Compose in A3 mode...")
        env["ML_HANDOVER_ENABLED"] = "0"
        
        subprocess.run(
            ["docker-compose", "-f", str(compose_file), "up", "-d"],
            env=env,
            capture_output=True
        )
        
        # Wait for services (NEF only - ML service may not be available in A3 mode)
        print("⏳ Waiting for NEF service...")
        import requests
        nef_ready = False
        for attempt in range(30):
            try:
                nef_url = os.environ.get("NEF_URL")
                if not nef_url:
                    raise RuntimeError("NEF_URL must be set")
                resp = requests.get(nef_url + "/docs", timeout=5)
                if resp.status_code == 200:
                    nef_ready = True
                    print("✅ NEF service ready")
                    break
            except (requests.RequestException, RuntimeError) as exc:
                print(f"   Attempt {attempt + 1}/30: {exc}")
                time.sleep(2)
                continue
            print(f"   Attempt {attempt + 1}/30...")
            time.sleep(2)
        
        if not nef_ready:
            print("❌ NEF failed to start for A3 mode")
            return False
        
        # Deploy scenario (fresh deployment)
        scenario2 = get_scenario(scenario_name)
        time.sleep(5)
        if scenario2 is None or not scenario2.deploy():
            print("❌ Scenario deployment failed for A3 mode")
            return False
        scenario2.start_all_ues()
        
        # Run experiment
        print(f"\n⏱️  Running A3 experiment for {duration_minutes} minutes...")
        start_time = datetime.now()
        duration_seconds = duration_minutes * 60
        
        while True:
            elapsed = (datetime.now() - start_time).total_seconds()
            if elapsed >= duration_seconds:
                break
            remaining = int(duration_seconds - elapsed)
            print(f"   Progress: {int(elapsed)}s / {duration_seconds}s ({remaining}s remaining)")
            time.sleep(30)
        
        print("✅ A3 experiment complete")
        
        # Collect metrics
        a3_metrics = collect_prometheus_metrics(output_dir / "metrics", "a3")
        
        # Stop A3 mode
        scenario2.stop_all_ues()
        subprocess.run(
            ["docker-compose", "-f", str(compose_file), "down"],
            capture_output=True
        )
    
    # ================================================================
    # Phase 3: Generate Summary
    # ================================================================
    
    print("\n" + "=" * 50)
    print("Phase 3: Generating Summary")
    print("=" * 50)
    
    # Create summary report
    summary = {
        "experiment": {
            "scenario": scenario_name,
            "description": metadata.description,
            "cells": metadata.num_cells,
            "ues": metadata.num_ues,
            "duration_minutes": duration_minutes,
            "timestamp": datetime.now().isoformat()
        },
        "ml_metrics": ml_metrics,
        "a3_metrics": a3_metrics
    }
    
    with open(output_dir / "experiment_summary.json", 'w') as f:
        json.dump(summary, f, indent=2)
    
    # Generate visualizations if both metrics are available
    if a3_metrics:
        generate_visualizations(output_dir)
    
    # Print summary
    print("\n" + "=" * 70)
    print("📊 Experiment Results Summary")
    print("=" * 70)
    print(f"\nScenario: {metadata.name}")
    print(f"Cells: {metadata.num_cells}, UEs: {metadata.num_ues}")
    print(f"\nML Mode Results:")
    print(f"  Total Handovers: {ml_metrics.get('total_handovers', 'N/A')}")
    print(f"  Ping-Pong Suppressions: {ml_metrics.get('pingpong_suppressions', 'N/A')}")
    print(f"  QoS Compliance: {ml_metrics.get('qos_compliance_ok', 'N/A')} passed")
    
    if a3_metrics:
        print(f"\nA3 Mode Results:")
        print(f"  Total Handovers: {a3_metrics.get('total_handovers', 'N/A')}")
    
    print(f"\n📁 Results saved to: {output_dir}")
    print("=" * 70 + "\n")
    
    return True


# ============================================================================
# CLI Entry Point
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Run enhanced scenario experiments for presentation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_enhanced_experiment.py --scenario smart_city --duration 15
  python run_enhanced_experiment.py --scenario highway --duration 10
  python run_enhanced_experiment.py --list-scenarios
        """
    )
    
    parser.add_argument(
        "--scenario",
        type=str,
        help="Scenario to run (use --list-scenarios to see options)"
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=10,
        help="Duration per mode in minutes (default: 10)"
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Output directory (default: thesis_results/<scenario>_<timestamp>)"
    )
    parser.add_argument(
        "--skip-a3",
        action="store_true",
        help="Skip A3 mode experiment (ML only)"
    )
    parser.add_argument(
        "--list-scenarios",
        action="store_true",
        help="List available scenarios"
    )
    
    args = parser.parse_args()
    
    if args.list_scenarios:
        list_scenarios()
        return 0
    
    if not args.scenario:
        parser.print_help()
        print("\n❌ Error: --scenario is required (or use --list-scenarios)")
        return 1
    
    # Set output directory
    if args.output:
        output_dir = Path(args.output)
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = REPO_ROOT / "thesis_results" / f"{args.scenario}_{timestamp}"
    
    # Run experiment
    success = run_experiment(
        scenario_name=args.scenario,
        duration_minutes=args.duration,
        output_dir=output_dir,
        skip_a3=args.skip_a3
    )
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
