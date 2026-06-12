"""Trace preparation planning for calibration/evaluation comparisons."""

from __future__ import annotations

import json
import shlex
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence


class TracePlanError(ValueError):
    """Raised when a trace preparation plan would be unsafe or ambiguous."""


@dataclass(frozen=True)
class PlannedTrace:
    """One planned trace capture output."""

    role: str
    seed: int
    path: str
    metadata_path: str

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class TracePreparationPlan:
    """A command plan for separate calibration/evaluation trace capture."""

    created_at: str
    scenario: str
    ue_ids: List[str]
    samples: int
    interval_s: float
    timeout_s: float
    policies: List[str]
    output_root: str
    calibration_traces: List[PlannedTrace]
    evaluation_traces: List[PlannedTrace]
    capture_commands: List[str]
    replay_commands: List[str]
    notes: List[str]

    def to_dict(self) -> Dict[str, object]:
        return {
            "created_at": self.created_at,
            "scenario": self.scenario,
            "ue_ids": self.ue_ids,
            "samples": self.samples,
            "interval_s": self.interval_s,
            "timeout_s": self.timeout_s,
            "policies": self.policies,
            "output_root": self.output_root,
            "calibration_traces": [
                trace.to_dict() for trace in self.calibration_traces
            ],
            "evaluation_traces": [trace.to_dict() for trace in self.evaluation_traces],
            "capture_commands": self.capture_commands,
            "replay_commands": self.replay_commands,
            "notes": self.notes,
        }


def parse_int_list(raw_values: Sequence[str], *, field_name: str) -> List[int]:
    """Parse repeatable/comma-separated integer CLI values."""
    values: List[int] = []
    for raw in raw_values:
        for item in raw.split(","):
            stripped = item.strip()
            if stripped:
                values.append(int(stripped))
    if not values:
        raise TracePlanError(f"{field_name} must include at least one seed")
    if len(set(values)) != len(values):
        raise TracePlanError(f"{field_name} contains duplicate seeds")
    if any(value < 0 for value in values):
        raise TracePlanError(f"{field_name} seeds must be non-negative")
    return values


def parse_string_list(raw_values: Sequence[str], *, field_name: str) -> List[str]:
    """Parse repeatable/comma-separated string CLI values."""
    values: List[str] = []
    for raw in raw_values:
        values.extend(item.strip() for item in raw.split(",") if item.strip())
    if not values:
        raise TracePlanError(f"{field_name} must include at least one value")
    if len(set(values)) != len(values):
        raise TracePlanError(f"{field_name} contains duplicate values")
    return values


def validate_trace_split(
    *,
    calibration_seeds: Sequence[int],
    evaluation_seeds: Sequence[int],
    policies: Sequence[str],
) -> None:
    """Validate calibration/evaluation seed discipline."""
    supported = {
        "ml",
        "fixed_a3_baseline",
        "tuned_a3_baseline",
        "strongest_rsrp_baseline",
        "strongest_sinr_baseline",
        "strongest_rsrq_baseline",
        "load_aware_a3_baseline",
        "velocity_adaptive_a3_baseline",
        "complexity_aware_ml_a3",
    }
    tuned_required = {"tuned_a3_baseline", "complexity_aware_ml_a3"}
    unknown = sorted(set(policies) - supported)
    if unknown:
        raise TracePlanError(f"unknown policies: {', '.join(unknown)}")

    overlap = set(calibration_seeds).intersection(evaluation_seeds)
    if overlap:
        raise TracePlanError(
            "calibration and evaluation seeds must be disjoint: "
            + ", ".join(str(seed) for seed in sorted(overlap))
        )

    if tuned_required.intersection(policies):
        if not calibration_seeds:
            raise TracePlanError("tuned A3 policies require a calibration seed")
        if len(calibration_seeds) != 1:
            raise TracePlanError(
                "current tuned A3 replay supports exactly one calibration trace"
            )


def ensure_fresh_output_root(output_root: Path) -> None:
    """Create an empty output root or reject a non-empty one."""
    if output_root.exists() and any(output_root.iterdir()):
        raise TracePlanError(
            f"output root already exists and is not empty: {output_root}"
        )
    output_root.mkdir(parents=True, exist_ok=True)


