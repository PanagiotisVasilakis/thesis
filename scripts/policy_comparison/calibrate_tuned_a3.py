#!/usr/bin/env python3
"""Generate a reusable tuned A3 config from one calibration trace."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Sequence

if __package__ in {None, ""}:  # pragma: no cover - direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.policy_comparison.policy_adapters import (
    ensure_baseline_service_importable,
    trace_record_to_baseline_snapshot,
)
from scripts.policy_comparison.schemas import MeasurementTraceRecord
from scripts.policy_comparison.trace_io import read_trace_jsonl


def ensure_fresh_output_file(path: Path) -> None:
    if path.exists() and path.stat().st_size > 0:
        raise ValueError(f"output config already exists and is not empty: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)


def validate_single_calibration_trace(
    records: Sequence[MeasurementTraceRecord],
) -> Dict[str, Any]:
    if not records:
        raise ValueError("calibration trace is empty")

    scenarios = {record.scenario for record in records}
    if len(scenarios) != 1:
        raise ValueError("calibration trace must contain exactly one scenario")

    seeds = {record.seed for record in records}
    if len(seeds) != 1:
        raise ValueError("calibration trace must contain exactly one seed")

    topology_hashes = {record.topology_hash for record in records}
    if None in topology_hashes or len(topology_hashes) != 1:
        raise ValueError("calibration trace must contain exactly one topology_hash")

    for record in records:
        if not record.visible_cells:
            raise ValueError("calibration trace contains a record without visible cells")
        for cell in record.visible_cells:
            float(cell.rsrp_dbm)

    return {
        "scenario": next(iter(scenarios)),
        "seed": next(iter(seeds)),
        "topology_hash": next(iter(topology_hashes)),
        "record_count": len(records),
    }


def compact_evaluated_configurations(tuning_result) -> list[Dict[str, Any]]:
    compact = []
    for result in tuning_result.evaluated_configurations:
        compact.append(
            {
                "parameters": result.parameters.to_dict(),
                "score": result.score,
                "handover_count": result.handover_count,
                "ping_pong_count": result.ping_pong_count,
                "low_quality_steps": result.low_quality_steps,
            }
        )
    return compact


def build_tuned_a3_config(
    *,
    calibration_trace: Path,
    records: Sequence[MeasurementTraceRecord],
) -> Dict[str, Any]:
    ensure_baseline_service_importable()
    from handover_baseline import A3ParameterGrid  # type: ignore[import-not-found]
    from handover_baseline.tuned_a3_policy import A3TraceTuner  # type: ignore[import-not-found]

    calibration = validate_single_calibration_trace(records)
    snapshots = [trace_record_to_baseline_snapshot(record) for record in records]
    tuning_result = A3TraceTuner(A3ParameterGrid()).fit(snapshots)
    evaluated = compact_evaluated_configurations(tuning_result)

    return {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": "calibration_trace_grid_search",
        "selected_parameters": tuning_result.selected_parameters.to_dict(),
        "selected_score": tuning_result.selected_score,
        "objective": tuning_result.objective,
        "calibration": {
            "trace": str(calibration_trace),
            "scenario": calibration["scenario"],
            "seed": calibration["seed"],
            "topology_hash": calibration["topology_hash"],
            "record_count": calibration["record_count"],
        },
        "record_count": calibration["record_count"],
        "evaluated_configuration_scores": evaluated,
        "evaluated_configurations": evaluated,
        "uses_ml_outputs": False,
    }


def calibrate_tuned_a3_config(calibration_trace: Path, output: Path) -> Path:
    ensure_fresh_output_file(output)
    records = read_trace_jsonl(calibration_trace)
    config = build_tuned_a3_config(
        calibration_trace=calibration_trace,
        records=records,
    )
    output.write_text(json.dumps(config, indent=2, sort_keys=True), encoding="utf-8")
    return output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Tune non-ML A3 parameters on one calibration trace and write a "
            "reusable tuned_a3_config.json artifact."
        )
    )
    parser.add_argument("--calibration-trace", required=True, help="Calibration trace JSONL.")
    parser.add_argument("--output", required=True, help="Fresh tuned A3 config JSON path.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        output = calibrate_tuned_a3_config(
            calibration_trace=Path(args.calibration_trace),
            output=Path(args.output),
        )
    except Exception as exc:  # noqa: BLE001 - command should fail visibly
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Tuned A3 config written to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
