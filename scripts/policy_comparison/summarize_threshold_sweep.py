#!/usr/bin/env python3
"""Summarize held-out complexity-threshold replay sweeps with strict gates."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

if __package__ in {None, ""}:  # pragma: no cover - direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.policy_comparison.output_validation import (  # noqa: E402
    validate_comparison_output,
)


DEFAULT_EXPECTED_POLICIES = (
    "fixed_a3_baseline",
    "tuned_a3_baseline",
    "strongest_rsrp_baseline",
    "strongest_sinr_baseline",
    "strongest_rsrq_baseline",
    "load_aware_a3_baseline",
    "velocity_adaptive_a3_baseline",
    "ml_policy",
    "complexity_aware_ml_a3",
)


@dataclass(frozen=True)
class LoadedRun:
    threshold: int
    path: Path
    summary: Mapping[str, Any]
    validation_ok: bool
    validation_issues: list[dict[str, Any]]


def parse_csv_ints(raw: str) -> list[int]:
    return [int(item.strip()) for item in raw.split(",") if item.strip()]


def parse_csv_strings(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def discover_runs(sweep_root: Path) -> list[tuple[int, Path]]:
    if not sweep_root.is_dir():
        raise ValueError(f"sweep root does not exist: {sweep_root}")
    discovered: list[tuple[int, Path]] = []
    for threshold_dir in sorted(sweep_root.iterdir()):
        if not threshold_dir.is_dir():
            continue
        match = re.fullmatch(r"threshold[_-](\d+)", threshold_dir.name)
        if not match:
            continue
        threshold = int(match.group(1))
        for summary_path in sorted(threshold_dir.rglob("summary.json")):
            discovered.append((threshold, summary_path.parent))
    if not discovered:
        raise ValueError(f"no threshold replay summaries found under {sweep_root}")
    return discovered


def summarize_threshold_sweep(args: argparse.Namespace) -> dict[str, Any]:
    sweep_root = Path(args.sweep_root)
    output_dir = Path(args.output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"output directory already exists and is not empty: {output_dir}")
    expected_policies = parse_csv_strings(args.expected_policies)
    required_seeds = set(parse_csv_ints(args.required_seeds))
    loaded_runs = [
        load_run(threshold, path, expected_policies=expected_policies)
        for threshold, path in discover_runs(sweep_root)
    ]
    by_threshold: dict[int, list[LoadedRun]] = {}
    for run in loaded_runs:
        by_threshold.setdefault(run.threshold, []).append(run)

    threshold_summaries = [
        evaluate_threshold(
            threshold,
            runs,
            required_seeds=required_seeds,
            min_high_improvement=args.min_high_improvement,
        )
        for threshold, runs in sorted(by_threshold.items())
    ]
    passing = [item for item in threshold_summaries if item["pass"]]
    selected = None
    if passing:
        selected = min(
            passing,
            key=lambda item: (
                item["mean_complexity_high_composite_cost"],
                item["mean_ping_pong_count"],
                item["mean_handover_count"],
                item["threshold"],
            ),
        )

    report = {
        "pass": bool(selected),
        "selected_threshold": None if selected is None else selected["threshold"],
        "selection_rule": (
            "lowest mean high-complexity composite cost; tie-break lower "
            "ping-pong count, lower handover count, lower threshold"
        ),
        "required_seeds": sorted(required_seeds),
        "expected_policies": expected_policies,
        "thresholds": threshold_summaries,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "threshold_sweep_summary.json"
    markdown_path = output_dir / "threshold_sweep_summary.md"
    json_path.write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return report


def load_run(
    threshold: int,
    path: Path,
    *,
    expected_policies: Sequence[str],
) -> LoadedRun:
    report = validate_comparison_output(path, expected_policies=expected_policies)
    summary = json.loads((path / "summary.json").read_text(encoding="utf-8"))
    return LoadedRun(
        threshold=threshold,
        path=path,
        summary=summary,
        validation_ok=report.ok,
        validation_issues=[issue.to_dict() for issue in report.issues],
    )


def evaluate_threshold(
    threshold: int,
    runs: Sequence[LoadedRun],
    *,
    required_seeds: set[int],
    min_high_improvement: float,
) -> dict[str, Any]:
    reasons: list[str] = []
    seeds = {int(run.summary.get("seed", -1)) for run in runs}
    missing_seeds = sorted(required_seeds.difference(seeds))
    if missing_seeds:
        reasons.append("missing required seed(s): " + ", ".join(map(str, missing_seeds)))
    validation_failures = [
        str(run.path) for run in runs if not run.validation_ok
    ]
    if validation_failures:
        reasons.append("validation failed for " + ", ".join(validation_failures))

    per_seed: list[dict[str, Any]] = []
    high_improvements: list[float] = []
    comp_costs: list[float] = []
    ml_costs: list[float] = []
    tuned_costs: list[float] = []
    comp_high_costs: list[float] = []
    ping_pongs: list[float] = []
    handovers: list[float] = []

    for run in sorted(runs, key=lambda item: int(item.summary.get("seed", 0))):
        seed = int(run.summary.get("seed", -1))
        metrics = _policy_metrics(run.summary)
        comp = metrics.get("complexity_aware_ml_a3")
        tuned = metrics.get("tuned_a3_baseline")
        ml = metrics.get("ml_policy")
        if comp is None or tuned is None or ml is None:
            reasons.append(f"seed {seed} missing required policy metrics")
            continue
        comp_high = _high_cost(comp)
        tuned_high = _high_cost(tuned)
        comp_high_count = _high_count(comp)
        tuned_high_count = _high_count(tuned)
        if comp_high_count <= 0 or tuned_high_count <= 0:
            high_improvement = 0.0
            reasons.append(f"seed {seed} has no high-complexity observations")
        elif tuned_high <= 0:
            high_improvement = 0.0
            reasons.append(f"seed {seed} tuned A3 high-complexity cost is not positive")
        else:
            high_improvement = (tuned_high - comp_high) / tuned_high
        if (comp_high_count > 0 and tuned_high_count > 0) and not comp_high < tuned_high:
            reasons.append(f"seed {seed} high-complexity cost did not beat tuned A3")
        if comp.get("ping_pong_count", 0.0) > tuned.get("ping_pong_count", 0.0):
            reasons.append(f"seed {seed} ping-pong count increased over tuned A3")
        if comp.get("qos_violation_proxy_count", 0.0) > tuned.get("qos_violation_proxy_count", 0.0):
            reasons.append(f"seed {seed} QoS violation proxy count increased over tuned A3")

        comp_cost = float(comp.get("composite_cost", 0.0))
        ml_cost = float(ml.get("composite_cost", 0.0))
        tuned_cost = float(tuned.get("composite_cost", 0.0))
        per_seed.append(
            {
                "seed": seed,
                "complexity_high_cost": comp_high,
                "complexity_high_count": comp_high_count,
                "tuned_high_cost": tuned_high,
                "tuned_high_count": tuned_high_count,
                "high_improvement": high_improvement,
                "complexity_composite_cost": comp_cost,
                "ml_composite_cost": ml_cost,
                "tuned_composite_cost": tuned_cost,
                "complexity_ping_pong_count": float(comp.get("ping_pong_count", 0.0)),
                "tuned_ping_pong_count": float(tuned.get("ping_pong_count", 0.0)),
            }
        )
        high_improvements.append(high_improvement)
        comp_costs.append(comp_cost)
        ml_costs.append(ml_cost)
        tuned_costs.append(tuned_cost)
        comp_high_costs.append(comp_high)
        ping_pongs.append(float(comp.get("ping_pong_count", 0.0)))
        handovers.append(float(comp.get("handover_count", 0.0)))

    mean_high_improvement = _mean(high_improvements)
    mean_comp_cost = _mean(comp_costs)
    mean_ml_cost = _mean(ml_costs)
    mean_tuned_cost = _mean(tuned_costs)
    if mean_high_improvement < min_high_improvement:
        reasons.append(
            f"mean high-complexity improvement {mean_high_improvement:.4f} "
            f"< required {min_high_improvement:.4f}"
        )
    if not mean_comp_cost < mean_ml_cost:
        reasons.append("complexity-aware ranker did not beat ranker-everywhere overall")
    if not mean_comp_cost < mean_tuned_cost:
        reasons.append("complexity-aware ranker did not beat tuned-A3-everywhere overall")

    return {
        "threshold": threshold,
        "pass": not reasons,
        "fail_reasons": reasons,
        "seed_count": len(seeds),
        "seeds": sorted(seeds),
        "mean_high_improvement": mean_high_improvement,
        "mean_complexity_high_composite_cost": _mean(comp_high_costs),
        "mean_complexity_composite_cost": mean_comp_cost,
        "mean_ml_composite_cost": mean_ml_cost,
        "mean_tuned_a3_composite_cost": mean_tuned_cost,
        "mean_ping_pong_count": _mean(ping_pongs),
        "mean_handover_count": _mean(handovers),
        "per_seed": per_seed,
        "validation_issues": [
            {
                "path": str(run.path),
                "issues": run.validation_issues,
            }
            for run in runs
            if run.validation_issues
        ],
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Threshold Sweep Summary",
        "",
        f"Pass: `{str(report['pass']).lower()}`",
        f"Selected threshold: `{report.get('selected_threshold')}`",
        "",
        "| Threshold | Pass | Mean high improvement | Mean high cost | Mean total cost | Reasons |",
        "|---:|---|---:|---:|---:|---|",
    ]
    for item in report["thresholds"]:
        reasons = "; ".join(item["fail_reasons"]) if item["fail_reasons"] else "n/a"
        lines.append(
            f"| {item['threshold']} | {str(item['pass']).lower()} | "
            f"{item['mean_high_improvement']:.4f} | "
            f"{item['mean_complexity_high_composite_cost']:.3f} | "
            f"{item['mean_complexity_composite_cost']:.3f} | {reasons} |"
        )
    return "\n".join(lines) + "\n"


def _policy_metrics(summary: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    raw = summary.get("policy_results")
    if not isinstance(raw, Mapping):
        raise ValueError("summary missing policy_results")
    metrics = {}
    for policy, payload in raw.items():
        if isinstance(payload, Mapping) and isinstance(payload.get("summary"), Mapping):
            metrics[str(policy)] = payload["summary"]  # type: ignore[assignment]
    return metrics


def _high_cost(metrics: Mapping[str, Any]) -> float:
    if "complexity_high_composite_cost" in metrics:
        return float(metrics["complexity_high_composite_cost"])
    bucket_costs = metrics.get("complexity_bucket_costs")
    if isinstance(bucket_costs, Mapping):
        return float(bucket_costs.get("high", 0.0))
    return 0.0


def _high_count(metrics: Mapping[str, Any]) -> float:
    bucket_counts = metrics.get("complexity_bucket_counts")
    if isinstance(bucket_counts, Mapping):
        return float(bucket_counts.get("high", 0.0))
    return 0.0


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument("--sweep-root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--required-seeds", default="42,43,44")
    parser.add_argument(
        "--expected-policies",
        default=",".join(DEFAULT_EXPECTED_POLICIES),
    )
    parser.add_argument("--min-high-improvement", type=float, default=0.05)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        report = summarize_threshold_sweep(args)
    except Exception as exc:  # noqa: BLE001 - command should fail visibly
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
