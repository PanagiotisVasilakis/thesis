#!/usr/bin/env python3
"""Tune segment-controller decision parameters using calibration replay."""

from __future__ import annotations

import argparse
import itertools
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import joblib

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.policy_comparison.output_validation import (  # noqa: E402
    validate_comparison_output,
)
from scripts.policy_comparison.run_offline_replay import run as run_offline_replay  # noqa: E402
from scripts.policy_comparison.segment_controller_artifact import (  # noqa: E402
    sha256_file,
)


def parse_float_list(raw: str) -> list[float]:
    return [float(item.strip()) for item in raw.split(",") if item.strip()]


def parse_int_list(raw: str) -> list[int]:
    return [int(item.strip()) for item in raw.split(",") if item.strip()]


def normalize_entry_threshold_offset(value: float) -> float:
    """Interpret large entry-threshold offsets as percentage points.

    The segment entry model is a classifier, so its threshold is a probability
    in [0, 1]. The written experiment grid uses `-5,0,+5,+10`; treating those
    as percentage points preserves that plan while keeping the replay threshold
    meaningful for classifier scores.
    """
    return value / 100.0 if abs(value) > 1.0 else value


def ensure_fresh_dir(path: Path) -> None:
    if path.exists() and any(path.iterdir()):
        raise ValueError(f"output directory already exists and is not empty: {path}")
    path.mkdir(parents=True, exist_ok=True)


