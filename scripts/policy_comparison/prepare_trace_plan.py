#!/usr/bin/env python3
"""Prepare separate calibration/evaluation trace command plans."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

if __package__ in {None, ""}:  # pragma: no cover - direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.policy_comparison.trace_plan import (
    TracePlanError,
    build_trace_preparation_plan,
    ensure_fresh_output_root,
    parse_int_list,
    parse_string_list,
    write_trace_preparation_plan,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare command files for separate calibration/evaluation trace "
            "capture and offline replay. This does not run capture, replay, or "
            "the thesis experiment."
        )
    )
    parser.add_argument("--scenario", required=True, help="Scenario name, e.g. highway.")
    parser.add_argument(
        "--ue-id",
        action="append",
        required=True,
        help="UE ID to include. Can be repeated or comma-separated.",
    )
    parser.add_argument(
        "--calibration-seed",
        action="append",
        default=[],
        help="Calibration seed. Required for tuned A3 and complexity-aware replay.",
    )
    parser.add_argument(
        "--evaluation-seed",
        action="append",
        required=True,
        help="Evaluation seed. Can be repeated or comma-separated.",
    )
    parser.add_argument("--output-root", required=True, help="Fresh plan directory.")
    parser.add_argument(
        "--samples",
        type=int,
        default=60,
        help="Samples per UE per trace. Default: 60.",
    )
    parser.add_argument(
        "--interval-s",
        type=float,
        default=1.0,
        help="Seconds between samples. Default: 1.0.",
    )
    parser.add_argument(
        "--timeout-s",
        type=float,
        default=5.0,
        help="HTTP timeout per capture request. Default: 5.0.",
    )
    parser.add_argument(
        "--policies",
        default="fixed_a3_baseline,tuned_a3_baseline",
        help=(
            "Comma-separated policies for replay commands. Default: "
            "fixed_a3_baseline,tuned_a3_baseline. Supports ml, classic baselines, "
            "and complexity_aware_ml_a3."
        ),
    )
    parser.add_argument("--nef-url", help="Optional NEF base URL for capture commands.")
    parser.add_argument("--ml-base-url", help="Optional ML base URL for replay commands.")
    parser.add_argument("--topology-hash", help="Optional topology hash label.")
    parser.add_argument("--topology-json", help="Optional topology JSON path.")
    parser.add_argument(
        "--python-bin",
        default=".venv/bin/python",
        help="Python command used in generated commands. Default: .venv/bin/python.",
    )
    return parser


def run(args: argparse.Namespace) -> int:
    output_root = Path(args.output_root)
    ensure_fresh_output_root(output_root)
    policies = parse_string_list([args.policies], field_name="policies")
    calibration_seeds = parse_int_list(
        args.calibration_seed,
        field_name="calibration_seeds",
    ) if args.calibration_seed else []
    evaluation_seeds = parse_int_list(
        args.evaluation_seed,
        field_name="evaluation_seeds",
    )

    plan = build_trace_preparation_plan(
        scenario=args.scenario,
        ue_ids=args.ue_id,
        calibration_seeds=calibration_seeds,
        evaluation_seeds=evaluation_seeds,
        output_root=output_root,
        samples=args.samples,
        interval_s=args.interval_s,
        timeout_s=args.timeout_s,
        policies=policies,
        nef_url=args.nef_url,
        ml_base_url=args.ml_base_url,
        topology_hash=args.topology_hash,
        topology_json=Path(args.topology_json) if args.topology_json else None,
        python_bin=args.python_bin,
    )
    plan_path, commands_path = write_trace_preparation_plan(plan, output_root)
    print(f"Trace plan written to {plan_path}")
    print(f"Commands written to {commands_path}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except (TracePlanError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
