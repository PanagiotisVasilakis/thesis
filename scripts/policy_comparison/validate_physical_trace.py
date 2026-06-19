#!/usr/bin/env python3
"""Fail-closed physical and provenance validation for thesis trace schema v3."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Sequence

from .complexity import candidate_complexity_for_record
from .trace_io import read_trace_jsonl


EXPECTED_CELL_COUNTS = {
    "highway_sparse_v2": 8,
    "highway_moderate_v2": 16,
    "highway_dense_v2": 24,
}


def _quantile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((len(ordered) - 1) * fraction)))
    return ordered[index]


def validate_trace(path: Path, *, require_complexity: bool = False) -> dict:
    records = read_trace_jsonl(path)
    if not records:
        raise ValueError("trace is empty")
    errors: list[str] = []
    scenario = records[0].scenario
    expected_cells = EXPECTED_CELL_COUNTS.get(scenario)
    rsrp_values: list[float] = []
    sinr_values: list[float] = []
    velocities_by_ue: dict[
        str, list[tuple[int, float, float, float, float, float, bool]]
    ] = defaultdict(list)
    complexity = Counter()

    for record in records:
        if record.trace_schema_version != 3:
            errors.append("trace_schema_version_not_v3")
        provenance = record.metadata.get("rf_provenance") or {}
        if provenance.get("fallback") is not False:
            errors.append("rf_fallback_active")
        if provenance.get("strict_mode") is not True:
            errors.append("rf_strict_mode_missing")
        if provenance.get("path_loss_model") != "3gpp_tr_38_901_rma":
            errors.append("unexpected_path_loss_model")
        topology_ids = set(record.topology_cell_ids)
        if expected_cells is not None and len(topology_ids) != expected_cells:
            errors.append("topology_cell_count_mismatch")
        measurement_ids = {cell.cell_id for cell in record.visible_cells}
        if measurement_ids != topology_ids:
            errors.append("incomplete_counterfactual_cell_measurements")
        if provenance.get("all_topology_cells_exposed") is not True:
            errors.append("counterfactual_measurement_provenance_missing")
        if not record.qos_requirements or not record.service_type:
            errors.append("missing_qos_requirements")
        qos_provenance = record.metadata.get("qos_provenance") or {}
        if qos_provenance.get("simulated") is not True:
            errors.append("missing_simulated_qos_provenance")
        movement_provenance = record.metadata.get("movement_provenance") or {}
        if (
            movement_provenance.get("model")
            != "distance_over_elapsed_time_ping_pong_v1"
            or movement_provenance.get("coordinate_frame") != "local_cartesian_m"
        ):
            errors.append("missing_movement_provenance")
        configured_provenance_speed = movement_provenance.get(
            "configured_speed_mps"
        )
        if (
            record.speed_mps is not None
            and isinstance(configured_provenance_speed, (int, float))
            and not math.isclose(
                float(record.speed_mps),
                float(configured_provenance_speed),
                rel_tol=1e-6,
            )
        ):
            errors.append("movement_provenance_speed_mismatch")

        rsrp_values.extend(cell.rsrp_dbm for cell in record.visible_cells)
        sinr_values.extend(
            cell.sinr_db for cell in record.visible_cells if cell.sinr_db is not None
        )
        feature_velocity = (record.metadata.get("ml_features") or {}).get("velocity")
        if isinstance(feature_velocity, (int, float)) and record.speed_mps is not None:
            heading_change_rate = (record.metadata.get("ml_features") or {}).get(
                "heading_change_rate", 0.0
            )
            velocities_by_ue[record.ue_id].append(
                (
                    record.step_index,
                    float(record.speed_mps),
                    float(feature_velocity),
                    float(heading_change_rate or 0.0),
                    float(record.ue_position["latitude"]),
                    float(record.ue_position["longitude"]),
                    bool(movement_provenance.get("endpoint_reversal", False)),
                )
            )
        bucket = candidate_complexity_for_record(record).complexity_bucket
        complexity[bucket] += 1

        rounded = Counter(
            (round(cell.rsrp_dbm, 6), round(cell.sinr_db or -999.0, 6))
            for cell in record.visible_cells
        )
        if any(count >= 4 for count in rounded.values()):
            errors.append("duplicate_omnidirectional_sector_measurements")

    if not rsrp_values or not sinr_values:
        errors.append("missing_rf_measurements")
    else:
        median_rsrp = statistics.median(rsrp_values)
        if max(rsrp_values) > -30.0 or not -135.0 <= median_rsrp <= -55.0:
            errors.append("implausible_rsrp_distribution")
        if not -35.0 <= statistics.median(sinr_values) <= 30.0:
            errors.append("implausible_sinr_distribution")

    for samples in velocities_by_ue.values():
        samples.sort(key=lambda item: item[0])
        for index, (
            step,
            configured,
            measured,
            _heading_rate,
            _position_x,
            _position_y,
            _endpoint_reversal,
        ) in enumerate(samples):
            if step < 2 or configured <= 0.0:
                continue
            relative_error = abs(measured - configured) / configured
            nearby_heading_rates = [
                samples[neighbor][3]
                for neighbor in range(max(0, index - 1), min(len(samples), index + 2))
            ]
            position_reversal = False
            if 0 < index < len(samples) - 1:
                previous = samples[index - 1]
                current = samples[index]
                following = samples[index + 1]
                incoming = (current[4] - previous[4], current[5] - previous[5])
                outgoing = (following[4] - current[4], following[5] - current[5])
                position_reversal = (
                    incoming[0] * outgoing[0] + incoming[1] * outgoing[1]
                ) < 0.0
            endpoint_reversal = (
                max(nearby_heading_rates, default=0.0) >= 1.0
                or position_reversal
                or any(
                    samples[neighbor][6]
                    for neighbor in range(
                        max(0, index - 1), min(len(samples), index + 2)
                    )
                )
            )
            if relative_error > 0.05 and not endpoint_reversal:
                errors.append("trajectory_velocity_mismatch")
                break

    if require_complexity and complexity["high"] < max(500, int(0.15 * len(records))):
        errors.append("insufficient_high_complexity_coverage")

    report = {
        "path": str(path),
        "scenario": scenario,
        "record_count": len(records),
        "expected_cell_count": expected_cells,
        "complexity_bucket_counts": dict(complexity),
        "rsrp_dbm": {
            "p05": _quantile(rsrp_values, 0.05) if rsrp_values else None,
            "median": statistics.median(rsrp_values) if rsrp_values else None,
            "p95": _quantile(rsrp_values, 0.95) if rsrp_values else None,
        },
        "sinr_db": {
            "p05": _quantile(sinr_values, 0.05) if sinr_values else None,
            "median": statistics.median(sinr_values) if sinr_values else None,
            "p95": _quantile(sinr_values, 0.95) if sinr_values else None,
        },
        "errors": sorted(set(errors)),
    }
    report["pass"] = not report["errors"]
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument("trace", type=Path)
    parser.add_argument("--require-complexity", action="store_true")
    args = parser.parse_args(argv)
    report = validate_trace(args.trace, require_complexity=args.require_complexity)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
