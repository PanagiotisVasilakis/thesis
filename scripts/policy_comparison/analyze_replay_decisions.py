#!/usr/bin/env python3
"""Analyze replay decision logs after a threshold sweep or failed replay."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any, Sequence

if __package__ in {None, ""}:  # pragma: no cover - direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.policy_comparison.schemas import PolicyDecisionRecord
from scripts.policy_comparison.trace_io import read_decisions_jsonl


def analyze_replay_decisions(args: argparse.Namespace) -> dict[str, Any]:
    replay_dir = Path(args.replay_dir)
    decisions_dir = replay_dir / "decisions"
    if not decisions_dir.is_dir():
        raise ValueError(f"replay decisions directory is missing: {decisions_dir}")
    policies = _resolve_policies(decisions_dir, args.policy)
    output_dir = Path(args.output_dir) if args.output_dir else replay_dir / "decision_diagnostics"

    policy_reports = {}
    for policy in policies:
        path = decisions_dir / f"{policy}.jsonl"
        decisions = read_decisions_jsonl(path)
        policy_reports[policy] = _analyze_policy(policy, decisions)

    report = {
        "replay_dir": str(replay_dir),
        "policies": policies,
        "policy_reports": policy_reports,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "decision_diagnostics.json").write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (output_dir / "decision_diagnostics.md").write_text(
        _markdown(report),
        encoding="utf-8",
    )
    return report


def _resolve_policies(decisions_dir: Path, raw: str | None) -> list[str]:
    if raw:
        policies = [item.strip() for item in raw.split(",") if item.strip()]
    else:
        policies = sorted(path.stem for path in decisions_dir.glob("*.jsonl"))
    if not policies:
        raise ValueError("no decision policies selected")
    missing = [policy for policy in policies if not (decisions_dir / f"{policy}.jsonl").is_file()]
    if missing:
        raise ValueError("missing decision log(s): " + ", ".join(missing))
    return policies


def _analyze_policy(policy: str, decisions: Sequence[PolicyDecisionRecord]) -> dict[str, Any]:
    handovers_by_bucket: Counter[str] = Counter()
    handovers_by_source: Counter[str] = Counter()
    records_by_bucket: Counter[str] = Counter()
    records_by_source: Counter[str] = Counter()
    handovers_per_ue: Counter[str] = Counter()
    source_transitions: Counter[str] = Counter()
    target_pairs: Counter[str] = Counter()
    unnecessary_by_bucket: Counter[str] = Counter()
    sparse_after_recent_ml = 0
    ranker_scores: list[float] = []
    selected_scores: list[float] = []
    margins: list[float] = []
    dwell_samples: list[float] = []
    last_handover_by_ue: dict[str, PolicyDecisionRecord] = {}
    last_source_by_ue: dict[str, str] = {}
    dwell_start_by_ue: dict[str, float] = {}

    for decision in sorted(decisions, key=lambda item: (item.timestamp_s, item.step_index, item.ue_id)):
        bucket = _bucket(decision)
        source = _source(decision)
        records_by_bucket[bucket] += 1
        records_by_source[source] += 1
        dwell_start_by_ue.setdefault(decision.ue_id, decision.timestamp_s)
        scores = decision.debug.get("ranker_candidate_scores")
        if isinstance(scores, dict):
            ranker_scores.extend(
                float(value)
                for value in scores.values()
                if isinstance(value, (int, float)) and math.isfinite(float(value))
            )
        selected_score = decision.debug.get("ranker_selected_score")
        if isinstance(selected_score, (int, float)) and math.isfinite(float(selected_score)):
            selected_scores.append(float(selected_score))
        margin = decision.debug.get("ranker_margin_vs_stay")
        if isinstance(margin, (int, float)) and math.isfinite(float(margin)):
            margins.append(float(margin))

        if decision.decision_type != "handover" or decision.selected_target_cell is None:
            continue

        handovers_by_bucket[bucket] += 1
        handovers_by_source[source] += 1
        handovers_per_ue[decision.ue_id] += 1
        target_pairs[f"{decision.current_serving_cell}->{decision.selected_target_cell}"] += 1
        dwell_samples.append(max(0.0, decision.timestamp_s - dwell_start_by_ue[decision.ue_id]))
        dwell_start_by_ue[decision.ue_id] = decision.timestamp_s

        target_rsrp = decision.neighbour_measurements_considered.get(decision.selected_target_cell)
        if target_rsrp is not None and target_rsrp <= decision.serving_measurement_value:
            unnecessary_by_bucket[bucket] += 1

        previous_source = last_source_by_ue.get(decision.ue_id)
        if previous_source is not None:
            source_transitions[f"{previous_source}->{source}"] += 1
        previous = last_handover_by_ue.get(decision.ue_id)
        if (
            previous is not None
            and _source(previous) in {"ml_high_complexity", "candidate_ranker", "ml_policy"}
            and bucket == "sparse"
            and decision.timestamp_s - previous.timestamp_s <= 60.0
        ):
            sparse_after_recent_ml += 1
        last_handover_by_ue[decision.ue_id] = decision
        last_source_by_ue[decision.ue_id] = source

    return {
        "record_count": len(decisions),
        "handover_count": sum(handovers_by_bucket.values()),
        "records_by_complexity_bucket": dict(sorted(records_by_bucket.items())),
        "records_by_decision_source": dict(sorted(records_by_source.items())),
        "handovers_by_complexity_bucket": dict(sorted(handovers_by_bucket.items())),
        "handovers_by_decision_source": dict(sorted(handovers_by_source.items())),
        "handover_source_transitions": dict(source_transitions.most_common()),
        "handovers_per_ue": dict(handovers_per_ue.most_common()),
        "top_current_to_target_pairs": dict(target_pairs.most_common(20)),
        "unnecessary_handovers_by_bucket": dict(sorted(unnecessary_by_bucket.items())),
        "sparse_handovers_after_recent_ml": sparse_after_recent_ml,
        "dwell_time_s": _stats(dwell_samples),
        "ranker_score_distribution": _stats(ranker_scores),
        "ranker_selected_score_distribution": _stats(selected_scores),
        "ranker_margin_distribution": _stats(margins),
    }


def _bucket(decision: PolicyDecisionRecord) -> str:
    complexity = decision.debug.get("candidate_complexity")
    if isinstance(complexity, dict):
        bucket = complexity.get("complexity_bucket")
        if isinstance(bucket, str) and bucket:
            return bucket
    return "unknown"


def _source(decision: PolicyDecisionRecord) -> str:
    source = decision.debug.get("decision_source")
    return str(source or decision.policy_name)


def _stats(values: Sequence[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "min": None, "mean": None, "max": None}
    ordered = sorted(float(value) for value in values)
    return {
        "count": len(ordered),
        "min": ordered[0],
        "mean": mean(ordered),
        "p50": ordered[len(ordered) // 2],
        "p95": ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))],
        "max": ordered[-1],
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Replay Decision Diagnostics",
        "",
        f"Replay: `{report['replay_dir']}`",
        "",
        "| Policy | Records | Handovers | By Source | By Bucket | Sparse After ML |",
        "|---|---:|---:|---|---|---:|",
    ]
    for policy, payload in report["policy_reports"].items():
        lines.append(
            "| "
            + " | ".join(
                [
                    policy,
                    str(payload["record_count"]),
                    str(payload["handover_count"]),
                    json.dumps(payload["handovers_by_decision_source"], sort_keys=True),
                    json.dumps(payload["handovers_by_complexity_bucket"], sort_keys=True),
                    str(payload["sparse_handovers_after_recent_ml"]),
                ]
            )
            + " |"
        )
    lines.append("")
    for policy, payload in report["policy_reports"].items():
        lines.extend(
            [
                f"## {policy}",
                "",
                f"- Source transitions: `{json.dumps(payload['handover_source_transitions'], sort_keys=True)}`",
                f"- Top current->target pairs: `{json.dumps(payload['top_current_to_target_pairs'], sort_keys=True)}`",
                f"- Dwell stats: `{json.dumps(payload['dwell_time_s'], sort_keys=True)}`",
                f"- Ranker margin stats: `{json.dumps(payload['ranker_margin_distribution'], sort_keys=True)}`",
                "",
            ]
        )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument("--replay-dir", required=True, help="Offline replay output directory.")
    parser.add_argument(
        "--policy",
        help="Comma-separated policies to analyze. Defaults to every decisions/*.jsonl file.",
    )
    parser.add_argument("--output-dir", help="Output directory for JSON/Markdown diagnostics.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        report = analyze_replay_decisions(args)
    except Exception as exc:  # noqa: BLE001 - command should fail visibly
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