def build_trace_preparation_plan(
    *,
    scenario: str,
    ue_ids: Sequence[str],
    calibration_seeds: Sequence[int],
    evaluation_seeds: Sequence[int],
    output_root: Path,
    samples: int,
    interval_s: float,
    timeout_s: float,
    policies: Sequence[str],
    nef_url: Optional[str] = None,
    ml_base_url: Optional[str] = None,
    topology_hash: Optional[str] = None,
    topology_json: Optional[Path] = None,
    python_bin: str = ".venv/bin/python",
) -> TracePreparationPlan:
    """Build command lines for capture and offline replay without executing them."""
    clean_scenario = scenario.strip()
    if not clean_scenario:
        raise TracePlanError("scenario is required")
    clean_ue_ids = parse_string_list(ue_ids, field_name="ue_ids")
    if samples <= 0:
        raise TracePlanError("samples must be positive")
    if interval_s < 0:
        raise TracePlanError("interval_s must be non-negative")
    if timeout_s <= 0:
        raise TracePlanError("timeout_s must be positive")
    if topology_hash and topology_json:
        raise TracePlanError("provide topology_hash or topology_json, not both")

    clean_policies = parse_string_list(policies, field_name="policies")
    validate_trace_split(
        calibration_seeds=calibration_seeds,
        evaluation_seeds=evaluation_seeds,
        policies=clean_policies,
    )

    traces_dir = output_root / "traces"
    replay_dir = output_root / "replays"
    calibration_traces = [
        _planned_trace(traces_dir, clean_scenario, "calibration", seed)
        for seed in calibration_seeds
    ]
    evaluation_traces = [
        _planned_trace(traces_dir, clean_scenario, "evaluation", seed)
        for seed in evaluation_seeds
    ]

    capture_commands = [
        _capture_command(
            python_bin=python_bin,
            scenario=clean_scenario,
            seed=trace.seed,
            ue_ids=clean_ue_ids,
            output=Path(trace.path),
            samples=samples,
            interval_s=interval_s,
            timeout_s=timeout_s,
            nef_url=nef_url,
            topology_hash=topology_hash,
            topology_json=topology_json,
        )
        for trace in [*calibration_traces, *evaluation_traces]
    ]

    calibration_trace = calibration_traces[0] if calibration_traces else None
    replay_commands = [
        _replay_command(
            python_bin=python_bin,
            evaluation_trace=Path(trace.path),
            calibration_trace=(
                Path(calibration_trace.path)
                if calibration_trace
                and {"tuned_a3_baseline", "complexity_aware_ml_a3"}.intersection(clean_policies)
                else None
            ),
            output_dir=replay_dir
            / f"{clean_scenario}_evaluation_seed{trace.seed}_{_policy_slug(clean_policies)}",
            policies=clean_policies,
            ml_base_url=ml_base_url,
        )
        for trace in evaluation_traces
    ]

    notes = [
        "This plan only writes command lines; it does not capture traces or run replay.",
        "Capture commands read the existing NEF feature endpoint only.",
        "No ML-vs-A3 thesis result is generated by preparing this plan.",
    ]
    if {"tuned_a3_baseline", "complexity_aware_ml_a3"}.intersection(clean_policies):
        notes.append(
            "Tuned A3 uses the single calibration trace listed in this plan; "
            "evaluation traces use disjoint seeds."
        )

    return TracePreparationPlan(
        created_at=datetime.now(timezone.utc).isoformat(),
        scenario=clean_scenario,
        ue_ids=list(clean_ue_ids),
        samples=samples,
        interval_s=interval_s,
        timeout_s=timeout_s,
        policies=list(clean_policies),
        output_root=str(output_root),
        calibration_traces=calibration_traces,
        evaluation_traces=evaluation_traces,
        capture_commands=capture_commands,
        replay_commands=replay_commands,
        notes=notes,
    )


def write_trace_preparation_plan(
    plan: TracePreparationPlan,
    output_root: Path,
) -> tuple[Path, Path]:
    """Write plan JSON and shell command file."""
    plan_path = output_root / "trace_plan.json"
    commands_path = output_root / "trace_commands.sh"
    plan_path.write_text(
        json.dumps(plan.to_dict(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    commands_path.write_text(_commands_file(plan), encoding="utf-8")
    return plan_path, commands_path


def _planned_trace(
    traces_dir: Path,
    scenario: str,
    role: str,
    seed: int,
) -> PlannedTrace:
    path = traces_dir / f"{scenario}_{role}_seed{seed}.jsonl"
    return PlannedTrace(
        role=role,
        seed=seed,
        path=str(path),
        metadata_path=str(path.with_suffix(path.suffix + ".metadata.json")),
    )


def _capture_command(
    *,
    python_bin: str,
    scenario: str,
    seed: int,
    ue_ids: Sequence[str],
    output: Path,
    samples: int,
    interval_s: float,
    timeout_s: float,
    nef_url: Optional[str],
    topology_hash: Optional[str],
    topology_json: Optional[Path],
) -> str:
    parts = [
        python_bin,
        "-m",
        "scripts.policy_comparison.capture_nef_trace",
        "--scenario",
        scenario,
        "--seed",
        str(seed),
    ]
    for ue_id in ue_ids:
        parts.extend(["--ue-id", ue_id])
    parts.extend(
        [
            "--samples",
            str(samples),
            "--interval-s",
            str(interval_s),
            "--timeout-s",
            str(timeout_s),
            "--output",
            str(output),
        ]
    )
    if nef_url:
        parts.extend(["--nef-url", nef_url])
    if topology_hash:
        parts.extend(["--topology-hash", topology_hash])
    if topology_json:
        parts.extend(["--topology-json", str(topology_json)])
    return _quote(parts)


def _replay_command(
    *,
    python_bin: str,
    evaluation_trace: Path,
    calibration_trace: Optional[Path],
    output_dir: Path,
    policies: Sequence[str],
    ml_base_url: Optional[str],
) -> str:
    parts = [
        python_bin,
        "-m",
        "scripts.policy_comparison.run_offline_replay",
        "--trace",
        str(evaluation_trace),
        "--output-dir",
        str(output_dir),
        "--policies",
        ",".join(policies),
    ]
    if calibration_trace:
        parts.extend(["--calibration-trace", str(calibration_trace)])
    if ml_base_url:
        parts.extend(["--ml-base-url", ml_base_url])
    return _quote(parts)


def _quote(parts: Sequence[str]) -> str:
    return " ".join(shlex.quote(part) for part in parts)


def _commands_file(plan: TracePreparationPlan) -> str:
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        "# Generated trace capture commands. These read existing NEF measurements only.",
        *plan.capture_commands,
        "",
        "# Generated offline replay commands. These do not run the full thesis experiment.",
        *plan.replay_commands,
        "",
    ]
    return "\n".join(lines)


def _policy_slug(policies: Sequence[str]) -> str:
    return "_".join(policy.replace("-", "_") for policy in policies)
