#!/usr/bin/env python3
"""Generate a reusable tuned A3 config from calibration trace(s)."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

if __package__ in {None, ""}:  # pragma: no cover - direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.policy_comparison.policy_adapters import (
    TunedA3PolicyAdapter,
    ensure_baseline_service_importable,
    trace_record_to_baseline_snapshot,
)
from scripts.policy_comparison.replay import OfflineReplayRunner
from scripts.policy_comparison.schemas import MeasurementTraceRecord
from scripts.policy_comparison.trace_io import read_trace_jsonl


def ensure_fresh_output_file(path: Path) -> None:
    if path.exists() and path.stat().st_size > 0:
        raise ValueError(f"output config already exists and is not empty: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_calibration_traces(
    records_by_trace: Mapping[Path, Sequence[MeasurementTraceRecord]],
) -> Dict[str, Any]:
    if not records_by_trace:
        raise ValueError("at least one calibration trace is required")

    records = [
        record
        for trace_records in records_by_trace.values()
        for record in trace_records
    ]
    if not records:
        raise ValueError("calibration trace is empty")

    empty_traces = [str(path) for path, trace_records in records_by_trace.items() if not trace_records]
    if empty_traces:
        raise ValueError("calibration trace(s) are empty: " + ", ".join(empty_traces))

    scenarios = {record.scenario for record in records}
    if len(scenarios) != 1:
        raise ValueError("calibration traces must share exactly one scenario")

    topology_hashes = {record.topology_hash for record in records}
    if None in topology_hashes or len(topology_hashes) != 1:
        raise ValueError("calibration traces must share exactly one topology_hash")

    for record in records:
        if not record.visible_cells:
            raise ValueError("calibration traces contain a record without visible cells")
        for cell in record.visible_cells:
            float(cell.rsrp_dbm)

    per_trace = []
    for path, trace_records in records_by_trace.items():
        trace_scenarios = {record.scenario for record in trace_records}
        trace_seeds = {record.seed for record in trace_records}
        trace_topologies = {record.topology_hash for record in trace_records}
        if len(trace_scenarios) != 1:
            raise ValueError(f"calibration trace must contain one scenario: {path}")
        if len(trace_seeds) != 1:
            raise ValueError(f"calibration trace must contain one seed: {path}")
        if len(trace_topologies) != 1:
            raise ValueError(f"calibration trace must contain one topology_hash: {path}")
        per_trace.append(
            {
                "trace": str(path),
                "scenario": next(iter(trace_scenarios)),
                "seed": next(iter(trace_seeds)),
                "topology_hash": next(iter(trace_topologies)),
                "record_count": len(trace_records),
                "trace_sha256": sha256_file(path),
            }
        )

    seeds = [int(item["seed"]) for item in per_trace]
    if len(set(seeds)) != len(seeds):
        raise ValueError("calibration traces must use distinct seeds")

    return {
        "scenario": next(iter(scenarios)),
        "seeds": sorted(seeds),
        "topology_hash": next(iter(topology_hashes)),
        "record_count": len(records),
        "trace_count": len(records_by_trace),
        "traces": per_trace,
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
    calibration_traces: Sequence[Path],
    records: Sequence[MeasurementTraceRecord],
    calibration: Mapping[str, Any],
) -> Dict[str, Any]:
    ensure_baseline_service_importable()
    from handover_baseline import A3ParameterGrid, FixedA3Policy  # type: ignore[import-not-found]

    records_by_seed: Dict[int, list[MeasurementTraceRecord]] = {}
    for record in records:
        records_by_seed.setdefault(record.seed, []).append(record)
    evaluated = []
    for parameters in A3ParameterGrid().iter_parameters():
        summaries = []
        for seed_records in records_by_seed.values():
            adapter = TunedA3PolicyAdapter(
                FixedA3Policy(parameters, name="tuned_a3_baseline")
            )
            replay = OfflineReplayRunner([adapter]).replay(seed_records)
            summaries.append(replay.policy_results["tuned_a3_baseline"].summary)
        evaluated.append(
            {
                "parameters": parameters.to_dict(),
                "score": sum(summary.composite_cost for summary in summaries) / len(summaries),
                "handover_count": sum(summary.handover_count for summary in summaries),
                "ping_pong_count": sum(summary.ping_pong_count for summary in summaries),
                "low_quality_steps": sum(summary.low_quality_step_count for summary in summaries),
                "low_sinr_steps": sum(summary.low_sinr_step_count for summary in summaries),
                "qos_violation_proxy_count": sum(
                    summary.qos_violation_proxy_count for summary in summaries
                ),
                "composite_cost_version": "v3_physical_qos_cost",
            }
        )
    selected = min(
        evaluated,
        key=lambda item: (
            item["score"],
            item["ping_pong_count"],
            item["handover_count"],
        ),
    )
    first_trace = calibration["traces"][0]

    return {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": "calibration_trace_grid_search",
        "selected_parameters": selected["parameters"],
        "selected_score": selected["score"],
        "objective": "minimize mean v3_physical_qos_cost across calibration seeds",
        "calibration": {
            "trace": first_trace["trace"],
            "scenario": calibration["scenario"],
            "seed": first_trace["seed"],
            "topology_hash": calibration["topology_hash"],
            "record_count": first_trace["record_count"],
            "trace_sha256": first_trace["trace_sha256"],
        },
        "calibrations": list(calibration["traces"]),
        "calibration_traces": [str(path) for path in calibration_traces],
        "calibration_seeds": calibration["seeds"],
        "trace_hashes": {
            str(item["trace"]): item["trace_sha256"]
            for item in calibration["traces"]
        },
        "record_count": calibration["record_count"],
        "calibration_trace_count": calibration["trace_count"],
        "topology_hash": calibration["topology_hash"],
        "evaluated_configuration_scores": evaluated,
        "evaluated_configurations": evaluated,
        "uses_ml_outputs": False,
        "metric_version": "v3_physical_qos_cost",
    }


def calibrate_tuned_a3_config(
    calibration_trace: Path | Sequence[Path],
    output: Path,
) -> Path:
    ensure_fresh_output_file(output)
    trace_paths = (
        [calibration_trace]
        if isinstance(calibration_trace, Path)
        else list(calibration_trace)
    )
    if not trace_paths:
        raise ValueError("at least one calibration trace is required")
    records_by_trace = {path: read_trace_jsonl(path) for path in trace_paths}
    calibration = validate_calibration_traces(records_by_trace)
    records = [
        record
        for trace_records in records_by_trace.values()
        for record in trace_records
    ]
    config = build_tuned_a3_config(
        calibration_traces=trace_paths,
        records=records,
        calibration=calibration,
    )
    output.write_text(json.dumps(config, indent=2, sort_keys=True), encoding="utf-8")
    return output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Tune non-ML A3 parameters on calibration trace(s) and write a "
            "reusable tuned_a3_config.json artifact."
        )
    )
    parser.add_argument(
        "--calibration-trace",
        action="append",
        required=True,
        help="Calibration trace JSONL. May be supplied multiple times.",
    )
    parser.add_argument("--output", required=True, help="Fresh tuned A3 config JSON path.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        output = calibrate_tuned_a3_config(
            calibration_trace=[Path(path) for path in args.calibration_trace],
            output=Path(args.output),
        )
    except Exception as exc:  # noqa: BLE001 - command should fail visibly
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Tuned A3 config written to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
