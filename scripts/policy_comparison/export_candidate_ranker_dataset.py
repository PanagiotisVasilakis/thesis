#!/usr/bin/env python3
"""Export a labeled candidate-ranker dataset from policy-free traces."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.policy_comparison.candidate_ranker import (  # noqa: E402
    build_labeled_candidate_ranker_dataset,
)
from scripts.policy_comparison.candidate_ranker_artifact import (  # noqa: E402
    select_feature_columns,
)
from scripts.policy_comparison.schemas import MeasurementTraceRecord  # noqa: E402
from scripts.policy_comparison.summarize_trace_complexity import (  # noqa: E402
    summarize_trace_records,
)
from scripts.policy_comparison.trace_io import read_trace_jsonl  # noqa: E402


DEFAULT_MIN_HIGH_COMPLEXITY_ROWS = 1000


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_seed_list(raw: str | None) -> list[int]:
    if not raw:
        return []
    return [int(item.strip()) for item in raw.split(",") if item.strip()]


def load_records_by_trace(
    trace_paths: Sequence[Path],
) -> dict[Path, list[MeasurementTraceRecord]]:
    records_by_trace: dict[Path, list[MeasurementTraceRecord]] = {}
    for path in trace_paths:
        records_by_trace[path] = read_trace_jsonl(path)
    records = [
        record
        for trace_records in records_by_trace.values()
        for record in trace_records
    ]
    if not records:
        raise ValueError("ranker traces produced no records")
    return records_by_trace


def flatten_records(
    records_by_trace: Mapping[Path, Sequence[MeasurementTraceRecord]],
) -> list[MeasurementTraceRecord]:
    records: list[MeasurementTraceRecord] = []
    for trace_records in records_by_trace.values():
        records.extend(trace_records)
    return records


def validate_seed_split(
    records: Sequence[MeasurementTraceRecord],
    forbidden_evaluation_seeds: Sequence[int],
) -> None:
    training_seeds = {record.seed for record in records}
    overlap = training_seeds.intersection(forbidden_evaluation_seeds)
    if overlap:
        raise ValueError(
            "ranker training seed(s) overlap forbidden evaluation seed(s): "
            + ", ".join(str(seed) for seed in sorted(overlap))
        )


def export_ranker_dataset(args: argparse.Namespace) -> Dict[str, Any]:
    output = Path(args.output)
    manifest_path = Path(args.manifest) if args.manifest else Path(f"{output}.manifest.json")
    if output.exists() and not args.overwrite:
        raise ValueError(f"output already exists: {output}")
    if manifest_path.exists() and not args.overwrite:
        raise ValueError(f"manifest already exists: {manifest_path}")

    trace_paths = [Path(path) for path in args.trace]
    records_by_trace = load_records_by_trace(trace_paths)
    records = flatten_records(records_by_trace)
    validate_seed_split(records, parse_seed_list(args.forbid_evaluation_seed))

    rows = build_labeled_candidate_ranker_dataset(
        records,
        sequence_window_steps=args.sequence_window_steps,
        stay_margin_db=args.stay_margin_db,
        handover_penalty_db=args.handover_penalty_db,
        load_penalty_db=args.load_penalty_db,
        sinr_weight=args.sinr_weight,
        rsrq_weight=args.rsrq_weight,
        missing_future_cell_score=args.missing_future_cell_score,
        same_site_penalty_db=args.same_site_penalty_db,
        rf_regression_penalty_db=args.rf_regression_penalty_db,
        short_dwell_penalty_db=args.short_dwell_penalty_db,
        ping_pong_risk_penalty_db=args.ping_pong_risk_penalty_db,
        min_dwell_time_s=args.min_dwell_time_s,
    )
    if not rows:
        raise ValueError("ranker export produced no viable candidate rows")
    min_high_complexity_rows = int(
        getattr(args, "min_high_complexity_rows", DEFAULT_MIN_HIGH_COMPLEXITY_ROWS)
    )
    high_complexity_row_count = sum(
        1 for row in rows if str(row.get("complexity_bucket")) == "high"
    )
    if high_complexity_row_count < min_high_complexity_rows:
        raise ValueError(
            "ranker export produced insufficient high-complexity rows: "
            f"{high_complexity_row_count} < {min_high_complexity_rows}"
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")

    complexity_counts = Counter(str(row["complexity_bucket"]) for row in rows)
    selected_count = sum(int(row["selected_label"]) for row in rows)
    label_policy = {
        "name": "sequence_stay_aware_margin_ranker",
        "version": 2,
        "sequence_window_steps": args.sequence_window_steps,
        "stay_margin_db": args.stay_margin_db,
        "handover_penalty_db": args.handover_penalty_db,
        "load_penalty_db": args.load_penalty_db,
        "sinr_weight": args.sinr_weight,
        "rsrq_weight": args.rsrq_weight,
        "missing_future_cell_score": args.missing_future_cell_score,
        "same_site_penalty_db": args.same_site_penalty_db,
        "rf_regression_penalty_db": args.rf_regression_penalty_db,
        "short_dwell_penalty_db": args.short_dwell_penalty_db,
        "ping_pong_risk_penalty_db": args.ping_pong_risk_penalty_db,
        "min_dwell_time_s": args.min_dwell_time_s,
    }
    manifest = {
        "dataset_type": "candidate_ranker_jsonl",
        "output": str(output),
        "row_count": len(rows),
        "selected_row_count": selected_count,
        "positive_rate": selected_count / len(rows),
        "scenario_seeds": sorted({record.seed for record in records}),
        "scenarios": sorted({record.scenario for record in records}),
        "ue_count": len({record.ue_id for record in records}),
        "trace_paths": [str(path) for path in trace_paths],
        "trace_hashes": {str(path): sha256_file(path) for path in trace_paths},
        "label_policy": label_policy,
        "complexity_bucket_counts": dict(sorted(complexity_counts.items())),
        "high_complexity_row_count": high_complexity_row_count,
        "min_high_complexity_rows": min_high_complexity_rows,
        "trace_complexity_summaries": [
            summarize_trace_records(trace_records, trace_path=str(path))
            for path, trace_records in records_by_trace.items()
        ],
        "feature_columns": select_feature_columns(rows),
        "label_columns": [
            "selected_label",
            "selected_label_tie_count",
            "rank_label",
            "handover_desirable",
            "candidate_sequence_score",
            "candidate_raw_sequence_score",
            "serving_sequence_score",
            "stay_sequence_score",
            "utility_margin_vs_serving",
            "utility_margin_vs_stay",
            "handover_action_penalty",
            "same_site_penalty",
            "rf_regression_penalty",
            "short_dwell_penalty",
            "ping_pong_risk_penalty",
            "total_decision_penalty",
        ],
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument(
        "--trace",
        action="append",
        required=True,
        help="Policy-free trace JSONL. May be supplied multiple times.",
    )
    parser.add_argument("--output", required=True, help="Output candidate-ranker JSONL.")
    parser.add_argument("--manifest", help="Optional manifest JSON path.")
    parser.add_argument(
        "--forbid-evaluation-seed",
        default="42,43,44",
        help="Comma-separated evaluation seeds that must not appear in ranker training traces.",
    )
    parser.add_argument("--sequence-window-steps", type=int, default=3)
    parser.add_argument("--stay-margin-db", type=float, default=2.0)
    parser.add_argument("--handover-penalty-db", type=float, default=1.0)
    parser.add_argument("--load-penalty-db", type=float, default=4.0)
    parser.add_argument("--sinr-weight", type=float, default=0.2)
    parser.add_argument("--rsrq-weight", type=float, default=0.1)
    parser.add_argument("--missing-future-cell-score", type=float, default=-160.0)
    parser.add_argument("--same-site-penalty-db", type=float, default=6.0)
    parser.add_argument("--rf-regression-penalty-db", type=float, default=4.0)
    parser.add_argument("--short-dwell-penalty-db", type=float, default=4.0)
    parser.add_argument("--ping-pong-risk-penalty-db", type=float, default=5.0)
    parser.add_argument("--min-dwell-time-s", type=float, default=10.0)
    parser.add_argument(
        "--min-high-complexity-rows",
        type=int,
        default=DEFAULT_MIN_HIGH_COMPLEXITY_ROWS,
        help=(
            "Minimum high-complexity candidate rows required in the exported "
            "dataset. Default: 1000."
        ),
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = export_ranker_dataset(args)
    except Exception as exc:  # noqa: BLE001 - command should fail visibly
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
