#!/usr/bin/env python3
"""Summarize candidate-complexity coverage for policy-free traces."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

if __package__ in {None, ""}:  # pragma: no cover - direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.policy_comparison.complexity import (  # noqa: E402
    candidate_complexity_for_record,
    complexity_bucket,
)
from scripts.policy_comparison.schemas import MeasurementTraceRecord  # noqa: E402
from scripts.policy_comparison.trace_io import read_trace_jsonl  # noqa: E402


DEFAULT_THRESHOLDS = (3, 4, 5)
DEFAULT_MIN_HIGH_COUNT = 500
DEFAULT_MIN_HIGH_FRACTION = 0.15
DEFAULT_MINIMUM_THRESHOLD = 3


def parse_csv_ints(raw: str) -> list[int]:
    values = [int(item.strip()) for item in raw.split(",") if item.strip()]
    if not values:
        raise ValueError("at least one threshold is required")
    if len(set(values)) != len(values):
        raise ValueError("thresholds must not contain duplicates")
    if any(value < 1 for value in values):
        raise ValueError("thresholds must be positive")
    return values


def summarize_trace_records(
    records: Sequence[MeasurementTraceRecord],
    *,
    trace_path: str | None = None,
    thresholds: Sequence[int] = DEFAULT_THRESHOLDS,
    min_high_count: int = DEFAULT_MIN_HIGH_COUNT,
    min_high_fraction: float = DEFAULT_MIN_HIGH_FRACTION,
    minimum_threshold: int = DEFAULT_MINIMUM_THRESHOLD,
) -> dict[str, Any]:
    if min_high_count < 0:
        raise ValueError("min_high_count must be non-negative")
    if not 0.0 <= min_high_fraction <= 1.0:
        raise ValueError("min_high_fraction must be in [0, 1]")

    candidate_counts = [
        candidate_complexity_for_record(record).viable_candidate_count
        for record in records
    ]
    histogram = Counter(candidate_counts)
    threshold_summaries: dict[str, dict[str, Any]] = {}
    total = len(candidate_counts)

    for threshold in thresholds:
        bucket_counts = Counter(
            complexity_bucket(count, high_complexity_threshold=threshold)
            for count in candidate_counts
        )
        high_count = int(bucket_counts.get("high", 0))
        high_fraction = (high_count / total) if total else 0.0
        threshold_summaries[str(threshold)] = {
            "sparse": int(bucket_counts.get("sparse", 0)),
            "moderate": int(bucket_counts.get("moderate", 0)),
            "high": high_count,
            "high_fraction": high_fraction,
            "minimum_pass": (
                high_count >= min_high_count
                or high_fraction >= min_high_fraction
            ),
        }

    minimum = threshold_summaries.get(str(minimum_threshold))
    if minimum is None:
        raise ValueError(
            f"minimum_threshold {minimum_threshold} is not in thresholds"
        )

    return {
        "trace": trace_path,
        "record_count": total,
        "candidate_count_histogram": {
            str(key): int(histogram[key]) for key in sorted(histogram)
        },
        "thresholds": threshold_summaries,
        "minimum_threshold": minimum_threshold,
        "minimum_pass": bool(minimum["minimum_pass"]),
    }


def summarize_trace_complexity(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = Path(args.output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"output directory already exists and is not empty: {output_dir}")

    thresholds = parse_csv_ints(args.thresholds)
    if args.minimum_threshold not in thresholds:
        raise ValueError("--minimum-threshold must be present in --thresholds")

    traces = []
    fail_reasons: list[str] = []
    for raw_path in args.trace:
        path = Path(raw_path)
        records = read_trace_jsonl(path)
        summary = summarize_trace_records(
            records,
            trace_path=str(path),
            thresholds=thresholds,
            min_high_count=args.min_high_count,
            min_high_fraction=args.min_high_fraction,
            minimum_threshold=args.minimum_threshold,
        )
        traces.append(summary)
        if not summary["minimum_pass"]:
            minimum = summary["thresholds"][str(args.minimum_threshold)]
            fail_reasons.append(
                f"{path} has {minimum['high']} high-complexity records "
                f"({minimum['high_fraction']:.3f}) at threshold "
                f"{args.minimum_threshold}; requires >= {args.min_high_count} "
                f"or >= {args.min_high_fraction:.3f}"
            )

    report = {
        "pass": not fail_reasons,
        "fail_reasons": fail_reasons,
        "thresholds": thresholds,
        "minimum": {
            "threshold": args.minimum_threshold,
            "min_high_count": args.min_high_count,
            "min_high_fraction": args.min_high_fraction,
            "rule": "pass when high_count >= min_high_count or high_fraction >= min_high_fraction",
        },
        "traces": traces,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "trace_complexity_summary.json").write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (output_dir / "trace_complexity_summary.md").write_text(
        render_markdown(report),
        encoding="utf-8",
    )
    return report


def render_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Trace Complexity Summary",
        "",
        f"Pass: `{str(report.get('pass')).lower()}`",
        "",
        "| Trace | Records | T=3 High | T=3 High Fraction | Minimum Pass |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for item in report.get("traces", []):
        if not isinstance(item, Mapping):
            continue
        threshold_3 = item.get("thresholds", {}).get("3", {})
        if not isinstance(threshold_3, Mapping):
            threshold_3 = {}
        lines.append(
            "| {trace} | {records} | {high} | {fraction:.3f} | `{passed}` |".format(
                trace=item.get("trace"),
                records=item.get("record_count", 0),
                high=threshold_3.get("high", 0),
                fraction=float(threshold_3.get("high_fraction", 0.0)),
                passed=str(item.get("minimum_pass")).lower(),
            )
        )

    fail_reasons = report.get("fail_reasons") or []
    if fail_reasons:
        lines.extend(["", "## Fail Reasons", ""])
        lines.extend(f"- {reason}" for reason in fail_reasons)
    lines.append("")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument(
        "--trace",
        action="append",
        required=True,
        help="Canonical policy-free trace JSONL. Can be repeated.",
    )
    parser.add_argument("--output-dir", required=True, help="Fresh output directory.")
    parser.add_argument(
        "--thresholds",
        default="3,4,5",
        help="Comma-separated high-complexity thresholds to summarize.",
    )
    parser.add_argument(
        "--minimum-threshold",
        type=int,
        default=DEFAULT_MINIMUM_THRESHOLD,
        help="Threshold whose coverage controls command success. Default: 3.",
    )
    parser.add_argument(
        "--min-high-count",
        type=int,
        default=DEFAULT_MIN_HIGH_COUNT,
        help="Minimum high-complexity record count per trace. Default: 500.",
    )
    parser.add_argument(
        "--min-high-fraction",
        type=float,
        default=DEFAULT_MIN_HIGH_FRACTION,
        help="Minimum high-complexity record fraction per trace. Default: 0.15.",
    )
    parser.add_argument(
        "--no-enforce",
        action="store_true",
        help="Write the report but exit 0 even when coverage is insufficient.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        report = summarize_trace_complexity(args)
    except Exception as exc:  # noqa: BLE001 - command should fail visibly
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(report, indent=2, sort_keys=True))
    if not report["pass"] and not args.no_enforce:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
