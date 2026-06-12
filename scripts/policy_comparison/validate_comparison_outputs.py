#!/usr/bin/env python3
"""Validate completed policy comparison outputs without running experiments."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

if __package__ in {None, ""}:  # pragma: no cover - direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.policy_comparison.output_validation import (
    validate_comparison_output,
    validation_summary_lines,
    write_validation_report,
)


def _parse_policy_list(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    policies = [item.strip() for item in raw.split(",") if item.strip()]
    return policies or None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate completed offline replay or live experiment outputs. "
            "This command only reads artifacts and never runs the thesis experiment."
        )
    )
    parser.add_argument(
        "--path",
        required=True,
        help="Run directory, summary.json, or experiment_summary.json to validate.",
    )
    parser.add_argument(
        "--expected-policies",
        help="Comma-separated policy names expected in the output.",
    )
    parser.add_argument(
        "--allow-empty-neighbour-measurements",
        action="store_true",
        help=(
            "Do not fail offline decision logs when a decision has no neighbour "
            "measurements. Leave disabled for thesis comparison validation."
        ),
    )
    parser.add_argument(
        "--report-json",
        help="Optional path for the JSON validation report.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    report = validate_comparison_output(
        Path(args.path),
        expected_policies=_parse_policy_list(args.expected_policies),
        require_neighbour_measurements=not args.allow_empty_neighbour_measurements,
    )
    for line in validation_summary_lines(report):
        print(line)
    if args.report_json:
        write_validation_report(report, Path(args.report_json))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
