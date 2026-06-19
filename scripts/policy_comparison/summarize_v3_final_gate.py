#!/usr/bin/env python3
"""Apply the preregistered v3 final gate without changing model or metric choices."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

import numpy as np

from .output_validation import validate_comparison_output
from .v3_protocol import load_protocol, require_capture_allowed


REQUIRED_POLICIES = {
    "tuned_a3_baseline",
    "ml_policy",
    "complexity_aware_ml_a3",
    "no_handover_baseline",
}


def _bootstrap_ci(values: Sequence[float], iterations: int) -> tuple[float, float]:
    data = np.asarray(values, dtype=float)
    rng = np.random.default_rng(20260619)
    samples = rng.choice(data, size=(iterations, len(data)), replace=True).mean(axis=1)
    return float(np.quantile(samples, 0.025)), float(np.quantile(samples, 0.975))


def summarize(run_dirs: Sequence[Path], protocol_path: Path) -> dict:
    protocol = load_protocol(protocol_path)
    for seed in protocol["final_seeds"]:
        require_capture_allowed(int(seed), protocol)
    runs: dict[tuple[str, int], dict] = {}
    for root in run_dirs:
        validation = validate_comparison_output(root, expected_policies=sorted(REQUIRED_POLICIES))
        if not validation.ok:
            raise ValueError(f"run failed output validation: {root}")
        data = json.loads((root / "summary.json").read_text(encoding="utf-8"))
        summaries = {
            name: payload["summary"] for name, payload in data["policy_results"].items()
        }
        if not REQUIRED_POLICIES.issubset(summaries):
            raise ValueError(f"run missing required policies: {root}")
        if any(
            summary.get("composite_cost_version") != "v3_physical_qos_cost"
            for summary in summaries.values()
        ):
            raise ValueError("final gate accepts only v3 metric outputs")
        runs[(str(data["scenario"]), int(data["seed"]))] = summaries

    expected = {
        (scenario, int(seed))
        for scenario in protocol["scenarios"]
        for seed in protocol["final_seeds"]
    }
    if set(runs) != expected:
        raise ValueError(f"final run matrix mismatch: missing={sorted(expected - set(runs))}")

    dense_improvements: list[float] = []
    dense_differences: list[float] = []
    sparse_differences: list[float] = []
    positive_seeds = 0
    safety_ok = True
    overall = {"adaptive": [], "tuned": [], "ml": [], "stay": []}
    for seed in protocol["final_seeds"]:
        dense = runs[("highway_dense_v2", int(seed))]
        sparse = runs[("highway_sparse_v2", int(seed))]
        adaptive_high = float(dense["complexity_aware_ml_a3"]["complexity_high_composite_cost"])
        tuned_high = float(dense["tuned_a3_baseline"]["complexity_high_composite_cost"])
        improvement = (tuned_high - adaptive_high) / tuned_high if tuned_high > 0 else 0.0
        dense_improvements.append(improvement)
        dense_differences.append(tuned_high - adaptive_high)
        positive_seeds += int(improvement > 0.0)
        sparse_adaptive = float(sparse["complexity_aware_ml_a3"]["composite_cost"])
        sparse_tuned = float(sparse["tuned_a3_baseline"]["composite_cost"])
        sparse_differences.append(sparse_tuned - sparse_adaptive)
        if sparse_adaptive > sparse_tuned * 1.02:
            safety_ok = False
        for scenario in protocol["scenarios"]:
            summaries = runs[(scenario, int(seed))]
            adaptive = summaries["complexity_aware_ml_a3"]
            tuned = summaries["tuned_a3_baseline"]
            for metric in ("ping_pong_count", "rlf_proxy_count", "qos_violation_proxy_count"):
                if float(adaptive[metric]) > float(tuned[metric]):
                    safety_ok = False
            overall["adaptive"].append(float(adaptive["composite_cost"]))
            overall["tuned"].append(float(tuned["composite_cost"]))
            overall["ml"].append(float(summaries["ml_policy"]["composite_cost"]))
            overall["stay"].append(float(summaries["no_handover_baseline"]["composite_cost"]))

    iterations = int(protocol["acceptance"]["bootstrap_iterations"])
    improvement_ci = _bootstrap_ci(dense_improvements, iterations)
    interaction = [dense - sparse for dense, sparse in zip(dense_differences, sparse_differences)]
    interaction_ci = _bootstrap_ci(interaction, iterations)
    mean_improvement = float(np.mean(dense_improvements))
    overall_pass = all(
        float(np.mean(overall["adaptive"])) < float(np.mean(overall[reference]))
        for reference in ("tuned", "ml", "stay")
    )
    passed = (
        mean_improvement
        >= float(protocol["acceptance"]["minimum_high_complexity_improvement_fraction"])
        and improvement_ci[0] > 0.0
        and positive_seeds
        >= int(protocol["acceptance"]["minimum_positive_final_seeds"])
        and interaction_ci[0] > 0.0
        and overall_pass
        and safety_ok
    )
    return {
        "pass": passed,
        "mean_high_complexity_improvement_fraction": mean_improvement,
        "high_complexity_improvement_95ci": improvement_ci,
        "positive_final_seed_count": positive_seeds,
        "policy_by_complexity_interaction_95ci": interaction_ci,
        "overall_policy_means": {key: float(np.mean(value)) for key, value in overall.items()},
        "overall_pass": overall_pass,
        "safety_and_sparse_noninferiority_pass": safety_ok,
        "protocol": str(protocol_path),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument("--run-dir", action="append", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = summarize(args.run_dir, args.protocol)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
