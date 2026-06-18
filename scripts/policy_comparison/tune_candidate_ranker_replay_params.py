#!/usr/bin/env python3
"""Tune candidate-ranker decision parameters by calibration replay."""

from __future__ import annotations

import argparse
import json
import math
import sys
from itertools import product
from pathlib import Path
from typing import Any, Sequence

import joblib

if __package__ in {None, ""}:  # pragma: no cover - direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.policy_comparison.candidate_ranker_artifact import (
    load_candidate_ranker_artifact,
    sha256_file,
)
from scripts.policy_comparison.policy_adapters import (
    CandidateRankerPolicyAdapter,
    ComplexityAwarePolicyAdapter,
    TunedA3PolicyAdapter,
)
from scripts.policy_comparison.replay import OfflineReplayRunner
from scripts.policy_comparison.trace_io import read_trace_jsonl


def tune_candidate_ranker_replay_params(args: argparse.Namespace) -> dict[str, Any]:
    calibration_trace = Path(args.calibration_trace)
    tuned_a3_config = Path(args.tuned_a3_config)
    artifact_path = Path(args.ranker_artifact)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    records = read_trace_jsonl(calibration_trace)
    artifact = load_candidate_ranker_artifact(artifact_path)
    margins = _parse_float_list(args.margin_thresholds)
    dwell_values = _parse_float_list(args.ml_dwell_s)
    segment_hold_values = _parse_float_list(args.ml_segment_hold_s)
    a3_guards = _parse_float_list(args.a3_reentry_extra_margin_db)
    thresholds = _parse_int_list(args.complexity_thresholds)

    evaluations = []
    for threshold, margin, dwell, segment_hold, a3_guard in product(
        thresholds,
        margins,
        dwell_values,
        segment_hold_values,
        a3_guards,
    ):
        tuned = TunedA3PolicyAdapter.from_tuned_config(tuned_a3_config)
        ranker = CandidateRankerPolicyAdapter(
            artifact,
            min_margin=margin,
            min_ml_dwell_s=dwell,
        )
        adaptive = ComplexityAwarePolicyAdapter(
            sparse_policy=TunedA3PolicyAdapter.from_tuned_config(tuned_a3_config),
            ml_policy=ranker,
            high_complexity_threshold=threshold,
            a3_reentry_extra_margin_db=a3_guard,
            ml_segment_hold_s=segment_hold,
        )
        result = OfflineReplayRunner([tuned, ranker, adaptive]).replay(records)
        tuned_summary = result.policy_results["tuned_a3_baseline"].summary.to_dict()
        ranker_summary = result.policy_results["ml_policy"].summary.to_dict()
        adaptive_summary = result.policy_results["complexity_aware_ml_a3"].summary.to_dict()
        evaluation = _evaluate_candidate(
            threshold=threshold,
            margin=margin,
            dwell=dwell,
            segment_hold=segment_hold,
            a3_guard=a3_guard,
            tuned=tuned_summary,
            ranker=ranker_summary,
            adaptive=adaptive_summary,
            max_unnecessary_increase_fraction=args.max_unnecessary_increase_fraction,
        )
        evaluations.append(evaluation)

    passing = [item for item in evaluations if item["pass"]]
    selected = None
    if passing:
        selected = min(
            passing,
            key=lambda item: (
                item["adaptive_high_cost"],
                item["adaptive_composite_cost"],
                item["adaptive_ping_pong_count"],
                item["adaptive_handover_count"],
                item["complexity_threshold"],
                item["ml_segment_hold_s"],
                item["ranker_min_margin"],
            ),
        )

    report = {
        "pass": selected is not None,
        "selected": selected,
        "calibration_trace": str(calibration_trace),
        "ranker_artifact": str(artifact_path),
        "tuned_a3_config": str(tuned_a3_config),
        "evaluated_count": len(evaluations),
        "evaluations": sorted(
            evaluations,
            key=lambda item: (
                not item["pass"],
                item["adaptive_high_cost"],
                item["adaptive_composite_cost"],
                item["complexity_threshold"],
                item["ml_segment_hold_s"],
                item["ranker_min_margin"],
            ),
        ),
    }
    (output_dir / "ranker_replay_tuning.json").write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (output_dir / "ranker_replay_tuning.md").write_text(
        _markdown(report),
        encoding="utf-8",
    )
    if selected and args.output_artifact:
        _write_tuned_artifact(
            source_artifact=artifact_path,
            output_artifact=Path(args.output_artifact),
            selected=selected,
            report_path=output_dir / "ranker_replay_tuning.json",
        )
        report["output_artifact"] = str(args.output_artifact)
    return report


