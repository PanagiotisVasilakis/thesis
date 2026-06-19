#!/usr/bin/env python3
"""Export physical cost-to-go oracle labels from training traces only."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Sequence

from .oracle_policy import ORACLE_LABEL_POLICY, feature_columns, solve_cost_to_go
from .trace_io import read_trace_jsonl
from .validate_physical_trace import validate_trace


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def export_dataset(
    traces: Sequence[Path],
    *,
    output: Path,
    manifest: Path,
    forbidden_seeds: set[int],
    horizon_steps: int = 20,
) -> dict:
    rows: list[dict] = []
    trace_hashes: dict[str, str] = {}
    seeds: set[int] = set()
    for path in traces:
        validation = validate_trace(path, require_complexity=False)
        if not validation["pass"]:
            raise ValueError(f"physical trace validation failed for {path}: {validation['errors']}")
        records = read_trace_jsonl(path)
        trace_seeds = {record.seed for record in records}
        if trace_seeds.intersection(forbidden_seeds):
            raise ValueError("evaluation seed leakage in oracle dataset")
        seeds.update(trace_seeds)
        grouped: dict[tuple[str, int, str], list] = defaultdict(list)
        for record in records:
            grouped[(record.scenario, record.seed, record.ue_id)].append(record)
        for trajectory in grouped.values():
            rows.extend(solve_cost_to_go(trajectory, horizon_steps=horizon_steps))
        trace_hashes[str(path)] = _sha256(path)
    if not rows:
        raise ValueError("oracle dataset contains no rows")
    columns = feature_columns(rows)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    report = {
        "label_policy": {
            "name": ORACLE_LABEL_POLICY,
            "discount": 0.98,
            "horizon_steps": horizon_steps,
            "penalties": {
                "handover_action": 1.0,
                "short_dwell": 3.0,
                "ping_pong": 5.0,
                "low_rsrp": 2.0,
                "rlf": 8.0,
                "low_sinr": 2.0,
                "poor_target_sinr": 3.0,
                "qos_violation": 10.0,
                "load_regression": 2.0,
                "target_disappearance": 30.0
            }
        },
        "dataset_path": str(output),
        "dataset_sha256": _sha256(output),
        "trace_hashes": trace_hashes,
        "training_seeds": sorted(seeds),
        "forbidden_evaluation_seeds": sorted(forbidden_seeds),
        "row_count": len(rows),
        "snapshot_group_count": len({row["snapshot_group"] for row in rows}),
        "label_distribution": dict(Counter(row["selected_label"] for row in rows)),
        "feature_columns": columns,
        "excluded_raw_id_columns": ["ue_id", "serving_cell", "action_cell"],
        "horizon_steps": horizon_steps,
    }
    manifest.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument("--trace", action="append", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--forbid-evaluation-seed", default="201,202,203,204,205,206,207,208,209,210")
    parser.add_argument("--horizon-steps", type=int, default=20)
    args = parser.parse_args(argv)
    forbidden = {int(item) for item in args.forbid_evaluation_seed.split(",") if item.strip()}
    try:
        report = export_dataset(
            args.trace,
            output=args.output,
            manifest=args.manifest,
            forbidden_seeds=forbidden,
            horizon_steps=args.horizon_steps,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