def tune_segment_controller_replay_params(args: argparse.Namespace) -> dict[str, Any]:
    traces = [Path(path) for path in args.calibration_trace]
    tuned_a3_config = Path(args.tuned_a3_config)
    segment_artifact = Path(args.segment_artifact)
    output_dir = Path(args.output_dir)
    ensure_fresh_dir(output_dir)

    configs = list(_iter_configs(args))
    if not configs:
        raise ValueError("parameter sweep produced no configurations")

    if args.staged:
        results, passing, stage_report = _run_staged_tuning(
            args=args,
            configs=configs,
            traces=traces,
            tuned_a3_config=tuned_a3_config,
            segment_artifact=segment_artifact,
            output_dir=output_dir,
        )
    else:
        results, passing = _run_configs(
            args=args,
            indexed_configs=list(enumerate(configs, start=1)),
            traces=traces,
            tuned_a3_config=tuned_a3_config,
            segment_artifact=segment_artifact,
            output_dir=output_dir,
            stage_name="config",
        )
        stage_report = {"mode": "exhaustive"}

    selected = _select_best(passing)
    summary = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "segment_artifact": str(segment_artifact),
        "segment_artifact_sha256": sha256_file(segment_artifact),
        "tuned_a3_config": str(tuned_a3_config),
        "calibration_traces": [str(path) for path in traces],
        "config_count": len(configs),
        "pass": selected is not None,
        "selected": selected,
        "stage_report": stage_report,
        "results": results,
    }
    (output_dir / "segment_replay_tuning.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (output_dir / "segment_replay_tuning.md").write_text(
        _render_markdown(summary),
        encoding="utf-8",
    )
    if selected is not None and args.output_artifact:
        tuned_artifact = Path(args.output_artifact)
        _write_tuned_artifact(
            source=segment_artifact,
            destination=tuned_artifact,
            selected=selected,
            tuning_summary=summary,
        )
        summary["tuned_artifact"] = str(tuned_artifact)
        (output_dir / "segment_replay_tuning.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    if selected is None and args.fail_if_no_pass:
        raise ValueError("no segment replay tuning configuration passed calibration gate")
    return summary


def _iter_configs(args: argparse.Namespace):
    base_entry = float(args.base_entry_threshold)
    for (
        threshold,
        entry_offset,
        margin,
        exit_threshold,
        exit_votes,
        min_duration,
        max_duration,
        post_exit_guard,
        post_exit_extra_margin,
        high_reject_hold,
    ) in itertools.product(
        parse_int_list(args.complexity_thresholds),
        parse_float_list(args.entry_threshold_offsets),
        parse_float_list(args.candidate_margin_mins),
        parse_float_list(args.exit_thresholds),
        parse_int_list(args.consecutive_exit_votes),
        parse_float_list(args.min_segment_durations),
        parse_float_list(args.max_segment_durations),
        parse_float_list(args.post_exit_a3_guard_s),
        parse_float_list(args.post_exit_a3_extra_margin_db),
        parse_float_list(args.high_reject_hold_s),
    ):
        normalized_entry_offset = normalize_entry_threshold_offset(float(entry_offset))
        if max_duration < min_duration:
            continue
        yield {
            "high_complexity_threshold": int(threshold),
            "entry_threshold": max(0.0, min(1.0, base_entry + normalized_entry_offset)),
            "entry_threshold_offset": float(normalized_entry_offset),
            "entry_threshold_offset_raw": float(entry_offset),
            "candidate_margin_min": float(margin),
            "exit_threshold": float(exit_threshold),
            "consecutive_exit_votes": int(exit_votes),
            "min_segment_duration_s": float(min_duration),
            "max_segment_duration_s": float(max_duration),
            "emergency_rsrp_floor_dbm": float(args.emergency_rsrp_floor_dbm),
            "post_exit_a3_guard_s": float(post_exit_guard),
            "post_exit_a3_extra_margin_db": float(post_exit_extra_margin),
            "high_reject_hold_s": float(high_reject_hold),
        }


def _run_staged_tuning(
    *,
    args: argparse.Namespace,
    configs: Sequence[Mapping[str, Any]],
    traces: Sequence[Path],
    tuned_a3_config: Path,
    segment_artifact: Path,
    output_dir: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    stage_a_trace = _select_stage_a_trace(traces, args.stage_a_seed)
    indexed = list(enumerate(configs, start=1))
    sampled = _stratified_sample(indexed, max_count=args.stage_a_max_configs)
    stage_a_results, _stage_a_passing = _run_configs(
        args=args,
        indexed_configs=sampled,
        traces=[stage_a_trace],
        tuned_a3_config=tuned_a3_config,
        segment_artifact=segment_artifact,
        output_dir=output_dir / "stage_a_seed52",
        stage_name="config",
    )
    ranked = sorted(stage_a_results, key=_stage_a_sort_key)
    selected_stage_b = [
        (int(item["config_index"]), item["config"])
        for item in ranked[: max(1, int(args.stage_b_top_configs))]
    ]
    stage_b_results, passing = _run_configs(
        args=args,
        indexed_configs=selected_stage_b,
        traces=traces,
        tuned_a3_config=tuned_a3_config,
        segment_artifact=segment_artifact,
        output_dir=output_dir / "stage_b_all_calibration",
        stage_name="config",
    )
    return stage_b_results, passing, {
        "mode": "staged",
        "total_grid_config_count": len(configs),
        "stage_a_trace": str(stage_a_trace),
        "stage_a_config_count": len(sampled),
        "stage_b_config_count": len(selected_stage_b),
        "stage_a_results": stage_a_results,
    }


def _run_configs(
    *,
    args: argparse.Namespace,
    indexed_configs: Sequence[tuple[int, Mapping[str, Any]]],
    traces: Sequence[Path],
    tuned_a3_config: Path,
    segment_artifact: Path,
    output_dir: Path,
    stage_name: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    passing: list[dict[str, Any]] = []
    for config_index, config in indexed_configs:
        config_dir = output_dir / f"{stage_name}_{config_index:04d}"
        config_dir.mkdir(parents=True, exist_ok=True)
        seed_results = []
        config_failed = False
        for trace in traces:
            seed = _trace_seed_hint(trace)
            replay_dir = config_dir / f"calibration_{seed or trace.stem}"
            replay_args = argparse.Namespace(
                trace=str(trace),
                output_dir=str(replay_dir),
                policies="tuned_a3_baseline,complexity_aware_ml_a3,ml",
                calibration_trace=None,
                tuned_a3_config=str(tuned_a3_config),
                allow_tuned_a3_calibration_seed_overlap=True,
                ml_base_url=None,
                ml_backend="segment_controller",
                ranker_artifact=None,
                segment_artifact=str(segment_artifact),
                high_complexity_threshold=config["high_complexity_threshold"],
                ranker_min_margin=None,
                ranker_min_ml_dwell_s=None,
                a3_reentry_extra_margin_db=None,
                ml_segment_hold_s=None,
                segment_entry_threshold=config["entry_threshold"],
                segment_candidate_margin_min=config["candidate_margin_min"],
                segment_exit_threshold=config["exit_threshold"],
                segment_consecutive_exit_votes=config["consecutive_exit_votes"],
                segment_min_duration_s=config["min_segment_duration_s"],
                segment_max_duration_s=config["max_segment_duration_s"],
                segment_emergency_rsrp_floor_dbm=config["emergency_rsrp_floor_dbm"],
                segment_post_exit_a3_guard_s=config["post_exit_a3_guard_s"],
                segment_post_exit_a3_extra_margin_db=config["post_exit_a3_extra_margin_db"],
                segment_high_reject_hold_s=config["high_reject_hold_s"],
            )
            try:
                run_offline_replay(replay_args)
                validation = validate_comparison_output(
                    replay_dir,
                    expected_policies=[
                        "tuned_a3_baseline",
                        "complexity_aware_ml_a3",
                        "ml_policy",
                    ],
                )
                summary = json.loads((replay_dir / "summary.json").read_text(encoding="utf-8"))
                seed_result = _summarize_seed(summary, validation.ok)
            except Exception as exc:  # noqa: BLE001 - preserve diagnostic detail
                seed_result = {
                    "trace": str(trace),
                    "ok": False,
                    "error": str(exc),
                }
            seed_results.append(seed_result)
            if not seed_result.get("ok"):
                config_failed = True
                if args.stop_seed_on_failure:
                    break
        evaluation = _evaluate_config(config, seed_results)
        entry = {
            "config_index": config_index,
            "config": dict(config),
            "seed_results": seed_results,
            "evaluation": evaluation,
            "pass": (not config_failed and evaluation["pass"]),
        }
        results.append(entry)
        if entry["pass"]:
            passing.append(entry)
    return results, passing


def _select_stage_a_trace(traces: Sequence[Path], seed: int) -> Path:
    needle = f"seed{seed}"
    for trace in traces:
        if any(needle in part for part in trace.parts):
            return trace
    raise ValueError(f"stage A calibration trace for seed {seed} not found")


def _stratified_sample(
    indexed_configs: Sequence[tuple[int, Mapping[str, Any]]],
    *,
    max_count: int,
) -> list[tuple[int, Mapping[str, Any]]]:
    if max_count <= 0 or len(indexed_configs) <= max_count:
        return list(indexed_configs)
    stride = max(1, len(indexed_configs) // max_count)
    sampled = list(indexed_configs[::stride][:max_count])
    if indexed_configs[-1] not in sampled:
        sampled[-1] = indexed_configs[-1]
    return sampled


def _stage_a_sort_key(entry: Mapping[str, Any]) -> tuple[float, float, float, int]:
    evaluation = entry.get("evaluation")
    if not isinstance(evaluation, Mapping):
        return (float("inf"), float("inf"), float("inf"), int(entry.get("config_index", 0)))
    high_improvement = float(evaluation.get("mean_high_improvement_fraction", 0.0))
    ping_pong = float(evaluation.get("mean_adaptive_ping_pong", float("inf")))
    overall = float(evaluation.get("mean_adaptive_overall_cost", float("inf")))
    handovers = float(evaluation.get("mean_adaptive_handovers", float("inf")))
    return (
        0.0 if high_improvement >= 0.05 else 1.0,
        ping_pong,
        overall + handovers * 0.1,
        int(entry.get("config_index", 0)),
    )


def _summarize_seed(summary: Mapping[str, Any], validation_ok: bool) -> dict[str, Any]:
    policies = summary.get("policy_results", {})
    if not isinstance(policies, Mapping):
        raise ValueError("summary missing policy_results")
    tuned = _policy_summary(policies, "tuned_a3_baseline")
    adaptive = _policy_summary(policies, "complexity_aware_ml_a3")
    ml = _policy_summary(policies, "ml_policy")
    high_tuned = float(tuned.get("complexity_high_composite_cost", 0.0))
    high_adaptive = float(adaptive.get("complexity_high_composite_cost", 0.0))
    overall_tuned = float(tuned.get("composite_cost", 0.0))
    overall_adaptive = float(adaptive.get("composite_cost", 0.0))
    return {
        "ok": bool(validation_ok),
        "scenario": summary.get("scenario"),
        "seed": summary.get("seed"),
        "validation_ok": bool(validation_ok),
        "tuned_high_cost": high_tuned,
        "adaptive_high_cost": high_adaptive,
        "high_improvement_fraction": (
            (high_tuned - high_adaptive) / high_tuned if high_tuned > 0 else 0.0
        ),
        "tuned_overall_cost": overall_tuned,
        "adaptive_overall_cost": overall_adaptive,
        "ml_overall_cost": float(ml.get("composite_cost", 0.0)),
        "tuned_ping_pong": int(tuned.get("ping_pong_count", 0)),
        "adaptive_ping_pong": int(adaptive.get("ping_pong_count", 0)),
        "tuned_unnecessary": int(tuned.get("unnecessary_handover_count", 0)),
        "adaptive_unnecessary": int(adaptive.get("unnecessary_handover_count", 0)),
        "adaptive_failed": int(adaptive.get("failed_handover_proxy_count", 0)),
        "adaptive_handovers": int(adaptive.get("handover_count", 0)),
        "adaptive_guard_suppressions": int(
            adaptive.get("post_segment_a3_guard_suppression_count", 0)
        ),
        "adaptive_high_reject_holds": int(adaptive.get("high_reject_hold_count", 0)),
        "adaptive_sparse_moderate_churn_after_ml": int(
            adaptive.get("sparse_moderate_churn_after_ml_count", 0)
        ),
        "adaptive_post_segment_a3": int(
            adaptive.get("post_segment_a3_handover_count", 0)
        ),
    }


def _policy_summary(policies: Mapping[str, Any], policy: str) -> Mapping[str, Any]:
    payload = policies.get(policy)
    if not isinstance(payload, Mapping):
        raise ValueError(f"summary missing policy {policy}")
    summary = payload.get("summary")
    if not isinstance(summary, Mapping):
        raise ValueError(f"summary missing metrics for policy {policy}")
    return summary


def _evaluate_config(config: Mapping[str, Any], seed_results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    valid = [item for item in seed_results if item.get("ok")]
    if len(valid) != len(seed_results) or not valid:
        return {"pass": False, "reason": "validation_or_replay_failure"}
    improvements = [float(item["high_improvement_fraction"]) for item in valid]
    mean_improvement = sum(improvements) / len(improvements)
    constraints = {
        "all_high_cost_beats_tuned": all(
            float(item["adaptive_high_cost"]) < float(item["tuned_high_cost"])
            for item in valid
        ),
        "mean_high_improvement_at_least_5pct": mean_improvement >= 0.05,
        "ping_pong_not_above_tuned": all(
            int(item["adaptive_ping_pong"]) <= int(item["tuned_ping_pong"])
            for item in valid
        ),
        "unnecessary_bounded": all(
            int(item["adaptive_unnecessary"])
            <= int(item["tuned_unnecessary"]) * 1.05 + 1
            for item in valid
        ),
        "no_failed_handover_proxies": all(
            int(item["adaptive_failed"]) == 0 for item in valid
        ),
    }
    passed = all(constraints.values())
    return {
        "pass": passed,
        "constraints": constraints,
        "mean_high_improvement_fraction": mean_improvement,
        "mean_adaptive_high_cost": sum(float(item["adaptive_high_cost"]) for item in valid) / len(valid),
        "mean_tuned_high_cost": sum(float(item["tuned_high_cost"]) for item in valid) / len(valid),
        "mean_adaptive_overall_cost": sum(float(item["adaptive_overall_cost"]) for item in valid) / len(valid),
        "mean_adaptive_ping_pong": sum(int(item["adaptive_ping_pong"]) for item in valid) / len(valid),
        "mean_adaptive_handovers": sum(int(item["adaptive_handovers"]) for item in valid) / len(valid),
    }


def _select_best(entries: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    if not entries:
        return None
    return min(
        entries,
        key=lambda entry: (
            float(entry["evaluation"]["mean_adaptive_high_cost"]),
            float(entry["evaluation"]["mean_adaptive_ping_pong"]),
            float(entry["evaluation"]["mean_adaptive_handovers"]),
            float(entry["config"]["max_segment_duration_s"]),
            int(entry["config"]["high_complexity_threshold"]),
        ),
    )


def _write_tuned_artifact(
    *,
    source: Path,
    destination: Path,
    selected: Mapping[str, Any],
    tuning_summary: Mapping[str, Any],
) -> None:
    if destination.exists():
        raise ValueError(f"tuned segment artifact already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = joblib.load(source)
    if not isinstance(payload, Mapping):
        raise ValueError("segment artifact payload must be a mapping")
    metadata = dict(payload.get("metadata") or {})
    metadata["segment_decision_parameters"] = dict(selected["config"])
    metadata["segment_replay_tuning_result"] = {
        "selected_config_index": selected["config_index"],
        "selected_evaluation": selected["evaluation"],
        "tuned_at": tuning_summary["created_at"],
    }
    payload = dict(payload)
    payload["metadata"] = metadata
    joblib.dump(payload, destination)
    metadata["model_sha256"] = sha256_file(destination)
    Path(f"{destination}.meta.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _render_markdown(summary: Mapping[str, Any]) -> str:
    lines = [
        "# Segment Replay Tuning",
        "",
        f"- Pass: `{str(summary.get('pass')).lower()}`",
        f"- Configurations evaluated: `{summary.get('config_count')}`",
        f"- Segment artifact: `{summary.get('segment_artifact')}`",
        "",
    ]
    selected = summary.get("selected")
    if isinstance(selected, Mapping):
        lines.extend(
            [
                "## Selected",
                "",
                f"- Config index: `{selected.get('config_index')}`",
                f"- Mean high-complexity improvement: `{selected['evaluation'].get('mean_high_improvement_fraction'):.4f}`",
                f"- Mean adaptive high cost: `{selected['evaluation'].get('mean_adaptive_high_cost'):.4f}`",
                f"- Parameters: `{json.dumps(selected.get('config'), sort_keys=True)}`",
                "",
            ]
        )
    else:
        lines.extend(["## Selected", "", "No configuration passed the calibration gate.", ""])
    return "\n".join(lines)


def _trace_seed_hint(path: Path) -> str:
    for part in reversed(path.parts):
        if "seed" in part:
            return part
    return path.stem


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument(
        "--calibration-trace",
        action="append",
        required=True,
        help="Calibration trace JSONL. May be supplied multiple times.",
    )
    parser.add_argument("--tuned-a3-config", required=True)
    parser.add_argument("--segment-artifact", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--output-artifact")
    parser.add_argument("--complexity-thresholds", default="3,4")
    parser.add_argument("--base-entry-threshold", type=float, default=0.5)
    parser.add_argument(
        "--entry-threshold-offsets",
        default="-10,-5,0,5",
        help=(
            "Entry threshold offsets. Values with absolute magnitude >1 are "
            "interpreted as percentage points, so the default means "
            "-0.10,-0.05,0,+0.05 around the base threshold."
        ),
    )
    parser.add_argument("--candidate-margin-mins", default="5,10,15,20,30")
    parser.add_argument("--exit-thresholds", default="0.6,0.7,0.8")
    parser.add_argument("--consecutive-exit-votes", default="2,3,4")
    parser.add_argument("--min-segment-durations", default="6,10,15")
    parser.add_argument("--max-segment-durations", default="30,45,60")
    parser.add_argument("--emergency-rsrp-floor-dbm", type=float, default=-112.0)
    parser.add_argument("--post-exit-a3-guard-s", default="0,10,20,30")
    parser.add_argument("--post-exit-a3-extra-margin-db", default="0,3,6,9")
    parser.add_argument("--high-reject-hold-s", default="0,6,12,20")
    parser.add_argument("--staged", action="store_true")
    parser.add_argument("--stage-a-seed", type=int, default=52)
    parser.add_argument("--stage-a-max-configs", type=int, default=48)
    parser.add_argument("--stage-b-top-configs", type=int, default=20)
    parser.add_argument("--stop-seed-on-failure", action="store_true")
    parser.add_argument("--fail-if-no-pass", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        summary = tune_segment_controller_replay_params(args)
    except Exception as exc:  # noqa: BLE001 - command should fail visibly
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
