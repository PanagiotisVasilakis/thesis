"""Validation-grade comparison campaign planning.

The planner writes command files for a future evidence campaign. It never starts
Docker, calls NEF, calls ML, captures traces, or runs the thesis experiment.
"""

from __future__ import annotations

import json
import shlex
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from scripts.run_enhanced_experiment import SCENARIOS, SUPPORTED_LIVE_POLICIES

from .trace_plan import parse_int_list, parse_string_list


COMPARISON_POLICIES = {
    "ml",
    "fixed_a3_baseline",
    "tuned_a3_baseline",
    "complexity_aware_ml_a3",
}
POLICIES_REQUIRING_TUNED_A3 = {"tuned_a3_baseline", "complexity_aware_ml_a3"}


class CampaignPlanError(ValueError):
    """Raised when a campaign plan would be unsafe or incomplete."""


@dataclass(frozen=True)
class PlannedLiveRun:
    """One future live comparison run command set."""

    scenario: str
    seed: int
    duration_minutes: int
    output_dir: str
    readiness_command: str
    plan_only_command: str
    run_command: str
    validation_command: str

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ComparisonCampaignPlan:
    """Full multi-seed comparison campaign plan."""

    created_at: str
    campaign_name: str
    output_root: str
    primary_scenario: str
    secondary_scenario: Optional[str]
    policies: List[str]
    ue_ids: List[str]
    calibration_seed: Optional[int]
    evaluation_seeds: List[int]
    offline_trace_plan_command: Optional[str]
    primary_live_runs: List[PlannedLiveRun]
    secondary_live_runs: List[PlannedLiveRun]
    validation_commands: List[str]
    statistics_commands: List[str]
    notes: List[str]

    def to_dict(self) -> Dict[str, object]:
        return {
            "created_at": self.created_at,
            "campaign_name": self.campaign_name,
            "output_root": self.output_root,
            "primary_scenario": self.primary_scenario,
            "secondary_scenario": self.secondary_scenario,
            "policies": self.policies,
            "ue_ids": self.ue_ids,
            "calibration_seed": self.calibration_seed,
            "evaluation_seeds": self.evaluation_seeds,
            "offline_trace_plan_command": self.offline_trace_plan_command,
            "primary_live_runs": [
                run.to_dict() for run in self.primary_live_runs
            ],
            "secondary_live_runs": [
                run.to_dict() for run in self.secondary_live_runs
            ],
            "validation_commands": self.validation_commands,
            "statistics_commands": self.statistics_commands,
            "notes": self.notes,
        }


def ensure_fresh_campaign_root(output_root: Path) -> None:
    """Create the campaign root or reject a non-empty existing directory."""
    if output_root.exists() and any(output_root.iterdir()):
        raise CampaignPlanError(
            f"campaign output root already exists and is not empty: {output_root}"
        )
    output_root.mkdir(parents=True, exist_ok=True)


