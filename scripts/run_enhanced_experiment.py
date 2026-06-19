#!/usr/bin/env python3
"""
Enhanced Scenario Experiment Runner.

This script runs comparative handover policy experiments using the enhanced
scenario implementations. Treat outputs as thesis evidence only after
preflight and post-run validation.

Features:
- Multiple scenario support (smart_city, highway, etc.)
- Automated metrics collection
- Comparative visualization generation
- Fresh-output guard to prevent stale result contamination

Usage:
    python scripts/run_enhanced_experiment.py --env-file 5g-network-optimization/.env --scenario smart_city --duration 10
    python scripts/run_enhanced_experiment.py --env-file 5g-network-optimization/.env --scenario highway --duration 15
    python scripts/run_enhanced_experiment.py --list-scenarios
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Type, TypedDict, cast

# Add paths for imports
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.scenarios.base_scenario import BaseScenario
from scripts.scenarios.smart_city_downtown import SmartCityDowntownScenario
from scripts.scenarios.highway_handover import (
    DenseHighwayV2Scenario,
    DenseHighwayHandoverScenario,
    HighwayHandoverScenario,
    ModerateHighwayV2Scenario,
    SparseHighwayV2Scenario,
)


# ============================================================================
# Scenario Registry
# ============================================================================

class ScenarioInfo(TypedDict):
    """Metadata for an enhanced experiment scenario entry."""

    class_: Type[BaseScenario]
    description: str
    recommended_duration: int


SCENARIOS: Dict[str, ScenarioInfo] = {
    "smart_city": {
        "class_": SmartCityDowntownScenario,
        "description": "Dense urban deployment (15 cells, 50 UEs)",
        "recommended_duration": 15,
    },
    "highway": {
        "class_": HighwayHandoverScenario,
        "description": "High-speed vehicle handover (8 cells, 10 vehicles at 80-150 km/h)",
        "recommended_duration": 10,
    },
    "highway_dense": {
        "class_": DenseHighwayHandoverScenario,
        "description": (
            "Dense high-speed candidate-complexity handover "
            "(24 cells, 10 vehicles at 80-150 km/h)"
        ),
        "recommended_duration": 10,
    },
    "highway_sparse_v2": {
        "class_": SparseHighwayV2Scenario,
        "description": "Physical 10 km highway with 8 directional cells",
        "recommended_duration": 10,
    },
    "highway_moderate_v2": {
        "class_": ModerateHighwayV2Scenario,
        "description": "Physical 10 km highway with 16 directional cells",
        "recommended_duration": 10,
    },
    "highway_dense_v2": {
        "class_": DenseHighwayV2Scenario,
        "description": "Physical 10 km highway with 24 directional cells",
        "recommended_duration": 10,
    },
}

DOCKER_COMPOSE_CMD = ["docker", "compose"]
SUPPORTED_LIVE_POLICIES = (
    "ml",
    "a3",
    "hybrid",
    "fixed_a3_baseline",
    "tuned_a3_baseline",
    "complexity_aware_ml_a3",
)
POLICIES_REQUIRING_ML = {"ml", "hybrid", "complexity_aware_ml_a3"}
POLICIES_REQUIRING_TUNED_A3 = {"tuned_a3_baseline", "complexity_aware_ml_a3"}
LIVE_TUNED_A3_CONTAINER_CONFIG = "/opt/tuned-a3-config/tuned_a3_config.json"


@dataclass(frozen=True)
class PolicyRunPlan:
    """One live policy phase in a shared-scenario comparison run."""

    policy: str
    scenario: str
    seed: int
    duration_minutes: int
    requires_ml_service: bool
    tuned_a3_config: Optional[str] = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "policy": self.policy,
            "scenario": self.scenario,
            "seed": self.seed,
            "duration_minutes": self.duration_minutes,
            "requires_ml_service": self.requires_ml_service,
            "tuned_a3_config": self.tuned_a3_config,
        }


# ============================================================================
# Helper Functions
# ============================================================================

def is_placeholder_value(value: Optional[str]) -> bool:
    """Return True for empty or template-like secret values."""
    if not value:
        return True
    normalized = value.lower()
    return (
        "change-me" in normalized
        or "changeme" in normalized
        or normalized.startswith("<set-")
        or normalized.startswith("your-")
        or normalized in {"password", "secret", "token"}
    )


def list_scenarios() -> None:
    """Print available scenarios."""
    print("\n" + "=" * 70)
    print("Available Enhanced Scenarios")
    print("=" * 70)
    
    for name, info in SCENARIOS.items():
        status = "Registered"
        print(f"\n  {name}")
        print(f"    Status: {status}")
        print(f"    Description: {info['description']}")
        print(f"    Recommended duration: {info['recommended_duration']} minutes")
    
    print("\n" + "=" * 70 + "\n")


def normalize_runtime_env() -> None:
    """Accept the same public URL env vars as the shell experiment runner."""
    public_defaults = {
        "NEF_SCHEME": "http",
        "NEF_HOST": "localhost",
        "NEF_PORT": os.environ.get("NGINX_HTTP", "8080"),
        "ML_BASE_URL": "http://localhost:5050",
        "PROMETHEUS_URL": "http://localhost:9090",
    }
    for name, value in public_defaults.items():
        if not os.environ.get(name):
            os.environ[name] = value
            print(f"ℹ️  {name} not set; using documented local default.")

    if not os.environ.get("NEF_URL"):
        scheme = os.environ.get("NEF_SCHEME")
        host = os.environ.get("NEF_HOST")
        port = os.environ.get("NEF_PORT")
        if scheme and host and port:
            os.environ["NEF_URL"] = f"{scheme}://{host}:{port}"

    if not os.environ.get("ML_URL") and os.environ.get("ML_BASE_URL"):
        os.environ["ML_URL"] = os.environ["ML_BASE_URL"]

    if is_placeholder_value(os.environ.get("NEF_USERNAME")):
        first_superuser = os.environ.get("FIRST_SUPERUSER")
        if first_superuser is not None and not is_placeholder_value(first_superuser):
            os.environ["NEF_USERNAME"] = first_superuser

    if is_placeholder_value(os.environ.get("NEF_PASSWORD")):
        first_password = os.environ.get("FIRST_SUPERUSER_PASSWORD")
        if first_password is not None and not is_placeholder_value(first_password):
            os.environ["NEF_PASSWORD"] = first_password

    first_superuser = os.environ.get("FIRST_SUPERUSER")
    first_password = os.environ.get("FIRST_SUPERUSER_PASSWORD")
    nef_username = os.environ.get("NEF_USERNAME")
    nef_password = os.environ.get("NEF_PASSWORD")
    if (
        first_superuser
        and first_password
        and nef_username == first_superuser
        and nef_password
        and nef_password != first_password
    ):
        raise ValueError(
            "NEF_PASSWORD differs from FIRST_SUPERUSER_PASSWORD while "
            "NEF_USERNAME equals FIRST_SUPERUSER. The NEF emulator seeds that "
            "user from FIRST_SUPERUSER_PASSWORD; update NEF_PASSWORD or use a "
            "different NEF_USERNAME."
        )


def load_env_file(env_file: Path) -> None:
    """Load simple KEY=VALUE env files without printing secret values."""
    if not env_file.exists():
        print(f"⚠️  Env file not found: {env_file}; using shell environment only.")
        return

    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key and key.replace("_", "").isalnum() and key[0].isalpha():
            os.environ.setdefault(key, value)


def get_scenario(name: str, *, seed: int = 42) -> Optional[BaseScenario]:
    """Get a scenario instance by name."""
    if name not in SCENARIOS:
        print(f"❌ Unknown scenario: {name}")
        list_scenarios()
        return None
    
    scenario_class = SCENARIOS[name]["class_"]
    return scenario_class(seed=seed)


def parse_policy_list(raw_policies: Optional[str], *, skip_a3: bool = False) -> List[str]:
    """Parse and validate an explicit live policy sequence."""
    if raw_policies is None:
        return ["ml"] if skip_a3 else ["ml", "a3"]

    policies = [
        policy.strip()
        for policy in raw_policies.split(",")
        if policy.strip()
    ]
    if not policies:
        raise ValueError("--policies must include at least one policy")

    unknown = sorted(set(policies).difference(SUPPORTED_LIVE_POLICIES))
    if unknown:
        raise ValueError(
            "unsupported policy value(s): "
            + ", ".join(unknown)
            + f". Supported: {', '.join(SUPPORTED_LIVE_POLICIES)}"
        )

    duplicates = sorted({policy for policy in policies if policies.count(policy) > 1})
    if duplicates:
        raise ValueError("duplicate policies are not allowed: " + ", ".join(duplicates))

    return policies


def validate_policy_requirements(
    policies: Sequence[str],
    *,
    tuned_a3_config: Optional[Path] = None,
) -> Optional[Path]:
    """Validate policy-specific config before Docker or experiment startup."""
    if not POLICIES_REQUIRING_TUNED_A3.intersection(policies):
        return None

    candidate = tuned_a3_config
    if candidate is None and os.environ.get("TUNED_A3_CONFIG_PATH"):
        candidate = Path(os.environ["TUNED_A3_CONFIG_PATH"])
    if candidate is None:
        required_policies = ", ".join(
            sorted(POLICIES_REQUIRING_TUNED_A3.intersection(policies))
        )
        raise ValueError(
            f"{required_policies} requires --tuned-a3-config or TUNED_A3_CONFIG_PATH"
        )

    candidate = candidate.expanduser().resolve()
    if not candidate.is_file():
        raise ValueError(f"tuned A3 config does not exist: {candidate}")

    data = json.loads(candidate.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"tuned A3 config must be a JSON object: {candidate}")
    params = data.get("selected_parameters") or data.get("parameters")
    if not isinstance(params, dict):
        raise ValueError(
            f"tuned A3 config must contain selected_parameters: {candidate}"
        )
    required = {"a3_offset_db", "hysteresis_db", "time_to_trigger_s", "cooldown_s"}
    missing = sorted(required.difference(params))
    if missing:
        raise ValueError(
            "tuned A3 selected_parameters missing required keys: "
            + ", ".join(missing)
        )
    return candidate


def build_policy_run_plan(
    *,
    scenario_name: str,
    duration_minutes: int,
    seed: int,
    policies: Sequence[str],
    tuned_a3_config: Optional[Path],
) -> List[PolicyRunPlan]:
    """Build a deterministic policy sequence for a live comparison run."""
    unknown = sorted(set(policies).difference(SUPPORTED_LIVE_POLICIES))
    if unknown:
        raise ValueError(
            "unsupported policy value(s): "
            + ", ".join(unknown)
            + f". Supported: {', '.join(SUPPORTED_LIVE_POLICIES)}"
        )
    duplicates = sorted({policy for policy in policies if list(policies).count(policy) > 1})
    if duplicates:
        raise ValueError("duplicate policies are not allowed: " + ", ".join(duplicates))

    resolved_tuned_config = validate_policy_requirements(
        policies,
        tuned_a3_config=tuned_a3_config,
    )
    return [
        PolicyRunPlan(
            policy=policy,
            scenario=scenario_name,
            seed=seed,
            duration_minutes=duration_minutes,
            requires_ml_service=policy in POLICIES_REQUIRING_ML,
            tuned_a3_config=(
                str(resolved_tuned_config)
                if policy in POLICIES_REQUIRING_TUNED_A3 and resolved_tuned_config
                else None
            ),
        )
        for policy in policies
    ]


def write_live_run_plan(output_dir: Path, plan: Sequence[PolicyRunPlan]) -> Path:
    """Write the planned live policy sequence without starting services."""
    path = output_dir / "live_experiment_plan.json"
    path.write_text(
        json.dumps([entry.to_dict() for entry in plan], indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return path


def stage_tuned_a3_config_for_live_run(
    output_dir: Path,
    plan: Sequence[PolicyRunPlan],
) -> List[PolicyRunPlan]:
    """Copy tuned A3 config into the live output and record that stable path.

    The source path provided on the CLI is a host path. The tuned NEF phase
    mounts the staged copy into the container through a generated Compose
    override, while validation reads the output-contained host copy.
    """
    staged_config: Optional[Path] = None
    staged_plan: List[PolicyRunPlan] = []

    for entry in plan:
        if entry.policy not in POLICIES_REQUIRING_TUNED_A3:
            staged_plan.append(entry)
            continue
        if not entry.tuned_a3_config:
            staged_plan.append(entry)
            continue

        if staged_config is None:
            source = Path(entry.tuned_a3_config).expanduser().resolve()
            config_dir = output_dir / "config"
            config_dir.mkdir(parents=True, exist_ok=True)
            staged_config = (config_dir / "tuned_a3_config.json").resolve()
            if source != staged_config:
                shutil.copy2(source, staged_config)
            else:
                staged_config.touch(exist_ok=True)

        staged_plan.append(replace(entry, tuned_a3_config=str(staged_config)))

    return staged_plan


def write_tuned_a3_compose_override(
    output_dir: Path,
    host_config_path: Path,
) -> Path:
    """Write a phase-local Compose override mounting the tuned config read-only."""
    override_path = output_dir / "logs" / "tuned_a3_baseline.compose.override.yml"
    override_path.parent.mkdir(parents=True, exist_ok=True)
    host_config = host_config_path.expanduser().resolve()
    volume_spec = f"{host_config}:{LIVE_TUNED_A3_CONTAINER_CONFIG}:ro"
    override_path.write_text(
        "\n".join(
            [
                "services:",
                "  nef-emulator:",
                "    environment:",
                f"      - TUNED_A3_CONFIG_PATH={LIVE_TUNED_A3_CONTAINER_CONFIG}",
                "    volumes:",
                f"      - {json.dumps(volume_spec)}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return override_path


def compose_file_args(compose_files: Sequence[Path]) -> List[str]:
    """Build repeated ``-f`` arguments for Docker Compose."""
    args: List[str] = []
    for compose_file in compose_files:
        args.extend(["-f", str(compose_file)])
    return args


def wait_for_services(nef_url: Optional[str] = None,
                       ml_url: Optional[str] = None,
                       max_attempts: int = 30) -> bool:
    """Wait for NEF and ML services to be ready."""
    import os
    import requests  # type: ignore[import-untyped]
    
    nef_url = nef_url or os.environ.get("NEF_URL")
    ml_url = ml_url or os.environ.get("ML_URL") or os.environ.get("ML_BASE_URL")
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


def wait_for_nef_service(
    nef_url: Optional[str] = None,
    *,
    max_attempts: int = 30,
) -> bool:
    """Wait for the shared NEF only."""
    import requests  # type: ignore[import-untyped]

    nef_url = nef_url or os.environ.get("NEF_URL")
    if not nef_url:
        raise ValueError("NEF_URL must be set")

    print("⏳ Waiting for NEF service...")
    for attempt in range(max_attempts):
        try:
            resp = requests.get(f"{nef_url}/docs", timeout=5)
            if resp.status_code == 200:
                print("✅ NEF service ready")
                return True
            raise RuntimeError(f"NEF not ready: HTTP {resp.status_code}")
        except (requests.RequestException, RuntimeError) as exc:
            print(f"   Attempt {attempt + 1}/{max_attempts}: {exc}")
            time.sleep(2)

    print("❌ NEF failed to start")
    return False


def wait_for_ml_model_ready(
    ml_url: Optional[str] = None,
    *,
    max_attempts: int = 60,
) -> bool:
    """Wait until the existing ML service reports that its model is ready."""
    import requests  # type: ignore[import-untyped]

    ml_url = ml_url or os.environ.get("ML_URL") or os.environ.get("ML_BASE_URL")
    if not ml_url:
        raise ValueError("ML_URL or ML_BASE_URL must be set")

    print("⏳ Waiting for ML model initialization...")
    for attempt in range(max_attempts):
        try:
            resp = requests.get(f"{ml_url}/api/model-health", timeout=5)
            resp.raise_for_status()
            payload = resp.json()
            if (
                os.environ.get("THESIS_FINAL_RUN", "").lower() in {"1", "true", "yes", "on"}
                and not (payload.get("metadata") or {}).get("artifact_complete")
            ):
                raise RuntimeError("ML model-health lacks complete final artifact metadata")
            if payload.get("ready"):
                print("✅ ML model ready")
                return True
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            print(f"   Model readiness attempt {attempt + 1}/{max_attempts}: {exc}")
        time.sleep(5)

    print("❌ ML model did not report ready.")
    return False


def set_handover_mode(policy: str, nef_url: Optional[str] = None) -> bool:
    """Set the policy mode through the existing NEF mode API."""
    import requests  # type: ignore[import-untyped]

    nef_url = nef_url or os.environ.get("NEF_URL")
    if not nef_url:
        raise ValueError("NEF_URL must be set")

    try:
        response = requests.post(
            f"{nef_url}/api/v1/ml/mode",
            json={"mode": policy},
            timeout=10,
        )
        if response.status_code != 200:
            print(f"❌ Failed to set handover mode {policy}: HTTP {response.status_code}")
            print(f"   Response: {response.text[:300]}")
            return False
        mode = response.json().get("mode")
        if mode != policy:
            print(f"❌ NEF reported mode {mode!r}; expected {policy!r}")
            return False
        print(f"✅ NEF handover mode set to {policy}")
        return True
    except requests.RequestException as exc:
        print(f"❌ Failed to set handover mode {policy}: {exc}")
        return False


def compose_env_for_policy(
    policy: str,
    *,
    tuned_a3_config: Optional[Path] = None,
) -> Dict[str, str]:
    """Build Compose environment for one policy phase."""
    env = os.environ.copy()
    env["COMPOSE_PROFILES"] = "ml" if policy in POLICIES_REQUIRING_ML else ""
    env["ML_LOCAL"] = "0"
    env["ML_HANDOVER_ENABLED"] = "1" if policy in POLICIES_REQUIRING_ML else "0"
    if tuned_a3_config is not None:
        env["TUNED_A3_CONFIG_PATH"] = LIVE_TUNED_A3_CONTAINER_CONFIG
    return env


def collect_prometheus_metrics(
    output_path: Path,
    mode: str,
) -> Tuple[Dict[str, Optional[float]], List[str]]:
    """Collect metrics from Prometheus."""
    import requests  # type: ignore[import-untyped]
    
    import os
    prom_url = os.environ.get("PROMETHEUS_URL")
    if not prom_url:
        raise ValueError("PROMETHEUS_URL must be set")
    metrics: Dict[str, Optional[float]] = {}
    warnings: List[str] = []
    
    queries = {
        "total_handovers": 'sum(nef_handover_decisions_total{outcome="applied"})',
        "skipped_handovers": 'sum(nef_handover_decisions_total{outcome="skipped"})',
    }
    if mode in POLICIES_REQUIRING_ML:
        queries.update(
            {
                "pingpong_suppressions": "sum(ml_pingpong_suppressions_total)",
                "qos_compliance_ok": 'sum(nef_handover_compliance_total{outcome="ok"})',
                "qos_compliance_failed": 'sum(nef_handover_compliance_total{outcome="failed"})',
                "avg_confidence": "avg(ml_prediction_confidence_avg)",
            }
        )
    
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
                    metrics[name] = None
                    warnings.append(f"Prometheus query returned no series for {name}")
            else:
                metrics[name] = None
                warnings.append(
                    f"Prometheus query for {name} returned HTTP {resp.status_code}"
                )
        except requests.RequestException as e:
            raise RuntimeError(f"Failed to query Prometheus metric {name}: {e}") from e
    
    # Save metrics
    metrics_file = output_path / f"{mode}_mode_metrics.json"
    with open(metrics_file, 'w') as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "mode": mode,
            "metrics": metrics,
            "warnings": warnings,
        }, f, indent=2)
    
    return metrics, warnings


def collect_decision_log_metrics(log_path: Path) -> Dict[str, float]:
    """Derive comparable live metrics from NEF HANDOVER_DECISION log lines."""
    if not log_path.is_file():
        return {}

    applied = 0
    skipped = 0
    pingpong_suppressions = 0
    qos_ok = 0
    qos_failed = 0
    confidence_values: List[float] = []
    decision_count = 0

    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "HANDOVER_DECISION:" not in line:
            continue
        raw_payload = line.split("HANDOVER_DECISION:", 1)[1].strip()
        try:
            payload = json.loads(raw_payload)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue

        decision_count += 1
        outcome = payload.get("outcome")
        if outcome == "applied":
            applied += 1
        elif outcome in {"no_handover", "already_connected", "trace_capture_no_decision"}:
            skipped += 1

        ml_response = payload.get("ml_response")
        if isinstance(ml_response, dict) and ml_response.get("anti_pingpong_applied"):
            pingpong_suppressions += 1

        confidence = payload.get("ml_confidence")
        if isinstance(confidence, (int, float)):
            confidence_values.append(float(confidence))

        qos = payload.get("qos_compliance")
        if isinstance(qos, dict) and qos.get("checked"):
            if qos.get("passed") is False:
                qos_failed += 1
            else:
                qos_ok += 1

    if decision_count == 0:
        return {}

    metrics: Dict[str, float] = {
        "total_handovers": float(applied),
        "skipped_handovers": float(skipped),
        "pingpong_suppressions": float(pingpong_suppressions),
        "live_decision_records": float(decision_count),
    }
    if confidence_values:
        metrics["avg_confidence"] = sum(confidence_values) / len(confidence_values)
    if qos_ok + qos_failed > 0:
        metrics["qos_compliance_ok"] = float(qos_ok)
        metrics["qos_compliance_failed"] = float(qos_failed)
    return metrics


def apply_decision_log_metric_fallback(
    prometheus_metrics: Dict[str, Optional[float]],
    warnings: List[str],
    log_metrics: Dict[str, float],
) -> Tuple[Dict[str, Optional[float]], List[str]]:
    """Fill missing Prometheus metrics from parsed decision logs."""
    if not log_metrics:
        return prometheus_metrics, warnings

    resolved = set()
    merged = dict(prometheus_metrics)
    for key, value in log_metrics.items():
        if key not in merged:
            merged[key] = value
        elif merged[key] is None:
            merged[key] = value
            resolved.add(key)

    remaining_warnings = [
        warning
        for warning in warnings
        if not any(f"for {metric}" in warning for metric in resolved)
    ]
    return merged, remaining_warnings


def topology_hash(topology_path: Path) -> str:
    """Return a stable hash for a saved topology JSON file."""
    payload = json.loads(topology_path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("metadata"), dict):
        payload["metadata"].pop("created_at", None)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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


def cleanup_docker(compose_files: Sequence[Path] | Path) -> None:
    """Ensure Docker Compose is stopped and clean."""
    print("🧹 Cleaning up Docker environment...")
    compose_file_list = [compose_files] if isinstance(compose_files, Path) else list(compose_files)
    cleanup_env = os.environ.copy()
    cleanup_env["COMPOSE_PROFILES"] = "ml"
    subprocess.run(
        DOCKER_COMPOSE_CMD + compose_file_args(compose_file_list) + ["down", "-v"],
        env=cleanup_env,
        capture_output=True
    )
    time.sleep(5)


def ensure_clean_output_dir(output_dir: Path) -> bool:
    """Prevent mixing fresh experiment output with stale artifacts."""
    if output_dir.exists() and any(output_dir.iterdir()):
        print(
            "❌ Output directory already exists and is not empty: "
            f"{output_dir}"
        )
        print("   Choose a new --output path or remove the old directory first.")
        return False
    output_dir.mkdir(parents=True, exist_ok=True)
    return True


# ============================================================================
# Main Experiment Runner
# ============================================================================

def run_experiment(
    scenario_name: str,
    duration_minutes: int,
    output_dir: Path,
    skip_a3: bool = False,
    *,
    policies: Optional[Sequence[str]] = None,
    seed: int = 42,
    tuned_a3_config: Optional[Path] = None,
    plan_only: bool = False,
) -> bool:
    """Run a shared-scenario live comparison across explicit policies."""
    selected_policies = list(policies) if policies is not None else parse_policy_list(
        None,
        skip_a3=skip_a3,
    )
    policy_plan = build_policy_run_plan(
        scenario_name=scenario_name,
        duration_minutes=duration_minutes,
        seed=seed,
        policies=selected_policies,
        tuned_a3_config=tuned_a3_config,
    )

    scenario = get_scenario(scenario_name, seed=seed)
    if not scenario:
        return False
    metadata = scenario.get_metadata()

    print("\n" + "=" * 70)
    print(f"🚀 Enhanced Experiment: {metadata.name}")
    print("=" * 70)
    print(f"   Cells: {metadata.num_cells}")
    print(f"   UEs: {metadata.num_ues}")
    print(f"   Area: {metadata.area_km2} km²")
    print(f"   Seed: {seed}")
    print(f"   Duration: {duration_minutes} minutes per policy")
    print(f"   Policies: {', '.join(selected_policies)}")
    print(f"   Output: {output_dir}")
    print("=" * 70 + "\n")

    if duration_minutes <= 0:
        print("❌ Duration must be positive.")
        return False

    if not ensure_clean_output_dir(output_dir):
        return False
    (output_dir / "metrics").mkdir(exist_ok=True)
    (output_dir / "logs").mkdir(exist_ok=True)
    (output_dir / "topology").mkdir(exist_ok=True)

    policy_plan = stage_tuned_a3_config_for_live_run(output_dir, policy_plan)
    plan_path = write_live_run_plan(output_dir, policy_plan)
    print(f"💾 Saved live policy run plan to {plan_path}")
    if plan_only:
        print("Plan-only mode selected; no Docker services or experiment phases started.")
        return True

    compose_file = REPO_ROOT / "5g-network-optimization" / "docker-compose.yml"
    policy_metrics: Dict[str, Dict] = {}
    policy_metric_warnings: Dict[str, List[str]] = {}
    topology_hashes: Dict[str, str] = {}

    for index, policy_entry in enumerate(policy_plan, start=1):
        print("\n" + "=" * 50)
        print(f"Phase {index}: {policy_entry.policy} Policy Experiment")
        print("=" * 50)

        phase_metrics = run_policy_phase(
            policy_entry,
            output_dir=output_dir,
            compose_file=compose_file,
        )
        if phase_metrics is None:
            return False
        log_metrics = collect_decision_log_metrics(
            output_dir / "logs" / f"{policy_entry.policy}_docker.log"
        )
        merged_metrics, metric_warnings = apply_decision_log_metric_fallback(
            cast(Dict[str, Optional[float]], phase_metrics["metrics"]),
            cast(List[str], phase_metrics.get("metric_warnings", [])),
            log_metrics,
        )
        if log_metrics:
            log_metrics_path = output_dir / "metrics" / f"{policy_entry.policy}_decision_log_metrics.json"
            log_metrics_path.write_text(
                json.dumps(
                    {
                        "timestamp": datetime.now().isoformat(),
                        "mode": policy_entry.policy,
                        "metrics": log_metrics,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        policy_metrics[policy_entry.policy] = cast(Dict, merged_metrics)
        if metric_warnings:
            policy_metric_warnings[policy_entry.policy] = metric_warnings
        topology_hashes[policy_entry.policy] = str(phase_metrics["topology_hash"])

    unique_topology_hashes = set(topology_hashes.values())
    if len(unique_topology_hashes) != 1:
        print("❌ Policy phases did not save identical topology hashes:")
        for policy, saved_hash in topology_hashes.items():
            print(f"   {policy}: {saved_hash}")
        return False

    summary = {
        "experiment": {
            "scenario": scenario_name,
            "description": metadata.description,
            "cells": metadata.num_cells,
            "ues": metadata.num_ues,
            "duration_minutes": duration_minutes,
            "seed": seed,
            "policies": selected_policies,
            "timestamp": datetime.now().isoformat(),
            "topology_hash": next(iter(unique_topology_hashes)),
        },
        "policy_metrics": policy_metrics,
        "policy_metric_warnings": policy_metric_warnings,
        # Backward-compatible keys for existing visual/report helpers.
        "ml_metrics": policy_metrics.get("ml"),
        "a3_metrics": policy_metrics.get("a3"),
    }

    (output_dir / "experiment_summary.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )

    if "ml" in policy_metrics and "a3" in policy_metrics:
        generate_visualizations(output_dir)

    print("\n" + "=" * 70)
    print("📊 Experiment Results Summary")
    print("=" * 70)
    print(f"\nScenario: {metadata.name}")
    print(f"Seed: {seed}")
    print(f"Cells: {metadata.num_cells}, UEs: {metadata.num_ues}")
    for policy, metrics in policy_metrics.items():
        print(f"\n{policy} Results:")
        print(f"  Total Handovers: {metrics.get('total_handovers', 'N/A')}")
        print(f"  Ping-Pong Suppressions: {metrics.get('pingpong_suppressions', 'N/A')}")
        print(f"  QoS Compliance: {metrics.get('qos_compliance_ok', 'N/A')} passed")

    print(f"\n📁 Results saved to: {output_dir}")
    print("=" * 70 + "\n")
    return True


def run_policy_phase(
    policy_plan: PolicyRunPlan,
    *,
    output_dir: Path,
    compose_file: Path,
) -> Optional[Dict[str, object]]:
    """Run one fresh live policy phase using the existing shared NEF path."""
    policy = policy_plan.policy
    tuned_config = (
        Path(policy_plan.tuned_a3_config)
        if policy_plan.tuned_a3_config is not None
        else None
    )
    env = compose_env_for_policy(policy, tuned_a3_config=tuned_config)
    scenario = get_scenario(policy_plan.scenario, seed=policy_plan.seed)
    if scenario is None:
        return None
    compose_files = [compose_file]
    if tuned_config is not None:
        compose_files.append(write_tuned_a3_compose_override(output_dir, tuned_config))

    cleanup_docker(compose_files)

    print(f"Starting Docker Compose for policy {policy}...")
    result = subprocess.run(
        DOCKER_COMPOSE_CMD + compose_file_args(compose_files) + ["up", "-d"],
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"❌ Docker Compose startup failed for {policy}: {result.stderr[:500]}")
        return None

    try:
        if policy_plan.requires_ml_service:
            if not wait_for_services():
                return None
            if not wait_for_ml_model_ready():
                return None
        elif not wait_for_nef_service():
            return None

        if not set_handover_mode(policy):
            return None

        print("\n📍 Deploying scenario topology...")
        if not scenario.deploy():
            print(f"❌ Scenario deployment failed for policy {policy}")
            return None

        topology_path = output_dir / "topology" / f"{policy}_topology.json"
        scenario.save_topology(topology_path)
        saved_topology_hash = topology_hash(topology_path)

        print("\n▶️  Starting UE movement...")
        scenario.start_all_ues()

        print(
            f"\n⏱️  Running {policy} experiment for "
            f"{policy_plan.duration_minutes} minutes..."
        )
        _sleep_for_duration(policy_plan.duration_minutes)
        print(f"✅ {policy} experiment complete")

        metrics, metric_warnings = collect_prometheus_metrics(
            output_dir / "metrics",
            policy,
        )
        for warning in metric_warnings:
            print(f"⚠️  {policy}: {warning}")
        return {
            "metrics": metrics,
            "metric_warnings": metric_warnings,
            "topology_hash": saved_topology_hash,
        }
    finally:
        try:
            scenario.stop_all_ues()
        except Exception as exc:  # noqa: BLE001
            print(f"⚠️  Failed to stop all UEs for policy {policy}: {exc}")

        logs_path = output_dir / "logs" / f"{policy}_docker.log"
        with logs_path.open("w", encoding="utf-8") as handle:
            subprocess.run(
                DOCKER_COMPOSE_CMD + compose_file_args(compose_files) + ["logs"],
                env=env,
                stdout=handle,
                stderr=subprocess.STDOUT,
                text=True,
            )

        subprocess.run(
            DOCKER_COMPOSE_CMD + compose_file_args(compose_files) + ["down", "-v"],
            env=env,
            capture_output=True,
        )
        time.sleep(10)


def _sleep_for_duration(duration_minutes: int) -> None:
    duration_seconds = duration_minutes * 60
    start_time = datetime.now()
    while True:
        elapsed = (datetime.now() - start_time).total_seconds()
        if elapsed >= duration_seconds:
            return
        remaining = int(duration_seconds - elapsed)
        print(f"   Progress: {int(elapsed)}s / {duration_seconds}s ({remaining}s remaining)")
        time.sleep(min(30, max(1, remaining)))


# ============================================================================
# CLI Entry Point
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Run enhanced scenario experiments with handover policy comparison",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_enhanced_experiment.py --env-file 5g-network-optimization/.env --scenario smart_city --duration 15
  python run_enhanced_experiment.py --env-file 5g-network-optimization/.env --scenario highway --duration 10
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
        "--env-file",
        type=str,
        default=str(REPO_ROOT / "5g-network-optimization" / ".env"),
        help="Env file to load before running (default: 5g-network-optimization/.env)"
    )
    parser.add_argument(
        "--skip-a3",
        action="store_true",
        help="Skip A3 mode experiment (ML only)"
    )
    parser.add_argument(
        "--policies",
        type=str,
        help=(
            "Comma-separated live policies to run. Supported: "
            + ",".join(SUPPORTED_LIVE_POLICIES)
            + ". Defaults to ml,a3 unless --skip-a3 is used."
        ),
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Scenario seed reused for every policy phase (default: 42)",
    )
    parser.add_argument(
        "--tuned-a3-config",
        type=str,
        help=(
            "Path to a real tuned A3 JSON containing selected_parameters; "
            "required when policies include tuned_a3_baseline."
        ),
    )
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="Write the live experiment plan and exit without starting services.",
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

    load_env_file(Path(args.env_file))
    normalize_runtime_env()

    try:
        policies = parse_policy_list(args.policies, skip_a3=args.skip_a3)
    except ValueError as exc:
        print(f"\n❌ Error: {exc}")
        return 1
    
    # Set output directory
    if args.output:
        output_dir = Path(args.output)
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = REPO_ROOT / "thesis_results" / f"{args.scenario}_{timestamp}"
    
    # Run experiment
    try:
        success = run_experiment(
            scenario_name=args.scenario,
            duration_minutes=args.duration,
            output_dir=output_dir,
            skip_a3=args.skip_a3,
            policies=policies,
            seed=args.seed,
            tuned_a3_config=Path(args.tuned_a3_config) if args.tuned_a3_config else None,
            plan_only=args.plan_only,
        )
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"\n❌ Error: {exc}")
        return 1
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
