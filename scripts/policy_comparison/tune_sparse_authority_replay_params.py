#!/usr/bin/env python3
"""Tune sparse/simple authority for a calibrated segment controller."""

from __future__ import annotations

import argparse
import itertools
import json
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
    SEGMENT_SPARSE_AUTHORITY_MODES,
    load_segment_controller_artifact,
    sha256_file,
)


def parse_float_list(raw: str) -> list[float]:
    return [float(item.strip()) for item in raw.split(",") if item.strip()]


def parse_int_list(raw: str) -> list[int]:
    return [int(item.strip()) for item in raw.split(",") if item.strip()]


def parse_mode_list(raw: str) -> list[str]:
    modes = [item.strip() for item in raw.split(",") if item.strip()]
    invalid = sorted(set(modes).difference(SEGMENT_SPARSE_AUTHORITY_MODES))
    if invalid:
        raise ValueError("unsupported sparse authority mode(s): " + ", ".join(invalid))
    return modes


def ensure_fresh_dir(path: Path) -> None:
    if path.exists() and any(path.iterdir()):
        raise ValueError(f"output directory already exists and is not empty: {path}")
    path.mkdir(parents=True, exist_ok=True)


def tune_sparse_authority_replay_params(args: argparse.Namespace) -> dict[str, Any]:
    traces = [Path(path) for path in args.calibration_trace]
    tuned_a3_config = Path(args.tuned_a3_config)
    segment_artifact = Path(args.segment_artifact)
    output_dir = Path(args.output_dir)
    ensure_fresh_dir(output_dir)
    load_segment_controller_artifact(segment_artifact)

    configs = list(_iter_configs(args))
    if not configs:
        raise ValueError("sparse authority sweep produced no configurations")

    indexed = list(enumerate(configs, start=1))
    if args.staged:
        stage_a_trace = _select_stage_a_trace(traces, args.stage_a_seed)
        sampled = _balanced_sample(indexed, max_count=args.stage_a_max_configs)
        stage_a_results, _ = _run_configs(
            indexed_configs=sampled,
            traces=[stage_a_trace],
            tuned_a3_config=tuned_a3_config,
            segment_artifact=segment_artifact,
            output_dir=output_dir / f"stage_a_seed{args.stage_a_seed}",
        )
        stage_b_configs = _select_stage_b(
            stage_a_results,
            max_count=args.stage_b_top_configs,
        )
        results, passing = _run_configs(
            indexed_configs=stage_b_configs,
            traces=traces,
            tuned_a3_config=tuned_a3_config,
            segment_artifact=segment_artifact,
            output_dir=output_dir / "stage_b_all_calibration",
        )
        stage_report = {
            "mode": "staged",
            "total_grid_config_count": len(configs),
            "stage_a_trace": str(stage_a_trace),
            "stage_a_config_count": len(sampled),
            "stage_b_config_count": len(stage_b_configs),
            "stage_a_results": stage_a_results,
        }
    else:
        results, passing = _run_configs(
            indexed_configs=indexed,
            traces=traces,
            tuned_a3_config=tuned_a3_config,
            segment_artifact=segment_artifact,
            output_dir=output_dir / "all_configs",
        )
        stage_report = {"mode": "exhaustive"}

    selected = _select_best(passing)
    summary: dict[str, Any] = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "segment_artifact": str(segment_artifact),
        "segment_artifact_sha256": sha256_file(segment_artifact),
        "tuned_a3_config": str(tuned_a3_config),
        "calibration_traces": [str(path) for path in traces],
        "config_count": len(configs),
        "evaluated_config_count": len(results),
        "pass": selected is not None,
        "selected": selected,
        "stage_report": stage_report,
        "results": results,
        "gate_policy": {
            "adaptive_beats_ml_only_every_calibration_seed": True,
            "adaptive_beats_tuned_a3_every_calibration_seed": True,
            "high_complexity_beats_tuned_a3_every_calibration_seed": True,
            "mean_high_complexity_improvement_min": 0.05,
        },
    }
    _write_summary(output_dir, summary)
    if selected is not None and args.output_artifact:
        destination = Path(args.output_artifact)
        _write_tuned_artifact(
            source=segment_artifact,
            destination=destination,
            selected=selected,
            tuning_summary=summary,
        )
        summary["tuned_artifact"] = str(destination)
        _write_summary(output_dir, summary)
    if selected is None and args.fail_if_no_pass:
        raise ValueError("no sparse authority configuration passed calibration gate")
    return summary


