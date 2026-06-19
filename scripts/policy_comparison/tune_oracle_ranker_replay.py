#!/usr/bin/env python3
"""Tune explicit-stay ranker margin and complexity threshold on tuning traces."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from statistics import mean
from typing import Sequence

from .oracle_ranker_artifact import load_oracle_ranker_artifact, sha256_file
from .policy_adapters import (
    ComplexityAwarePolicyAdapter,
    NoHandoverPolicyAdapter,
    OracleRankerPolicyAdapter,
    TunedA3PolicyAdapter,
)
from .replay import OfflineReplayRunner
from .trace_io import read_trace_jsonl
from .validate_physical_trace import validate_trace


DEFAULT_MARGINS = (0.0, 0.25, 0.5, 1.0, 2.0, 5.0)
DEFAULT_THRESHOLDS = (3, 4)


def tune(
    traces: Sequence[Path],
    *,
    tuned_a3_config: Path,
    artifact_path: Path,
    output_artifact: Path,
    report_path: Path,
    margins: Sequence[float] = DEFAULT_MARGINS,
    thresholds: Sequence[int] = DEFAULT_THRESHOLDS,
) -> dict:
    source_artifact = load_oracle_ranker_artifact(artifact_path)
    results: list[dict] = []
    for margin in margins:
        for threshold in thresholds:
            seed_results: list[dict] = []
            for trace in traces:
                validation = validate_trace(trace, require_complexity=True)
                if not validation["pass"]:
                    raise ValueError(f"tuning trace failed physical validation: {validation}")
                records = read_trace_jsonl(trace)
                tuned = TunedA3PolicyAdapter.from_tuned_config(tuned_a3_config)
                adaptive = ComplexityAwarePolicyAdapter(
                    sparse_policy=TunedA3PolicyAdapter.from_tuned_config(tuned_a3_config),
                    ml_policy=OracleRankerPolicyAdapter(
                        source_artifact, min_utility_margin=margin
                    ),
                    high_complexity_threshold=threshold,
                )
                replay = OfflineReplayRunner(
                    [
                        tuned,
                        OracleRankerPolicyAdapter(
                            source_artifact, min_utility_margin=margin
                        ),
                        adaptive,
                        NoHandoverPolicyAdapter(),
                    ]
                ).replay(records)
                summaries = {
                    name: result.summary.to_dict()
                    for name, result in replay.policy_results.items()
                }
                tuned_summary = summaries["tuned_a3_baseline"]
                ml_summary = summaries["ml_policy"]
                adaptive_summary = summaries["complexity_aware_ml_a3"]
                stay_summary = summaries["no_handover_baseline"]
                high_tuned = float(tuned_summary["complexity_high_composite_cost"])
                high_adaptive = float(adaptive_summary["complexity_high_composite_cost"])
                improvement = (
                    (high_tuned - high_adaptive) / high_tuned if high_tuned > 0 else 0.0
                )
                passes = (
                    high_adaptive < high_tuned
                    and float(adaptive_summary["composite_cost"])
                    < float(ml_summary["composite_cost"])
                    and float(adaptive_summary["composite_cost"])
                    < float(tuned_summary["composite_cost"])
                    and float(adaptive_summary["composite_cost"])
                    < float(stay_summary["composite_cost"])
                    and int(adaptive_summary["ping_pong_count"])
                    <= int(tuned_summary["ping_pong_count"])
                    and int(adaptive_summary["rlf_proxy_count"])
                    <= int(tuned_summary["rlf_proxy_count"])
                    and int(adaptive_summary["qos_violation_proxy_count"])
                    <= int(tuned_summary["qos_violation_proxy_count"])
                )
                seed_results.append(
                    {
                        "seed": records[0].seed,
                        "pass": passes,
                        "high_complexity_improvement_fraction": improvement,
                        "adaptive": adaptive_summary,
                        "ml": ml_summary,
                        "tuned_a3": tuned_summary,
                        "no_handover": stay_summary,
                    }
                )
            mean_improvement = mean(
                item["high_complexity_improvement_fraction"] for item in seed_results
            )
            config_pass = all(item["pass"] for item in seed_results) and mean_improvement >= 0.05
            results.append(
                {
                    "margin": margin,
                    "high_complexity_threshold": threshold,
                    "pass": config_pass,
                    "mean_high_complexity_improvement_fraction": mean_improvement,
                    "seed_results": seed_results,
                }
            )
    passing = [item for item in results if item["pass"]]
    selected = (
        min(
            passing,
            key=lambda item: (
                mean(seed["adaptive"]["composite_cost"] for seed in item["seed_results"]),
                item["margin"],
                item["high_complexity_threshold"],
            ),
        )
        if passing
        else None
    )
    report = {
        "pass": selected is not None,
        "selected": selected,
        "results": results,
        "tuning_traces": [str(path) for path in traces],
        "source_artifact": str(artifact_path),
        "tuned_a3_config": str(tuned_a3_config),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    if selected is not None:
        if output_artifact.exists() or Path(f"{output_artifact}.meta.json").exists():
            raise ValueError("tuned output artifact already exists")
        output_artifact.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(artifact_path, output_artifact)
        metadata = dict(source_artifact.metadata)
        metadata["selected_min_utility_margin"] = selected["margin"]
        metadata["selected_high_complexity_threshold"] = selected[
            "high_complexity_threshold"
        ]
        metadata["replay_tuning_result"] = {
            "report": str(report_path),
            "mean_high_complexity_improvement_fraction": selected[
                "mean_high_complexity_improvement_fraction"
            ],
        }
        metadata["model_sha256"] = sha256_file(output_artifact)
        Path(f"{output_artifact}.meta.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8"
        )
        protocol_lock = {
            "protocol_version": "physical_handover_v3",
            "metric_version": "v3_physical_qos_cost",
            "final_seeds": list(range(201, 211)),
            "model_selection_frozen": True,
            "final_results_unlocked": True,
            "selected_model_artifact_sha256": metadata["model_sha256"],
            "selected_high_complexity_threshold": selected[
                "high_complexity_threshold"
            ],
            "selected_min_utility_margin": selected["margin"],
            "source_tuning_report": str(report_path),
        }
        report_path.with_name("protocol_lock.json").write_text(
            json.dumps(protocol_lock, indent=2, sort_keys=True), encoding="utf-8"
        )
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument("--trace", action="append", type=Path, required=True)
    parser.add_argument("--tuned-a3-config", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--output-artifact", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = tune(
            args.trace,
            tuned_a3_config=args.tuned_a3_config,
            artifact_path=args.artifact,
            output_artifact=args.output_artifact,
            report_path=args.report,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
