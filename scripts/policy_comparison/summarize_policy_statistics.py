#!/usr/bin/env python3
"""Generate statistical reports from completed policy comparison runs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

if __package__ in {None, ""}:  # pragma: no cover - direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.policy_comparison.statistical_report import (
    StatisticalReportError,
    build_statistical_report,
    load_run_metrics,
    write_statistical_report,
)


def _parse_metrics(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    metrics = [item.strip() for item in raw.split(",") if item.strip()]
    if not metrics:
        raise StatisticalReportError("--metrics must not be empty when provided")
    return metrics


def run(args: argparse.Namespace) -> int:
    runs = [load_run_metrics(Path(path)) for path in args.run]
    report = build_statistical_report(
        runs,
        reference_policy=args.reference_policy,
        candidate_policy=args.candidate_policy,
        metrics=_parse_metrics(args.metrics),
        evidence_type=args.evidence_type,
        alpha=args.alpha,
        bootstrap_iterations=args.bootstrap_iterations,
        seed=args.seed,
    )
    json_path, markdown_path = write_statistical_report(report, Path(args.output_dir))
    print(f"Statistical report written to {json_path}")
    print(f"Markdown report written to {markdown_path}")
    if report.warnings:
        print("Warnings:")
        for warning in report.warnings:
            print(f"- {warning}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Summarize completed offline replay or live experiment summaries. "
            "This command does not run experiments."
        )
    )
    parser.add_argument(
        "--run",
        action="append",
        required=True,
        help=(
            "Run directory or summary JSON file. Can be repeated. Directories "
            "must contain summary.json or experiment_summary.json."
        ),
    )
    parser.add_argument("--output-dir", required=True, help="Fresh output directory.")
    parser.add_argument("--reference-policy", required=True)
    parser.add_argument("--candidate-policy", required=True)
    parser.add_argument(
        "--metrics",
        help="Optional comma-separated metric names. Defaults to common numeric metrics.",
    )
    parser.add_argument(
        "--evidence-type",
        default="all",
        choices=("all", "offline_replay", "live_experiment"),
        help="Evidence type to include. Default: all, reported separately.",
    )
    parser.add_argument("--alpha", type=float, default=0.05)
    parser.add_argument("--bootstrap-iterations", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=42)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except Exception as exc:  # noqa: BLE001 - command should fail visibly
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