def _iter_configs(args: argparse.Namespace):
    thresholds = parse_int_list(args.complexity_thresholds)
    modes = parse_mode_list(args.sparse_authority_modes)
    rsrp_floors = parse_float_list(args.sparse_rsrp_floors)
    sinr_floors = parse_float_list(args.sparse_sinr_floors)
    margins = parse_float_list(args.sparse_extra_margins)
    if not rsrp_floors or not sinr_floors or not margins:
        raise ValueError("sparse authority grids must not be empty")
    for threshold in thresholds:
        for mode in modes:
            if mode == "tuned_a3":
                yield {
                    "high_complexity_threshold": int(threshold),
                    "sparse_authority_mode": mode,
                    "sparse_serving_rsrp_floor_dbm": float(rsrp_floors[0]),
                    "sparse_serving_sinr_floor_db": float(sinr_floors[0]),
                    "sparse_a3_extra_margin_db": float(margins[0]),
                }
                continue
            for rsrp, sinr, margin in itertools.product(
                rsrp_floors,
                sinr_floors,
                margins,
            ):
                yield {
                    "high_complexity_threshold": int(threshold),
                    "sparse_authority_mode": mode,
                    "sparse_serving_rsrp_floor_dbm": float(rsrp),
                    "sparse_serving_sinr_floor_db": float(sinr),
                    "sparse_a3_extra_margin_db": float(margin),
                }