def _evaluate_candidate(
    *,
    threshold: int,
    margin: float,
    dwell: float,
    segment_hold: float,
    a3_guard: float,
    tuned: dict[str, Any],
    ranker: dict[str, Any],
    adaptive: dict[str, Any],
    max_unnecessary_increase_fraction: float,
) -> dict[str, Any]:
    tuned_high = float(tuned.get("complexity_high_composite_cost", 0.0))
    adaptive_high = float(adaptive.get("complexity_high_composite_cost", 0.0))
    tuned_unnecessary = int(tuned.get("unnecessary_handover_count", 0))
    adaptive_unnecessary = int(adaptive.get("unnecessary_handover_count", 0))
    allowed_unnecessary = math.ceil(
        tuned_unnecessary * (1.0 + max_unnecessary_increase_fraction)
    )
    fail_reasons = []
    if tuned_high <= 0.0:
        fail_reasons.append("calibration has no tuned-A3 high-complexity cost")
    elif adaptive_high >= tuned_high:
        fail_reasons.append("adaptive high-complexity cost did not beat tuned A3")
    if int(adaptive.get("ping_pong_count", 0)) > int(tuned.get("ping_pong_count", 0)):
        fail_reasons.append("adaptive ping-pong exceeded tuned A3")
    if adaptive_unnecessary > allowed_unnecessary:
        fail_reasons.append("adaptive unnecessary handovers exceeded allowed bound")
    return {
        "complexity_threshold": int(threshold),
        "ranker_min_margin": float(margin),
        "min_ml_dwell_s": float(dwell),
        "ml_segment_hold_s": float(segment_hold),
        "a3_reentry_extra_margin_db": float(a3_guard),
        "pass": not fail_reasons,
        "fail_reasons": fail_reasons,
        "tuned_high_cost": tuned_high,
        "adaptive_high_cost": adaptive_high,
        "high_improvement": (
            (tuned_high - adaptive_high) / tuned_high
            if tuned_high > 0.0
            else 0.0
        ),
        "tuned_composite_cost": float(tuned.get("composite_cost", 0.0)),
        "ranker_composite_cost": float(ranker.get("composite_cost", 0.0)),
        "adaptive_composite_cost": float(adaptive.get("composite_cost", 0.0)),
        "tuned_ping_pong_count": int(tuned.get("ping_pong_count", 0)),
        "adaptive_ping_pong_count": int(adaptive.get("ping_pong_count", 0)),
        "tuned_unnecessary_handover_count": tuned_unnecessary,
        "adaptive_unnecessary_handover_count": adaptive_unnecessary,
        "adaptive_handover_count": int(adaptive.get("handover_count", 0)),
    }


def _write_tuned_artifact(
    *,
    source_artifact: Path,
    output_artifact: Path,
    selected: dict[str, Any],
    report_path: Path,
) -> None:
    payload = joblib.load(source_artifact)
    if not isinstance(payload, dict):
        raise ValueError("ranker artifact payload must be a dict")
    metadata = dict(payload.get("metadata") or {})
    metadata["ranker_decision_parameters"] = {
        "selection_source": "calibration_replay",
        "selected_min_margin": selected["ranker_min_margin"],
        "min_ml_dwell_s": selected["min_ml_dwell_s"],
        "ml_segment_hold_s": selected["ml_segment_hold_s"],
        "a3_reentry_extra_margin_db": selected["a3_reentry_extra_margin_db"],
        "selected_complexity_threshold": selected["complexity_threshold"],
        "calibration_replay_tuning_report": str(report_path),
        "calibration_high_improvement": selected["high_improvement"],
    }
    payload["metadata"] = metadata
    output_artifact.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(payload, output_artifact)
    metadata["model_sha256"] = sha256_file(output_artifact)
    Path(f"{output_artifact}.meta.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _parse_float_list(raw: str) -> list[float]:
    values = [float(item.strip()) for item in raw.split(",") if item.strip()]
    if not values:
        raise ValueError("float list must not be empty")
    return values


def _parse_int_list(raw: str) -> list[int]:
    values = [int(item.strip()) for item in raw.split(",") if item.strip()]
    if not values:
        raise ValueError("integer list must not be empty")
    return values


def _markdown(report: dict[str, Any]) -> str:
    selected = report.get("selected")
    lines = [
        "# Candidate Ranker Replay Tuning",
        "",
        f"Pass: `{str(report['pass']).lower()}`",
        f"Selected: `{json.dumps(selected, sort_keys=True) if selected else None}`",
        "",
        "| Threshold | Margin | Dwell | Segment Hold | A3 Guard | Pass | High Improvement | Adaptive High Cost | Reasons |",
        "|---:|---:|---:|---:|---:|---|---:|---:|---|",
    ]
    for item in report["evaluations"][:100]:
        lines.append(
            f"| {item['complexity_threshold']} | {item['ranker_min_margin']:.3f} | "
            f"{item['min_ml_dwell_s']:.3f} | {item['ml_segment_hold_s']:.3f} | "
            f"{item['a3_reentry_extra_margin_db']:.3f} | "
            f"{str(item['pass']).lower()} | {item['high_improvement']:.4f} | "
            f"{item['adaptive_high_cost']:.3f} | {'; '.join(item['fail_reasons'])} |"
        )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument("--calibration-trace", required=True)
    parser.add_argument("--tuned-a3-config", required=True)
    parser.add_argument("--ranker-artifact", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--output-artifact")
    parser.add_argument("--complexity-thresholds", default="3,4")
    parser.add_argument("--margin-thresholds", default="5,8,12,16,20,25,30")
    parser.add_argument("--ml-dwell-s", default="0,10,20")
    parser.add_argument("--ml-segment-hold-s", default="0,10,20,30")
    parser.add_argument("--a3-reentry-extra-margin-db", default="0,3,6")
    parser.add_argument("--max-unnecessary-increase-fraction", type=float, default=0.05)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        report = tune_candidate_ranker_replay_params(args)
    except Exception as exc:  # noqa: BLE001 - command should fail visibly
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
