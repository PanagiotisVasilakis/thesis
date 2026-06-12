#!/usr/bin/env python3
"""Prepare a validation-grade ML-vs-A3 campaign command plan."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

if __package__ in {None, ""}:  # pragma: no cover - direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.policy_comparison.campaign_plan import (
    CampaignPlanError,
    build_comparison_campaign_plan,
    ensure_fresh_campaign_root,
    write_comparison_campaign_plan,
)
from scripts.policy_comparison.trace_plan import parse_int_list, parse_string_list


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Write command plans for a future validation-grade ML vs fixed/tuned "
            "A3 comparison campaign. This does not run readiness, Docker, "
            "traces, replay, live experiments, validation, or statistics."
        )
    )
    parser.add_argument("--campaign-name", required=True)
    parser.add_argument("--output-root", required=True, help="Fresh campaign directory.")
    parser.add_argument("--primary-scenario", default="highway")
    parser.add_argument("--secondary-scenario")
    parser.add_argument(
        "--evaluation-seed",
        action="append",
        required=True,
        help="Evaluation seed. Can be repeated or comma-separated.",
    )
    parser.add_argument(
        "--calibration-seed",
        type=int,
        help="Separate calibration seed required when tuned A3 policies are selected.",
    )
    parser.add_argument(
        "--ue-id",
        action="append",
        required=True,
        help="UE ID for offline trace capture planning. Can be repeated or comma-separated.",
    )
    parser.add_argument(
        "--policies",
        default="ml,fixed_a3_baseline",
        help=(
            "Comma-separated policies for future runs. Supported campaign "
            "policies: ml,fixed_a3_baseline,tuned_a3_baseline,"
            "complexity_aware_ml_a3."
        ),
    )
    parser.add_argument("--duration", type=int, default=10)
    parser.add_argument("--secondary-duration", type=int)
    parser.add_argument(
        "--env-file",
        default="5g-network-optimization/.env",
        help="Env file used by generated readiness/live commands.",
    )
    parser.add_argument(
        "--tuned-a3-config",
        help="Required when policies include tuned A3 or complexity-aware ML+A3.",
    )
    parser.add_argument("--samples", type=int, default=60)
    parser.add_argument("--interval-s", type=float, default=1.0)
    parser.add_argument("--python-bin", default=".venv/bin/python")
    return parser


def run(args: argparse.Namespace) -> int:
    output_root = Path(args.output_root)
    policies = parse_string_list([args.policies], field_name="policies")
    ue_ids = parse_string_list(args.ue_id, field_name="ue_ids")
    evaluation_seeds = parse_int_list(
        args.evaluation_seed,
        field_name="evaluation_seeds",
    )
    plan = build_comparison_campaign_plan(
        campaign_name=args.campaign_name,
        output_root=output_root,
        primary_scenario=args.primary_scenario,
        secondary_scenario=args.secondary_scenario,
        evaluation_seeds=evaluation_seeds,
        policies=policies,
        ue_ids=ue_ids,
        duration_minutes=args.duration,
        secondary_duration_minutes=args.secondary_duration,
        calibration_seed=args.calibration_seed,
        env_file=Path(args.env_file),
        tuned_a3_config=Path(args.tuned_a3_config) if args.tuned_a3_config else None,
        samples=args.samples,
        interval_s=args.interval_s,
        python_bin=args.python_bin,
    )
    ensure_fresh_campaign_root(output_root)
    plan_path, offline_path, live_path, analysis_path = write_comparison_campaign_plan(
        plan,
        output_root,
    )
    print(f"Comparison campaign plan written to {plan_path}")
    print(f"Offline commands written to {offline_path}")
    print(f"Live commands written to {live_path}")
    print(f"Analysis commands written to {analysis_path}")
    print("No experiment commands were executed.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except (CampaignPlanError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