def build_comparison_campaign_plan(
    *,
    campaign_name: str,
    output_root: Path,
    primary_scenario: str,
    evaluation_seeds: Sequence[int],
    policies: Sequence[str],
    ue_ids: Sequence[str],
    duration_minutes: int,
    calibration_seed: Optional[int] = None,
    secondary_scenario: Optional[str] = None,
    secondary_duration_minutes: Optional[int] = None,
    env_file: Path = Path("5g-network-optimization/.env"),
    tuned_a3_config: Optional[Path] = None,
    samples: int = 60,
    interval_s: float = 1.0,
    python_bin: str = ".venv/bin/python",
) -> ComparisonCampaignPlan:
    """Build future command plans for offline and live comparison evidence."""
    clean_campaign_name = campaign_name.strip()
    if not clean_campaign_name:
        raise CampaignPlanError("campaign_name is required")
    clean_primary = _validate_scenario(primary_scenario, "primary_scenario")
    clean_secondary = (
        _validate_scenario(secondary_scenario, "secondary_scenario")
        if secondary_scenario
        else None
    )
    if clean_secondary == clean_primary:
        raise CampaignPlanError("secondary_scenario must differ from primary_scenario")
    if duration_minutes <= 0:
        raise CampaignPlanError("duration_minutes must be positive")
    if secondary_duration_minutes is not None and secondary_duration_minutes <= 0:
        raise CampaignPlanError("secondary_duration_minutes must be positive")
    if samples <= 0:
        raise CampaignPlanError("samples must be positive")
    if interval_s < 0:
        raise CampaignPlanError("interval_s must be non-negative")

    clean_policies = parse_string_list(policies, field_name="policies")
    _validate_campaign_policies(clean_policies, tuned_a3_config)
    clean_ue_ids = parse_string_list(ue_ids, field_name="ue_ids")
    clean_evaluation_seeds = list(evaluation_seeds)
    if not clean_evaluation_seeds:
        raise CampaignPlanError("evaluation_seeds must include at least one seed")
    if len(set(clean_evaluation_seeds)) != len(clean_evaluation_seeds):
        raise CampaignPlanError("evaluation_seeds contains duplicate seeds")
    if any(seed < 0 for seed in clean_evaluation_seeds):
        raise CampaignPlanError("evaluation_seeds must be non-negative")
    if calibration_seed is not None:
        if calibration_seed < 0:
            raise CampaignPlanError("calibration_seed must be non-negative")
        if calibration_seed in clean_evaluation_seeds:
            raise CampaignPlanError(
                "calibration_seed must be disjoint from evaluation_seeds"
            )
    if POLICIES_REQUIRING_TUNED_A3.intersection(clean_policies) and calibration_seed is None:
        raise CampaignPlanError(
            "tuned A3 policies require a calibration_seed for offline planning"
        )

    offline_command = _offline_trace_plan_command(
        python_bin=python_bin,
        scenario=clean_primary,
        ue_ids=clean_ue_ids,
        calibration_seed=calibration_seed,
        evaluation_seeds=clean_evaluation_seeds,
        output_root=output_root / "offline_trace_plan",
        samples=samples,
        interval_s=interval_s,
        policies=clean_policies,
    )
    primary_runs = [
        _planned_live_run(
            python_bin=python_bin,
            scenario=clean_primary,
            seed=seed,
            duration_minutes=duration_minutes,
            output_dir=output_root / "live" / f"{clean_primary}_seed{seed}",
            policies=clean_policies,
            env_file=env_file,
            tuned_a3_config=tuned_a3_config,
        )
        for seed in clean_evaluation_seeds
    ]
    secondary_runs: List[PlannedLiveRun] = []
    if clean_secondary:
        secondary_runs = [
            _planned_live_run(
                python_bin=python_bin,
                scenario=clean_secondary,
                seed=seed,
                duration_minutes=(
                    secondary_duration_minutes
                    if secondary_duration_minutes is not None
                    else duration_minutes
                ),
                output_dir=output_root / "live" / f"{clean_secondary}_seed{seed}",
                policies=clean_policies,
                env_file=env_file,
                tuned_a3_config=tuned_a3_config,
            )
            for seed in clean_evaluation_seeds
        ]

    all_runs = [*primary_runs, *secondary_runs]
    validation_commands = [run.validation_command for run in all_runs]
    statistics_commands = _statistics_commands(
        python_bin=python_bin,
        output_root=output_root,
        scenario=clean_primary,
        runs=primary_runs,
        policies=clean_policies,
    )
    if secondary_runs:
        statistics_commands.extend(
            _statistics_commands(
                python_bin=python_bin,
                output_root=output_root,
                scenario=clean_secondary or "",
                runs=secondary_runs,
                policies=clean_policies,
            )
        )

    notes = [
        "This campaign plan writes commands only; it does not execute them.",
        "Run readiness commands before each live run command.",
        "Run validation commands before statistical reporting.",
        "Do not treat smart_city as primary evidence unless highway is stable.",
        "No real-world field validation is claimed by this plan.",
    ]
    if "tuned_a3_baseline" in clean_policies:
        notes.append(
            "Tuned A3 live commands require the real tuned config path recorded "
            "in this plan; no tuned results are fabricated."
        )

    return ComparisonCampaignPlan(
        created_at=datetime.now(timezone.utc).isoformat(),
        campaign_name=clean_campaign_name,
        output_root=str(output_root),
        primary_scenario=clean_primary,
        secondary_scenario=clean_secondary,
        policies=list(clean_policies),
        ue_ids=list(clean_ue_ids),
        calibration_seed=calibration_seed,
        evaluation_seeds=clean_evaluation_seeds,
        offline_trace_plan_command=offline_command,
        primary_live_runs=primary_runs,
        secondary_live_runs=secondary_runs,
        validation_commands=validation_commands,
        statistics_commands=statistics_commands,
        notes=notes,
    )


