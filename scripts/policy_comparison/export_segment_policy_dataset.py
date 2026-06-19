#!/usr/bin/env python3
"""Export a labeled two-stage segment-controller dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.policy_comparison.segment_controller import (  # noqa: E402
    SEGMENT_LABEL_POLICY_VERSION,
    build_segment_policy_dataset,
    select_segment_feature_columns,
)
from scripts.policy_comparison.schemas import MeasurementTraceRecord  # noqa: E402
from scripts.policy_comparison.summarize_trace_complexity import (  # noqa: E402
    summarize_trace_records,
)
from scripts.policy_comparison.trace_io import read_trace_jsonl  # noqa: E402


DEFAULT_FORBIDDEN_EVALUATION_SEEDS = "61,62,63,64,65"
DEFAULT_MIN_HIGH_COMPLEXITY_CANDIDATE_ROWS = 2500
DEFAULT_MIN_HIGH_COMPLEXITY_SNAPSHOT_GROUPS = 1000


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
    if not trace_paths:
        raise ValueError("at least one trace is required")
    records_by_trace = {path: read_trace_jsonl(path) for path in trace_paths}
    if not any(records_by_trace.values()):
        raise ValueError("segment traces produced no records")
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
            "segment training seed(s) overlap forbidden evaluation seed(s): "
            + ", ".join(str(seed) for seed in sorted(overlap))
        )


def validate_trace_consistency(records: Sequence[MeasurementTraceRecord]) -> dict[str, Any]:
    scenarios = {record.scenario for record in records}
    if len(scenarios) != 1:
        raise ValueError("segment calibration traces must share one scenario")
    topology_hashes = {record.topology_hash for record in records}
    if None in topology_hashes or len(topology_hashes) != 1:
        raise ValueError("segment calibration traces must share one topology_hash")
    for record in records:
        if not record.visible_cells:
            raise ValueError("segment trace contains a record without visible cells")
    return {
        "scenario": next(iter(scenarios)),
        "topology_hash": next(iter(topology_hashes)),
        "calibration_seeds": sorted({record.seed for record in records}),
        "record_count": len(records),
    }


def export_segment_dataset(args: argparse.Namespace) -> dict[str, Any]:
    output = Path(args.output)
    manifest_path = Path(args.manifest) if args.manifest else Path(f"{output}.manifest.json")
    if output.exists() and not args.overwrite:
        raise ValueError(f"output already exists: {output}")
    if manifest_path.exists() and not args.overwrite:
        raise ValueError(f"manifest already exists: {manifest_path}")

    trace_paths = [Path(path) for path in args.trace]
    records_by_trace = load_records_by_trace(trace_paths)
    records = flatten_records(records_by_trace)
    forbidden_evaluation_seeds = parse_seed_list(args.forbid_evaluation_seed)
    validate_seed_split(records, forbidden_evaluation_seeds)
    consistency = validate_trace_consistency(records)

    dataset = build_segment_policy_dataset(
        records,
        segment_horizon_steps=args.segment_horizon_steps,
        min_segment_duration_s=args.min_segment_duration_s,
        max_segment_duration_s=args.max_segment_duration_s,
        stay_margin=args.stay_margin,
        handover_action_penalty=args.handover_action_penalty,
        ping_pong_penalty=args.ping_pong_penalty,
        sparse_reentry_penalty=args.sparse_reentry_penalty,
        weak_serving_rsrp_dbm=args.weak_serving_rsrp_dbm,
        invalid_target_penalty=args.invalid_target_penalty,
        missing_future_cell_score=args.missing_future_cell_score,
        load_penalty=args.load_penalty,
        sinr_weight=args.sinr_weight,
        rsrq_weight=args.rsrq_weight,
        qos_violation_penalty=args.qos_violation_penalty,
        a3_recovery_margin_db=args.a3_recovery_margin_db,
        post_segment_churn_penalty=args.post_segment_churn_penalty,
        high_reject_recovery_risk_penalty=args.high_reject_recovery_risk_penalty,
    )
    rows = dataset.rows
    if not rows:
        raise ValueError("segment export produced no rows")

    candidate_rows = dataset.candidate_rows
    entry_rows = dataset.entry_rows
    exit_rows = dataset.exit_rows
    high_candidate_rows = len(candidate_rows)
    high_snapshot_groups = len(
        {str(row.get("snapshot_group")) for row in entry_rows}
    )
    if high_candidate_rows < args.min_high_complexity_candidate_rows:
        raise ValueError(
            "segment export produced insufficient high-complexity candidate rows: "
            f"{high_candidate_rows} < {args.min_high_complexity_candidate_rows}"
        )
    if high_snapshot_groups < args.min_high_complexity_snapshot_groups:
        raise ValueError(
            "segment export produced insufficient high-complexity snapshot groups: "
            f"{high_snapshot_groups} < {args.min_high_complexity_snapshot_groups}"
        )
    _require_binary_label_coverage(entry_rows, "enter_ml_segment", "entry")
    _require_binary_label_coverage(exit_rows, "exit_segment_to_a3", "exit")
    _require_non_constant_target(candidate_rows, "segment_utility_margin_vs_stay")

    feature_columns = {
        "candidate": select_segment_feature_columns(rows, row_type="candidate"),
        "entry": select_segment_feature_columns(rows, row_type="entry"),
        "exit": select_segment_feature_columns(rows, row_type="exit"),
    }
    leaked = sorted(
        {"ue_id", "serving_cell", "candidate_cell"}.intersection(
            set(feature_columns["candidate"])
            | set(feature_columns["entry"])
            | set(feature_columns["exit"])
        )
    )
    if leaked:
        raise ValueError("raw ID columns leaked into segment features: " + ", ".join(leaked))

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")

    label_policy = {
        "version": SEGMENT_LABEL_POLICY_VERSION,
        "segment_horizon_steps": args.segment_horizon_steps,
        "min_segment_duration_s": args.min_segment_duration_s,
        "max_segment_duration_s": args.max_segment_duration_s,
        "stay_margin": args.stay_margin,
        "penalty_weights": dataset.metadata["penalty_weights"],
        "churn_feature_policy": {
            "a3_recovery_margin_db": args.a3_recovery_margin_db,
            "post_segment_churn_penalty": args.post_segment_churn_penalty,
            "high_reject_recovery_risk_penalty": args.high_reject_recovery_risk_penalty,
        },
    }
    manifest = {
        "dataset_type": "segment_policy_jsonl",
        "output": str(output),
        "row_count": len(rows),
        "row_type_counts": dataset.metadata["row_type_counts"],
        "candidate_row_count": len(candidate_rows),
        "entry_row_count": len(entry_rows),
        "exit_row_count": len(exit_rows),
        "high_complexity_candidate_row_count": high_candidate_rows,
        "high_complexity_snapshot_count": high_snapshot_groups,
        "min_high_complexity_candidate_rows": args.min_high_complexity_candidate_rows,
        "min_high_complexity_snapshot_groups": args.min_high_complexity_snapshot_groups,
        "scenario": consistency["scenario"],
        "topology_hash": consistency["topology_hash"],
        "calibration_seeds": consistency["calibration_seeds"],
        "forbidden_evaluation_seeds": forbidden_evaluation_seeds,
        "trace_paths": [str(path) for path in trace_paths],
        "trace_hashes": {str(path): sha256_file(path) for path in trace_paths},
        "trace_complexity_summaries": [
            summarize_trace_records(trace_records, trace_path=str(path))
            for path, trace_records in records_by_trace.items()
        ],
        "label_policy": label_policy,
        "feature_columns": feature_columns,
        "label_columns": [
            "enter_ml_segment",
            "exit_segment_to_a3",
            "segment_utility_margin_vs_stay",
        ],
        "segment_entry_label_distribution": _label_distribution(
            entry_rows,
            "enter_ml_segment",
        ),
        "segment_exit_label_distribution": _label_distribution(
            exit_rows,
            "exit_segment_to_a3",
        ),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return manifest


def _require_binary_label_coverage(
    rows: Sequence[Mapping[str, Any]],
    label: str,
    name: str,
) -> None:
    values = {int(row[label]) for row in rows if label in row}
    if values != {0, 1}:
        raise ValueError(
            f"segment {name} labels must contain both positive and negative examples"
        )


def _require_non_constant_target(
    rows: Sequence[Mapping[str, Any]],
    target: str,
    *,
    min_std: float = 1e-6,
) -> None:
    values = [float(row[target]) for row in rows if target in row]
    if not values:
        raise ValueError(f"segment target {target} is missing")
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    if not math.isfinite(variance) or math.sqrt(variance) < min_std:
        raise ValueError(f"segment target {target} is constant or near-constant")


def _label_distribution(
    rows: Sequence[Mapping[str, Any]],
    label: str,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(int(row.get(label, 0)))
        counts[key] = counts.get(key, 0) + 1
    return counts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument(
        "--trace",
        action="append",
        required=True,
        help="Policy-free calibration trace JSONL. May be supplied multiple times.",
    )
    parser.add_argument("--output", required=True, help="Output segment dataset JSONL.")
    parser.add_argument("--manifest", help="Optional manifest JSON path.")
    parser.add_argument(
        "--forbid-evaluation-seed",
        default=DEFAULT_FORBIDDEN_EVALUATION_SEEDS,
        help="Comma-separated evaluation seeds forbidden in calibration traces.",
    )
    parser.add_argument("--segment-horizon-steps", type=int, default=20)
    parser.add_argument("--min-segment-duration-s", type=float, default=6.0)
    parser.add_argument("--max-segment-duration-s", type=float, default=45.0)
    parser.add_argument("--stay-margin", type=float, default=2.0)
    parser.add_argument("--handover-action-penalty", type=float, default=1.0)
    parser.add_argument("--ping-pong-penalty", type=float, default=8.0)
    parser.add_argument("--sparse-reentry-penalty", type=float, default=8.0)
    parser.add_argument("--weak-serving-rsrp-dbm", type=float, default=-105.0)
    parser.add_argument("--invalid-target-penalty", type=float, default=30.0)
    parser.add_argument("--missing-future-cell-score", type=float, default=-160.0)
    parser.add_argument("--load-penalty", type=float, default=4.0)
    parser.add_argument("--sinr-weight", type=float, default=0.2)
    parser.add_argument("--rsrq-weight", type=float, default=0.1)
    parser.add_argument("--qos-violation-penalty", type=float, default=10.0)
    parser.add_argument("--a3-recovery-margin-db", type=float, default=3.0)
    parser.add_argument("--post-segment-churn-penalty", type=float, default=8.0)
    parser.add_argument("--high-reject-recovery-risk-penalty", type=float, default=6.0)
    parser.add_argument(
        "--min-high-complexity-candidate-rows",
        type=int,
        default=DEFAULT_MIN_HIGH_COMPLEXITY_CANDIDATE_ROWS,
    )
    parser.add_argument(
        "--min-high-complexity-snapshot-groups",
        type=int,
        default=DEFAULT_MIN_HIGH_COMPLEXITY_SNAPSHOT_GROUPS,
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        manifest = export_segment_dataset(args)
    except Exception as exc:  # noqa: BLE001 - command should fail visibly
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