def _run_configs(
    *,
    indexed_configs: Sequence[tuple[int, Mapping[str, Any]]],
    traces: Sequence[Path],
    tuned_a3_config: Path,
    segment_artifact: Path,
    output_dir: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    passing: list[dict[str, Any]] = []
    for config_index, config in indexed_configs:
        config_dir = output_dir / f"config_{config_index:04d}"
        config_dir.mkdir(parents=True, exist_ok=True)
        seed_results: list[dict[str, Any]] = []
        for trace in traces:
            seed = _trace_seed(trace)
            replay_dir = config_dir / f"calibration_seed{seed}"
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
                segment_entry_threshold=None,
                segment_candidate_margin_min=None,
                segment_exit_threshold=None,
                segment_consecutive_exit_votes=None,
                segment_min_duration_s=None,
                segment_max_duration_s=None,
                segment_emergency_rsrp_floor_dbm=None,
                segment_post_exit_a3_guard_s=None,
                segment_post_exit_a3_extra_margin_db=None,
                segment_high_reject_hold_s=None,
                segment_sparse_authority_mode=config["sparse_authority_mode"],
                segment_sparse_serving_rsrp_floor_dbm=config[
                    "sparse_serving_rsrp_floor_dbm"
                ],
                segment_sparse_serving_sinr_floor_db=config[
                    "sparse_serving_sinr_floor_db"
                ],
                segment_sparse_a3_extra_margin_db=config[
                    "sparse_a3_extra_margin_db"
                ],
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
                summary = json.loads(
                    (replay_dir / "summary.json").read_text(encoding="utf-8")
                )
                seed_result = _summarize_seed(summary, validation.ok)
                if not validation.ok:
                    seed_result["validation_issues"] = [
                        issue.to_dict() for issue in validation.issues
                    ]
            except Exception as exc:  # noqa: BLE001 - preserve diagnostics
                seed_result = {
                    "seed": seed,
                    "ok": False,
                    "error": str(exc),
                }
            seed_results.append(seed_result)
        evaluation = _evaluate_config(seed_results)
        entry = {
            "config_index": int(config_index),
            "config": dict(config),
            "seed_results": seed_results,
            "evaluation": evaluation,
            "pass": bool(evaluation["pass"]),
        }
        results.append(entry)
        if entry["pass"]:
            passing.append(entry)
    return results, passing


def _summarize_seed(summary: Mapping[str, Any], validation_ok: bool) -> dict[str, Any]:
    policies = summary.get("policy_results")
    if not isinstance(policies, Mapping):
        raise ValueError("summary missing policy_results")
    tuned = _policy_metrics(policies, "tuned_a3_baseline")
    adaptive = _policy_metrics(policies, "complexity_aware_ml_a3")
    ml = _policy_metrics(policies, "ml_policy")
    tuned_high = float(tuned.get("complexity_high_composite_cost", 0.0))
    adaptive_high = float(adaptive.get("complexity_high_composite_cost", 0.0))
    return {
        "ok": bool(validation_ok),
        "seed": int(summary.get("seed", -1)),
        "validation_ok": bool(validation_ok),
        "tuned_high_cost": tuned_high,
        "adaptive_high_cost": adaptive_high,
        "high_improvement_fraction": (
            (tuned_high - adaptive_high) / tuned_high if tuned_high > 0 else 0.0
        ),
        "tuned_overall_cost": float(tuned.get("composite_cost", 0.0)),
        "adaptive_overall_cost": float(adaptive.get("composite_cost", 0.0)),
        "ml_overall_cost": float(ml.get("composite_cost", 0.0)),
        "tuned_ping_pong": int(tuned.get("ping_pong_count", 0)),
        "adaptive_ping_pong": int(adaptive.get("ping_pong_count", 0)),
        "tuned_unnecessary": int(tuned.get("unnecessary_handover_count", 0)),
        "adaptive_unnecessary": int(adaptive.get("unnecessary_handover_count", 0)),
        "adaptive_failed": int(adaptive.get("failed_handover_proxy_count", 0)),
        "adaptive_qos": int(adaptive.get("qos_violation_proxy_count", 0)),
        "tuned_qos": int(tuned.get("qos_violation_proxy_count", 0)),
        "adaptive_rlf": int(adaptive.get("rlf_proxy_count", 0)),
        "tuned_rlf": int(tuned.get("rlf_proxy_count", 0)),
        "adaptive_low_sinr": int(adaptive.get("low_sinr_step_count", 0)),
        "ml_low_sinr": int(ml.get("low_sinr_step_count", 0)),
        "tuned_low_sinr": int(tuned.get("low_sinr_step_count", 0)),
        "adaptive_poor_target_sinr": int(
            adaptive.get("poor_handover_target_sinr_count", 0)
        ),
        "ml_poor_target_sinr": int(ml.get("poor_handover_target_sinr_count", 0)),
        "adaptive_latency_budget_violations": int(
            adaptive.get("latency_budget_violation_count", 0)
        ),
        "ml_latency_budget_violations": int(
            ml.get("latency_budget_violation_count", 0)
        ),
        "adaptive_handovers": int(adaptive.get("handover_count", 0)),
        "adaptive_sparse_suppressions": int(
            adaptive.get("sparse_authority_suppression_count", 0)
        ),
        "adaptive_sparse_handovers": int(
            adaptive.get("sparse_authority_handover_count", 0)
        ),
    }


def _policy_metrics(policies: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    payload = policies.get(name)
    if not isinstance(payload, Mapping) or not isinstance(payload.get("summary"), Mapping):
        raise ValueError(f"summary missing metrics for {name}")
    return payload["summary"]


def _evaluate_config(seed_results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    valid = [item for item in seed_results if item.get("ok")]
    if len(valid) != len(seed_results) or not valid:
        return {
            "pass": False,
            "reason": "validation_or_replay_failure",
            "constraints": {"all_outputs_validate": False},
        }
    improvements = [float(item["high_improvement_fraction"]) for item in valid]
    mean_improvement = sum(improvements) / len(improvements)
    mean_adaptive = _mean(valid, "adaptive_overall_cost")
    mean_ml = _mean(valid, "ml_overall_cost")
    mean_tuned = _mean(valid, "tuned_overall_cost")
    constraints = {
        "all_outputs_validate": True,
        "all_high_cost_beats_tuned": all(
            float(item["adaptive_high_cost"]) < float(item["tuned_high_cost"])
            for item in valid
        ),
        "mean_high_improvement_at_least_5pct": mean_improvement >= 0.05,
        "adaptive_beats_ml_every_seed": all(
            float(item["adaptive_overall_cost"]) < float(item["ml_overall_cost"])
            for item in valid
        ),
        "adaptive_beats_ml_mean": mean_adaptive < mean_ml,
        "adaptive_beats_tuned_every_seed": all(
            float(item["adaptive_overall_cost"]) < float(item["tuned_overall_cost"])
            for item in valid
        ),
        "ping_pong_not_above_tuned": all(
            int(item["adaptive_ping_pong"]) <= int(item["tuned_ping_pong"])
            for item in valid
        ),
        "unnecessary_bounded": all(
            int(item["adaptive_unnecessary"])
            <= int(item["tuned_unnecessary"]) * 1.05 + 1
            for item in valid
        ),
        "qos_not_above_tuned": all(
            int(item["adaptive_qos"]) <= int(item["tuned_qos"])
            for item in valid
        ),
        "rlf_not_above_tuned": all(
            int(item["adaptive_rlf"]) <= int(item["tuned_rlf"])
            for item in valid
        ),
        "sinr_not_above_ml": all(
            int(item["adaptive_low_sinr"]) <= int(item["ml_low_sinr"])
            for item in valid
        ),
        "poor_target_sinr_not_above_ml": all(
            int(item["adaptive_poor_target_sinr"])
            <= int(item["ml_poor_target_sinr"])
            for item in valid
        ),
        "latency_budget_not_above_ml": all(
            int(item["adaptive_latency_budget_violations"])
            <= int(item["ml_latency_budget_violations"])
            for item in valid
        ),
        "no_failed_handover_proxies": all(
            int(item["adaptive_failed"]) == 0 for item in valid
        ),
    }
    return {
        "pass": all(constraints.values()),
        "constraints": constraints,
        "mean_high_improvement_fraction": mean_improvement,
        "mean_adaptive_high_cost": _mean(valid, "adaptive_high_cost"),
        "mean_adaptive_overall_cost": mean_adaptive,
        "mean_ml_overall_cost": mean_ml,
        "mean_tuned_overall_cost": mean_tuned,
        "mean_adaptive_ping_pong": _mean(valid, "adaptive_ping_pong"),
        "mean_adaptive_handovers": _mean(valid, "adaptive_handovers"),
        "mean_sparse_suppressions": _mean(valid, "adaptive_sparse_suppressions"),
        "mean_sparse_handovers": _mean(valid, "adaptive_sparse_handovers"),
    }


def _mean(items: Sequence[Mapping[str, Any]], key: str) -> float:
    return sum(float(item[key]) for item in items) / len(items)


def _balanced_sample(
    indexed_configs: Sequence[tuple[int, Mapping[str, Any]]],
    *,
    max_count: int,
) -> list[tuple[int, Mapping[str, Any]]]:
    if max_count <= 0 or len(indexed_configs) <= max_count:
        return list(indexed_configs)
    groups: dict[tuple[int, str], list[tuple[int, Mapping[str, Any]]]] = {}
    for item in indexed_configs:
        config = item[1]
        key = (
            int(config["high_complexity_threshold"]),
            str(config["sparse_authority_mode"]),
        )
        groups.setdefault(key, []).append(item)
    selected: list[tuple[int, Mapping[str, Any]]] = []
    per_group = max(1, max_count // len(groups))
    for key in sorted(groups):
        group = groups[key]
        stride = max(1, len(group) // per_group)
        chosen = list(group[::stride][:per_group])
        if group[-1] not in chosen and chosen:
            chosen[-1] = group[-1]
        selected.extend(chosen)
    selected_ids = {item[0] for item in selected}
    for item in indexed_configs:
        if len(selected) >= max_count:
            break
        if item[0] not in selected_ids:
            selected.append(item)
            selected_ids.add(item[0])
    return selected[:max_count]


def _select_stage_b(
    stage_a_results: Sequence[Mapping[str, Any]],
    *,
    max_count: int,
) -> list[tuple[int, Mapping[str, Any]]]:
    ranked = sorted(stage_a_results, key=_stage_a_sort_key)
    selected: list[Mapping[str, Any]] = []
    seen_groups: set[tuple[int, str]] = set()
    for entry in ranked:
        config = entry["config"]
        key = (
            int(config["high_complexity_threshold"]),
            str(config["sparse_authority_mode"]),
        )
        if key not in seen_groups:
            selected.append(entry)
            seen_groups.add(key)
    for entry in ranked:
        if len(selected) >= max_count:
            break
        if entry not in selected:
            selected.append(entry)
    return [
        (int(entry["config_index"]), dict(entry["config"]))
        for entry in selected[:max_count]
    ]


def _stage_a_sort_key(entry: Mapping[str, Any]) -> tuple[float, float, float, int]:
    evaluation = entry.get("evaluation")
    if not isinstance(evaluation, Mapping) or "mean_adaptive_overall_cost" not in evaluation:
        return (float("inf"), float("inf"), float("inf"), int(entry["config_index"]))
    ml_gap = float(evaluation["mean_adaptive_overall_cost"]) - float(
        evaluation["mean_ml_overall_cost"]
    )
    high_improvement = float(evaluation["mean_high_improvement_fraction"])
    return (
        ml_gap,
        0.0 if high_improvement >= 0.05 else 1.0,
        float(evaluation["mean_adaptive_overall_cost"]),
        int(entry["config_index"]),
    )


def _select_best(entries: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    if not entries:
        return None
    return min(
        entries,
        key=lambda entry: (
            float(entry["evaluation"]["mean_adaptive_overall_cost"]),
            float(entry["evaluation"]["mean_adaptive_high_cost"]),
            float(entry["evaluation"]["mean_adaptive_ping_pong"]),
            float(entry["evaluation"]["mean_adaptive_handovers"]),
            int(entry["config"]["high_complexity_threshold"]),
        ),
    )


def _select_stage_a_trace(traces: Sequence[Path], seed: int) -> Path:
    needle = f"seed{seed}"
    for trace in traces:
        if any(needle in part for part in trace.parts):
            return trace
    raise ValueError(f"stage A calibration trace for seed {seed} not found")


def _trace_seed(path: Path) -> int:
    for part in reversed(path.parts):
        if "seed" in part:
            suffix = part.rsplit("seed", 1)[-1]
            digits = "".join(char for char in suffix if char.isdigit())
            if digits:
                return int(digits)
    raise ValueError(f"could not infer seed from trace path: {path}")


def _write_tuned_artifact(
    *,
    source: Path,
    destination: Path,
    selected: Mapping[str, Any],
    tuning_summary: Mapping[str, Any],
) -> None:
    if destination.exists():
        raise ValueError(f"sparse-authority tuned artifact already exists: {destination}")
    payload = joblib.load(source)
    if not isinstance(payload, Mapping):
        raise ValueError("segment artifact payload must be a mapping")
    metadata = dict(payload.get("metadata") or {})
    existing = metadata.get("segment_decision_parameters")
    decision_parameters = dict(existing) if isinstance(existing, Mapping) else {}
    decision_parameters.update(dict(selected["config"]))
    metadata["segment_decision_parameters"] = decision_parameters
    metadata["sparse_authority_replay_tuning_result"] = {
        "selected_config_index": int(selected["config_index"]),
        "selected_evaluation": selected["evaluation"],
        "tuned_at": tuning_summary["created_at"],
        "calibration_traces": tuning_summary["calibration_traces"],
    }
    updated = dict(payload)
    updated["metadata"] = metadata
    destination.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(updated, destination)
    metadata["model_sha256"] = sha256_file(destination)
    Path(f"{destination}.meta.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _write_summary(output_dir: Path, summary: Mapping[str, Any]) -> None:
    (output_dir / "sparse_authority_tuning.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (output_dir / "sparse_authority_tuning.md").write_text(
        _render_markdown(summary),
        encoding="utf-8",
    )


def _render_markdown(summary: Mapping[str, Any]) -> str:
    lines = [
        "# Sparse Authority Replay Tuning",
        "",
        f"- Pass: `{str(summary.get('pass')).lower()}`",
        f"- Full grid size: `{summary.get('config_count')}`",
        f"- Stage B evaluated: `{summary.get('evaluated_config_count')}`",
        f"- Segment artifact: `{summary.get('segment_artifact')}`",
        "",
        "Calibration requires adaptive to beat ML-only and tuned A3 on every seed.",
        "",
    ]
    selected = summary.get("selected")
    if not isinstance(selected, Mapping):
        lines.extend(["## Selected", "", "No configuration passed.", ""])
        return "\n".join(lines)
    evaluation = selected["evaluation"]
    lines.extend(
        [
            "## Selected",
            "",
            f"- Config index: `{selected['config_index']}`",
            f"- Parameters: `{json.dumps(selected['config'], sort_keys=True)}`",
            f"- Mean adaptive cost: `{evaluation['mean_adaptive_overall_cost']:.4f}`",
            f"- Mean ML-only cost: `{evaluation['mean_ml_overall_cost']:.4f}`",
            f"- Mean high-complexity improvement: `{evaluation['mean_high_improvement_fraction']:.4f}`",
            "",
        ]
    )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument("--calibration-trace", action="append", required=True)
    parser.add_argument("--tuned-a3-config", required=True)
    parser.add_argument("--segment-artifact", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--output-artifact")
    parser.add_argument("--complexity-thresholds", default="3,4")
    parser.add_argument(
        "--sparse-authority-modes",
        default="tuned_a3,quality_gated_a3,stay_unless_weak",
    )
    parser.add_argument("--sparse-rsrp-floors", default="-100,-105,-110,-112")
    parser.add_argument(
        "--sparse-sinr-floors",
        default="-30,-25,-20,-15,-10,-5,0",
        help=(
            "Serving SINR values at or below the floor are weak. The wide default "
            "covers strict floors because dense-highway startup SINR can be below -20 dB."
        ),
    )
    parser.add_argument("--sparse-extra-margins", default="0,3,6,9")
    parser.add_argument("--staged", action="store_true")
    parser.add_argument("--stage-a-seed", type=int, default=52)
    parser.add_argument("--stage-a-max-configs", type=int, default=36)
    parser.add_argument("--stage-b-top-configs", type=int, default=12)
    parser.add_argument("--fail-if-no-pass", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary = tune_sparse_authority_replay_params(args)
    except Exception as exc:  # noqa: BLE001 - command should fail visibly
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