def write_comparison_campaign_plan(
    plan: ComparisonCampaignPlan,
    output_root: Path,
) -> tuple[Path, Path, Path, Path]:
    """Write JSON and shell command files for the campaign plan."""
    plan_path = output_root / "comparison_campaign_plan.json"
    offline_path = output_root / "offline_commands.sh"
    live_path = output_root / "live_commands.sh"
    analysis_path = output_root / "analysis_commands.sh"
    plan_path.write_text(
        json.dumps(plan.to_dict(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    offline_path.write_text(_offline_commands_file(plan), encoding="utf-8")
    live_path.write_text(_live_commands_file(plan), encoding="utf-8")
    analysis_path.write_text(_analysis_commands_file(plan), encoding="utf-8")
    return plan_path, offline_path, live_path, analysis_path


def _validate_scenario(value: Optional[str], field_name: str) -> str:
    if value is None or not value.strip():
        raise CampaignPlanError(f"{field_name} is required")
    scenario = value.strip()
    if scenario not in SCENARIOS:
        raise CampaignPlanError(
            f"unknown scenario {scenario!r}; supported: {', '.join(sorted(SCENARIOS))}"
        )
    return scenario


def _validate_campaign_policies(
    policies: Sequence[str],
    tuned_a3_config: Optional[Path],
) -> None:
    unknown = sorted(set(policies).difference(COMPARISON_POLICIES))
    if unknown:
        raise CampaignPlanError(
            "unsupported campaign policy value(s): "
            + ", ".join(unknown)
            + f". Supported: {', '.join(sorted(COMPARISON_POLICIES))}"
        )
    unsupported_live = sorted(set(policies).difference(SUPPORTED_LIVE_POLICIES))
    if unsupported_live:
        raise CampaignPlanError(
            "policy not supported by live runner: " + ", ".join(unsupported_live)
        )
    if "ml" not in policies:
        raise CampaignPlanError("campaign policies must include ml")
    if "fixed_a3_baseline" not in policies:
        raise CampaignPlanError("campaign policies must include fixed_a3_baseline")
    if POLICIES_REQUIRING_TUNED_A3.intersection(policies):
        if tuned_a3_config is None:
            raise CampaignPlanError(
                "tuned A3 policies live planning requires --tuned-a3-config"
            )
        if not tuned_a3_config.expanduser().is_file():
            raise CampaignPlanError(
                f"tuned A3 config does not exist: {tuned_a3_config}"
            )


def _offline_trace_plan_command(
    *,
    python_bin: str,
    scenario: str,
    ue_ids: Sequence[str],
    calibration_seed: Optional[int],
    evaluation_seeds: Sequence[int],
    output_root: Path,
    samples: int,
    interval_s: float,
    policies: Sequence[str],
) -> str:
    parts = [
        python_bin,
        "-m",
        "scripts.policy_comparison.prepare_trace_plan",
        "--scenario",
        scenario,
    ]
    for ue_id in ue_ids:
        parts.extend(["--ue-id", ue_id])
    if calibration_seed is not None:
        parts.extend(["--calibration-seed", str(calibration_seed)])
    parts.extend(["--evaluation-seed", ",".join(str(seed) for seed in evaluation_seeds)])
    parts.extend(
        [
            "--output-root",
            str(output_root),
            "--samples",
            str(samples),
            "--interval-s",
            str(interval_s),
            "--policies",
            ",".join(policies),
        ]
    )
    return _quote(parts)


def _planned_live_run(
    *,
    python_bin: str,
    scenario: str,
    seed: int,
    duration_minutes: int,
    output_dir: Path,
    policies: Sequence[str],
    env_file: Path,
    tuned_a3_config: Optional[Path],
) -> PlannedLiveRun:
    policy_arg = ",".join(policies)
    readiness_parts = [
        "./scripts/check_experiment_readiness.sh",
        "--scenario",
        scenario,
        "--output",
        str(output_dir),
        "--env-file",
        str(env_file),
        "--policies",
        policy_arg,
    ]
    if tuned_a3_config is not None:
        readiness_parts.extend(["--tuned-a3-config", str(tuned_a3_config)])

    base_run_parts = [
        python_bin,
        "scripts/run_enhanced_experiment.py",
        "--env-file",
        str(env_file),
        "--scenario",
        scenario,
        "--seed",
        str(seed),
        "--duration",
        str(duration_minutes),
        "--policies",
        policy_arg,
        "--output",
        str(output_dir),
    ]
    if tuned_a3_config is not None:
        base_run_parts.extend(["--tuned-a3-config", str(tuned_a3_config)])

    validation_parts = [
        python_bin,
        "-m",
        "scripts.policy_comparison.validate_comparison_outputs",
        "--path",
        str(output_dir),
        "--expected-policies",
        policy_arg,
        "--report-json",
        str(output_dir) + "_validation.json",
    ]

    return PlannedLiveRun(
        scenario=scenario,
        seed=seed,
        duration_minutes=duration_minutes,
        output_dir=str(output_dir),
        readiness_command=_quote(readiness_parts),
        plan_only_command=_quote([*base_run_parts, "--plan-only"]),
        run_command=_quote(base_run_parts),
        validation_command=_quote(validation_parts),
    )


def _statistics_commands(
    *,
    python_bin: str,
    output_root: Path,
    scenario: str,
    runs: Sequence[PlannedLiveRun],
    policies: Sequence[str],
) -> List[str]:
    commands: List[str] = []
    comparison_pairs = [("fixed_a3_baseline", "ml")]
    if "tuned_a3_baseline" in policies:
        comparison_pairs.append(("fixed_a3_baseline", "tuned_a3_baseline"))
        comparison_pairs.append(("tuned_a3_baseline", "ml"))
    for reference_policy, candidate_policy in comparison_pairs:
        parts = [
            python_bin,
            "-m",
            "scripts.policy_comparison.summarize_policy_statistics",
        ]
        for run in runs:
            parts.extend(["--run", run.output_dir])
        parts.extend(
            [
                "--evidence-type",
                "live_experiment",
                "--reference-policy",
                reference_policy,
                "--candidate-policy",
                candidate_policy,
                "--metrics",
                "total_handovers,pingpong_suppressions,qos_compliance_ok,qos_compliance_failed",
                "--output-dir",
                str(
                    output_root
                    / "statistics"
                    / f"{scenario}_{reference_policy}_vs_{candidate_policy}"
                ),
            ]
        )
        commands.append(_quote(parts))
    return commands


def _quote(parts: Sequence[str]) -> str:
    return " ".join(shlex.quote(str(part)) for part in parts)


def _offline_commands_file(plan: ComparisonCampaignPlan) -> str:
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        "# Offline planning command. This does not run the full thesis experiment.",
    ]
    if plan.offline_trace_plan_command:
        lines.append(plan.offline_trace_plan_command)
    lines.append("")
    return "\n".join(lines)


def _live_commands_file(plan: ComparisonCampaignPlan) -> str:
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        "# Future live commands. Run readiness first. Do not execute until approved.",
    ]
    for run in [*plan.primary_live_runs, *plan.secondary_live_runs]:
        lines.extend(
            [
                "",
                f"# {run.scenario} seed {run.seed}",
                run.readiness_command,
                run.plan_only_command,
                "# Execute the next line only when starting the real live run:",
                "# " + run.run_command,
            ]
        )
    lines.append("")
    return "\n".join(lines)


def _analysis_commands_file(plan: ComparisonCampaignPlan) -> str:
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        "# Post-run validation and statistics commands.",
        "# Run only after the corresponding live runs have completed.",
        "",
        "# Validate completed run artifacts.",
        *plan.validation_commands,
        "",
        "# Generate paired statistical reports after validation passes.",
        *plan.statistics_commands,
        "",
    ]
    return "\n".join(lines)
