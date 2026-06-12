#!/usr/bin/env python3
"""Run a scenario in NEF trace-capture mode and write a canonical trace."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

if __package__ in {None, ""}:  # pragma: no cover - direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.policy_comparison.capture_nef_trace import parse_ue_ids, resolve_nef_url
from scripts.policy_comparison.nef_trace import capture_nef_trace_records
from scripts.policy_comparison.trace_io import write_trace_jsonl
from scripts.run_enhanced_experiment import (
    DOCKER_COMPOSE_CMD,
    cleanup_docker,
    get_scenario,
    load_env_file,
    normalize_runtime_env,
    set_handover_mode,
    topology_hash,
    wait_for_nef_service,
)


DEFAULT_HIGHWAY_UE_IDS = [
    f"202010000002{i:03d}"
    for i in range(1, 11)
]
DEFAULT_DENSE_HIGHWAY_UE_IDS = list(DEFAULT_HIGHWAY_UE_IDS)


def ensure_fresh_output_dir(path: Path) -> None:
    if path.exists() and any(path.iterdir()):
        raise ValueError(f"output directory already exists and is not empty: {path}")
    path.mkdir(parents=True, exist_ok=True)


def compose_env_for_trace_capture() -> dict[str, str]:
    env = os.environ.copy()
    env["COMPOSE_PROFILES"] = ""
    env["ML_LOCAL"] = "0"
    env["ML_HANDOVER_ENABLED"] = "0"
    return env


def default_ue_ids_for_scenario(scenario_name: str) -> list[str]:
    if scenario_name in {"highway", "highway_dense"}:
        if scenario_name == "highway_dense":
            return list(DEFAULT_DENSE_HIGHWAY_UE_IDS)
        return list(DEFAULT_HIGHWAY_UE_IDS)
    raise ValueError(
        f"--ue-id is required for scenario {scenario_name!r}; no safe default is defined"
    )


def selected_ue_ids(raw_ue_ids: Optional[Sequence[str]], scenario_name: str) -> list[str]:
    if raw_ue_ids:
        return parse_ue_ids(raw_ue_ids)
    return default_ue_ids_for_scenario(scenario_name)


def start_selected_ues(scenario, ue_ids: Sequence[str], *, delay_s: float) -> int:
    available = {ue.supi for ue in getattr(scenario, "ues", [])}
    missing = sorted(set(ue_ids).difference(available))
    if missing:
        raise ValueError(
            "requested UE IDs are not present in deployed scenario: " + ", ".join(missing)
        )

    started = 0
    for index, ue_id in enumerate(ue_ids):
        if scenario.start_ue_movement(ue_id):
            started += 1
        if index < len(ue_ids) - 1 and delay_s > 0:
            time.sleep(delay_s)
    if started != len(ue_ids):
        raise RuntimeError(f"started {started}/{len(ue_ids)} requested UEs")
    return started


def stop_selected_ues(scenario, ue_ids: Sequence[str]) -> int:
    stopped = 0
    for ue_id in ue_ids:
        if scenario.stop_ue_movement(ue_id):
            stopped += 1
    return stopped


def write_metadata(
    *,
    path: Path,
    scenario_name: str,
    seed: int,
    ue_ids: Sequence[str],
    samples: int,
    interval_s: float,
    timeout_s: float,
    record_count: int,
    topology_path: Path,
    topology_hash_value: str,
    nef_url: str,
) -> None:
    metadata = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scenario": scenario_name,
        "seed": seed,
        "ue_ids": list(ue_ids),
        "samples": samples,
        "interval_s": interval_s,
        "timeout_s": timeout_s,
        "record_count": record_count,
        "nef_url": nef_url,
        "topology_json": str(topology_path),
        "topology_hash": topology_hash_value,
        "source": "existing_shared_nef_trace_capture_mode",
        "endpoint": "/api/v1/ml/state/{ue_id}",
        "handover_mode": "trace_capture",
        "policy_free": True,
        "no_handover_applied_by_runner": True,
    }
    path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")


def capture_scenario_trace(
    *,
    scenario_name: str,
    seed: int,
    output_dir: Path,
    ue_ids: Sequence[str],
    samples: int,
    interval_s: float,
    timeout_s: float,
    env_file: Path,
    compose_file: Path,
    nef_url: Optional[str] = None,
    start_delay_s: float = 1.0,
    warmup_s: float = 2.0,
) -> Path:
    if samples <= 0:
        raise ValueError("samples must be positive")
    if interval_s < 0:
        raise ValueError("interval_s must be non-negative")
    if timeout_s <= 0:
        raise ValueError("timeout_s must be positive")
    if start_delay_s < 0:
        raise ValueError("start_delay_s must be non-negative")
    if warmup_s < 0:
        raise ValueError("warmup_s must be non-negative")
    if not compose_file.is_file():
        raise ValueError(f"compose file does not exist: {compose_file}")

    ensure_fresh_output_dir(output_dir)
    (output_dir / "logs").mkdir(exist_ok=True)
    (output_dir / "topology").mkdir(exist_ok=True)

    load_env_file(env_file)
    normalize_runtime_env()
    resolved_nef_url = resolve_nef_url(nef_url)
    env = compose_env_for_trace_capture()
    scenario = get_scenario(scenario_name, seed=seed)
    if scenario is None:
        raise ValueError(f"unknown scenario: {scenario_name}")

    trace_path = output_dir / "trace.jsonl"
    metadata_path = output_dir / "trace.metadata.json"
    topology_path = output_dir / "topology" / "trace_capture_topology.json"
    logs_path = output_dir / "logs" / "trace_capture_docker.log"

    cleanup_docker(compose_file)
    result = subprocess.run(
        DOCKER_COMPOSE_CMD + ["-f", str(compose_file), "up", "-d"],
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Docker Compose startup failed: {result.stderr[:500]}")

    try:
        if not wait_for_nef_service(resolved_nef_url):
            raise RuntimeError("NEF service did not become ready")
        if not set_handover_mode("trace_capture", resolved_nef_url):
            raise RuntimeError("failed to set NEF mode to trace_capture")
        if not scenario.deploy():
            raise RuntimeError(f"scenario deployment failed: {scenario_name}")

        scenario.save_topology(topology_path)
        topology_hash_value = topology_hash(topology_path)

        start_selected_ues(scenario, ue_ids, delay_s=start_delay_s)
        if warmup_s > 0:
            time.sleep(warmup_s)

        records = capture_nef_trace_records(
            nef_url=resolved_nef_url,
            ue_ids=ue_ids,
            scenario=scenario_name,
            seed=seed,
            samples=samples,
            interval_s=interval_s,
            timeout_s=timeout_s,
            topology_hash=topology_hash_value,
        )
        write_trace_jsonl(records, trace_path)
        write_metadata(
            path=metadata_path,
            scenario_name=scenario_name,
            seed=seed,
            ue_ids=ue_ids,
            samples=samples,
            interval_s=interval_s,
            timeout_s=timeout_s,
            record_count=len(records),
            topology_path=topology_path,
            topology_hash_value=topology_hash_value,
            nef_url=resolved_nef_url,
        )
        return trace_path
    finally:
        try:
            stop_selected_ues(scenario, ue_ids)
        except Exception as exc:  # noqa: BLE001
            print(f"WARNING: failed to stop selected UEs: {exc}", file=sys.stderr)

        with logs_path.open("w", encoding="utf-8") as handle:
            subprocess.run(
                DOCKER_COMPOSE_CMD + ["-f", str(compose_file), "logs"],
                env=env,
                stdout=handle,
                stderr=subprocess.STDOUT,
                text=True,
            )

        subprocess.run(
            DOCKER_COMPOSE_CMD + ["-f", str(compose_file), "down", "-v"],
            env=env,
            capture_output=True,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Start the existing shared NEF stack, deploy a scenario in "
            "trace_capture mode, and capture policy-free canonical JSONL."
        )
    )
    parser.add_argument("--scenario", default="highway", help="Scenario name.")
    parser.add_argument("--seed", type=int, required=True, help="Scenario seed.")
    parser.add_argument("--output-dir", required=True, help="Fresh output directory.")
    parser.add_argument(
        "--ue-id",
        action="append",
        help=(
            "UE ID to capture. Can be repeated or comma-separated. "
            "Defaults to all 10 highway UEs for --scenario highway."
        ),
    )
    parser.add_argument("--samples", type=int, default=300, help="Samples per UE.")
    parser.add_argument("--interval-s", type=float, default=1.0, help="Seconds between samples.")
    parser.add_argument("--timeout-s", type=float, default=5.0, help="NEF request timeout.")
    parser.add_argument("--nef-url", help="NEF base URL. Falls back to env.")
    parser.add_argument(
        "--env-file",
        default=str(Path("5g-network-optimization") / ".env"),
        help="Environment file to load before starting Compose.",
    )
    parser.add_argument(
        "--compose-file",
        default=str(Path("5g-network-optimization") / "docker-compose.yml"),
        help="Existing shared Docker Compose file.",
    )
    parser.add_argument("--start-delay-s", type=float, default=1.0)
    parser.add_argument("--warmup-s", type=float, default=2.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        ue_ids = selected_ue_ids(args.ue_id, args.scenario)
        trace_path = capture_scenario_trace(
            scenario_name=args.scenario,
            seed=args.seed,
            output_dir=Path(args.output_dir),
            ue_ids=ue_ids,
            samples=args.samples,
            interval_s=args.interval_s,
            timeout_s=args.timeout_s,
            env_file=Path(args.env_file),
            compose_file=Path(args.compose_file),
            nef_url=args.nef_url,
            start_delay_s=args.start_delay_s,
            warmup_s=args.warmup_s,
        )
    except Exception as exc:  # noqa: BLE001 - command must fail visibly
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Trace written to {trace_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
