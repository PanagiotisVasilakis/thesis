#!/usr/bin/env python3
"""Run deterministic offline replay over canonical policy comparison traces."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence

if __package__ in {None, ""}:  # pragma: no cover - direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import requests  # type: ignore[import-untyped]

from scripts.policy_comparison.manifest import build_reproducibility_manifest
from scripts.policy_comparison.policy_adapters import (
    CandidateRankerPolicyAdapter,
    ComparisonPolicyAdapter,
    ComplexityAwarePolicyAdapter,
    FixedA3PolicyAdapter,
    LoadAwareA3PolicyAdapter,
    MLPolicyAdapter,
    StrongestSignalPolicyAdapter,
    TunedA3PolicyAdapter,
    VelocityAdaptiveA3PolicyAdapter,
)
from scripts.policy_comparison.replay import OfflineReplayRunner
from scripts.policy_comparison.schemas import MeasurementTraceRecord
from scripts.policy_comparison.trace_io import (
    read_trace_jsonl,
    write_decisions_jsonl,
)


SUPPORTED_POLICIES = {
    "ml",
    "fixed_a3_baseline",
    "tuned_a3_baseline",
    "strongest_rsrp_baseline",
    "strongest_sinr_baseline",
    "strongest_rsrq_baseline",
    "load_aware_a3_baseline",
    "velocity_adaptive_a3_baseline",
    "complexity_aware_ml_a3",
}


def parse_policy_list(raw: str) -> List[str]:
    policies = [item.strip() for item in raw.split(",") if item.strip()]
    if not policies:
        raise ValueError("--policies must include at least one policy")
    unknown = sorted(set(policies) - SUPPORTED_POLICIES)
    if unknown:
        raise ValueError(f"unknown policies: {', '.join(unknown)}")
    if len(set(policies)) != len(policies):
        raise ValueError("--policies contains duplicates")
    return policies


def ensure_fresh_output_dir(output_dir: Path) -> None:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"output directory already exists and is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)


def build_policy_adapters(
    policies: Sequence[str],
    *,
    evaluation_trace: Path,
    calibration_trace: Path | None,
    tuned_a3_config: Path | None,
    ml_base_url: str | None,
    ml_backend: str = "service",
    ranker_artifact: Path | None = None,
    high_complexity_threshold: int = 3,
    ranker_min_margin: float | None = None,
    ranker_min_ml_dwell_s: float | None = None,
    a3_reentry_extra_margin_db: float | None = None,
    ml_segment_hold_s: float | None = None,
):
    adapters: List[ComparisonPolicyAdapter] = []
    tuning_result = None
    tuned_config_data: Dict[str, Any] | None = None
    calibration_records: List[MeasurementTraceRecord] | None = None

    needs_tuned_a3 = bool(
        {"tuned_a3_baseline", "complexity_aware_ml_a3"}.intersection(policies)
    )
    if needs_tuned_a3:
        if calibration_trace is not None and tuned_a3_config is not None:
            raise ValueError(
                "provide --calibration-trace or --tuned-a3-config, not both"
            )
        if calibration_trace is None and tuned_a3_config is None:
            raise ValueError(
                "tuned_a3_baseline requires --tuned-a3-config from calibration "
                "or a separate --calibration-trace; tuning results will not be fabricated"
            )
        if calibration_trace is not None and calibration_trace.resolve() == evaluation_trace.resolve():
            raise ValueError("--calibration-trace must be different from --trace")
        if calibration_trace is not None:
            calibration_records = read_trace_jsonl(calibration_trace)

    def build_tuned_adapter() -> TunedA3PolicyAdapter:
        nonlocal tuning_result, tuned_config_data
        if tuned_a3_config is not None:
            tuned_adapter = TunedA3PolicyAdapter.from_tuned_config(tuned_a3_config)
        else:
            assert calibration_records is not None
            tuned_adapter = TunedA3PolicyAdapter.from_calibration_trace(
                calibration_records
            )
        tuning_result = tuned_adapter.tuning_result_dict
        if tuned_a3_config is not None:
            tuned_config_data = tuning_result
        return tuned_adapter

    def build_ml_adapter() -> MLPolicyAdapter:
        resolved_ml_url = ml_base_url or os.environ.get("ML_BASE_URL")
        if not resolved_ml_url:
            raise ValueError("ml policy requires --ml-base-url or ML_BASE_URL")
        return MLPolicyAdapter(
            ml_base_url=resolved_ml_url,
            username=os.environ.get("ML_SERVICE_USERNAME")
            or os.environ.get("ML_AUTH_USERNAME")
            or os.environ.get("ML_SERVICE_USER"),
            password=os.environ.get("ML_SERVICE_PASSWORD")
            or os.environ.get("ML_AUTH_PASSWORD")
            or os.environ.get("ML_SERVICE_PASS"),
        )

    ranker_adapter = None

    def build_ranker_adapter() -> CandidateRankerPolicyAdapter:
        nonlocal ranker_adapter
        if ranker_artifact is None:
            raise ValueError(
                "candidate_ranker backend requires --ranker-artifact"
            )
        if ranker_adapter is None:
            ranker_adapter = CandidateRankerPolicyAdapter(
                ranker_artifact,
                min_margin=ranker_min_margin,
                min_ml_dwell_s=ranker_min_ml_dwell_s,
            )
        return ranker_adapter

    def build_selected_ml_adapter() -> ComparisonPolicyAdapter:
        if ml_backend == "service":
            return build_ml_adapter()
        if ml_backend == "candidate_ranker":
            return build_ranker_adapter()
        raise ValueError(f"unsupported --ml-backend: {ml_backend}")

    def ranker_decision_parameter(name: str) -> float | None:
        if ml_backend != "candidate_ranker" or ranker_artifact is None:
            return None
        adapter = build_ranker_adapter()
        params = getattr(adapter.artifact, "decision_parameters", {})
        value = params.get(name) if isinstance(params, Mapping) else None
        return float(value) if isinstance(value, (int, float)) else None

    for policy in policies:
        if policy == "fixed_a3_baseline":
            adapters.append(FixedA3PolicyAdapter())
        elif policy == "tuned_a3_baseline":
            adapters.append(build_tuned_adapter())
        elif policy == "ml":
            adapters.append(build_selected_ml_adapter())
        elif policy == "strongest_rsrp_baseline":
            adapters.append(StrongestSignalPolicyAdapter(metric="rsrp"))
        elif policy == "strongest_sinr_baseline":
            adapters.append(StrongestSignalPolicyAdapter(metric="sinr"))
        elif policy == "strongest_rsrq_baseline":
            adapters.append(StrongestSignalPolicyAdapter(metric="rsrq"))
        elif policy == "load_aware_a3_baseline":
            adapters.append(LoadAwareA3PolicyAdapter())
        elif policy == "velocity_adaptive_a3_baseline":
            adapters.append(VelocityAdaptiveA3PolicyAdapter())
        elif policy == "complexity_aware_ml_a3":
            selected_a3_guard = (
                a3_reentry_extra_margin_db
                if a3_reentry_extra_margin_db is not None
                else ranker_decision_parameter("a3_reentry_extra_margin_db")
            )
            selected_segment_hold = (
                ml_segment_hold_s
                if ml_segment_hold_s is not None
                else ranker_decision_parameter("ml_segment_hold_s")
            )
            adapters.append(
                ComplexityAwarePolicyAdapter(
                    sparse_policy=build_tuned_adapter(),
                    ml_policy=build_selected_ml_adapter(),
                    high_complexity_threshold=high_complexity_threshold,
                    **(
                        {}
                        if selected_a3_guard is None
                        else {"a3_reentry_extra_margin_db": selected_a3_guard}
                    ),
                    **(
                        {}
                        if selected_segment_hold is None
                        else {"ml_segment_hold_s": selected_segment_hold}
                    ),
                )
            )
    return adapters, tuning_result, calibration_records, tuned_config_data


def validate_calibration_split(
    evaluation_records: Sequence[MeasurementTraceRecord],
    calibration_records: Sequence[MeasurementTraceRecord] | None,
) -> None:
    if calibration_records is None:
        return
    evaluation_keys = _trace_record_keys(evaluation_records)
    calibration_keys = _trace_record_keys(calibration_records)
    overlap = evaluation_keys.intersection(calibration_keys)
    if overlap:
        raise ValueError(
            "calibration and evaluation traces share exact records; "
            "use separate calibration data"
        )
    evaluation_seeds = {record.seed for record in evaluation_records}
    calibration_seeds = {record.seed for record in calibration_records}
    shared_seeds = evaluation_seeds.intersection(calibration_seeds)
    if shared_seeds:
        raise ValueError(
            "calibration and evaluation traces share seed(s): "
            + ", ".join(str(seed) for seed in sorted(shared_seeds))
        )


def validate_tuned_config_split(
    evaluation_records: Sequence[MeasurementTraceRecord],
    tuned_config_data: Mapping[str, Any] | None,
) -> None:
    if not tuned_config_data:
        return
    calibration = tuned_config_data.get("calibration")
    if not isinstance(calibration, Mapping):
        raise ValueError("tuned A3 config must include calibration metadata")

    calibration_seed = calibration.get("seed")
    if calibration_seed is None:
        raise ValueError("tuned A3 config calibration metadata missing seed")
    evaluation_seeds = {record.seed for record in evaluation_records}
    if int(calibration_seed) in evaluation_seeds:
        raise ValueError(
            "tuned A3 config calibration seed overlaps evaluation seed(s): "
            f"{calibration_seed}"
        )

    calibration_scenario = calibration.get("scenario")
    evaluation_scenarios = {record.scenario for record in evaluation_records}
    if calibration_scenario not in evaluation_scenarios or len(evaluation_scenarios) != 1:
        raise ValueError(
            "tuned A3 config calibration scenario must match the evaluation trace scenario"
        )

    calibration_topology_hash = calibration.get("topology_hash")
    evaluation_topology_hashes = {record.topology_hash for record in evaluation_records}
    if None in evaluation_topology_hashes:
        raise ValueError("evaluation trace must include topology_hash when using tuned A3 config")
    if calibration_topology_hash not in evaluation_topology_hashes or len(evaluation_topology_hashes) != 1:
        raise ValueError(
            "tuned A3 config calibration topology_hash must match the evaluation trace"
        )


def _trace_record_keys(records: Iterable[MeasurementTraceRecord]) -> set[tuple]:
    return {
        (
            record.scenario,
            record.seed,
            record.step_index,
            record.ue_id,
            record.timestamp_s,
            record.topology_hash,
        )
        for record in records
    }


def resolve_ml_base_url(raw: str | None) -> str:
    resolved = raw or os.environ.get("ML_BASE_URL")
    if not resolved:
        raise ValueError("ml policy requires --ml-base-url or ML_BASE_URL")
    return resolved.rstrip("/")


def fetch_ml_model_health(ml_base_url: str) -> Dict[str, Any]:
    url = f"{ml_base_url.rstrip('/')}/api/model-health"
    response = requests.get(url, timeout=5)
    if response.status_code >= 400:
        raise ValueError(f"ML model-health returned HTTP {response.status_code}")
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("ML model-health response must be a JSON object")
    if not bool(data.get("ready")):
        raise ValueError("ML model-health reports ready=false")
    return {
        str(key): value
        for key, value in data.items()
        if "password" not in str(key).lower()
        and "secret" not in str(key).lower()
        and "token" not in str(key).lower()
    }


def run(args: argparse.Namespace) -> int:
    policies = parse_policy_list(args.policies)
    trace_path = Path(args.trace)
    output_dir = Path(args.output_dir)
    calibration_trace = Path(args.calibration_trace) if args.calibration_trace else None
    tuned_a3_config = Path(args.tuned_a3_config) if args.tuned_a3_config else None
    ranker_artifact = Path(args.ranker_artifact) if args.ranker_artifact else None

    evaluation_records = read_trace_jsonl(trace_path)
    ml_model_health = None
    if (
        args.ml_backend == "service"
        and {"ml", "complexity_aware_ml_a3"}.intersection(policies)
    ):
        ml_model_health = fetch_ml_model_health(resolve_ml_base_url(args.ml_base_url))

    adapters, tuning_result, calibration_records, tuned_config_data = build_policy_adapters(
        policies,
        evaluation_trace=trace_path,
        calibration_trace=calibration_trace,
        tuned_a3_config=tuned_a3_config,
        ml_base_url=args.ml_base_url,
        ml_backend=args.ml_backend,
        ranker_artifact=ranker_artifact,
        high_complexity_threshold=args.high_complexity_threshold,
        ranker_min_margin=args.ranker_min_margin,
        ranker_min_ml_dwell_s=args.ranker_min_ml_dwell_s,
        a3_reentry_extra_margin_db=args.a3_reentry_extra_margin_db,
        ml_segment_hold_s=args.ml_segment_hold_s,
    )
    validate_calibration_split(evaluation_records, calibration_records)
    validate_tuned_config_split(evaluation_records, tuned_config_data)
    ensure_fresh_output_dir(output_dir)

    result = OfflineReplayRunner(adapters).replay(evaluation_records)

    decisions_dir = output_dir / "decisions"
    for policy_name, policy_result in result.policy_results.items():
        write_decisions_jsonl(
            policy_result.decisions,
            decisions_dir / f"{policy_name}.jsonl",
        )

    (output_dir / "summary.json").write_text(
        json.dumps(result.to_dict(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    if tuned_a3_config is not None and tuning_result is not None:
        (output_dir / "tuned_a3_config.json").write_text(
            json.dumps(tuning_result, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    elif tuning_result is not None:
        (output_dir / "tuned_a3_tuning_result.json").write_text(
            json.dumps(tuning_result, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    manifest = build_reproducibility_manifest(
        scenario=result.scenario,
        seed=result.seed,
        policies={adapter.name: adapter.parameters for adapter in adapters},
        topology_hash=result.topology_hash,
        repo_root=Path(__file__).resolve().parents[2],
        notes={
            "trace": str(trace_path),
            "calibration_trace": str(calibration_trace) if calibration_trace else None,
            "tuned_a3_config": str(tuned_a3_config) if tuned_a3_config else None,
            "ml_model_health": ml_model_health,
            "ml_backend": args.ml_backend,
            "ranker_artifact": str(ranker_artifact) if ranker_artifact else None,
            "high_complexity_threshold": args.high_complexity_threshold,
            "ranker_min_margin": args.ranker_min_margin,
            "ranker_min_ml_dwell_s": args.ranker_min_ml_dwell_s,
            "a3_reentry_extra_margin_db": args.a3_reentry_extra_margin_db,
            "ml_segment_hold_s": args.ml_segment_hold_s,
            "mode": "offline_replay",
            "no_full_experiment_run": True,
        },
    )
    manifest.write_json(output_dir / "manifest.json")

    print(f"Offline replay complete: {output_dir}")
    for policy_name, policy_result in result.policy_results.items():
        summary = policy_result.summary
        print(
            f"- {policy_name}: handovers={summary.handover_count}, "
            f"ping_pongs={summary.ping_pong_count}, "
            f"low_quality_steps={summary.low_quality_step_count}, "
            f"composite_cost={summary.composite_cost:.2f}"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Replay canonical handover measurement traces through ML/fixed-A3/"
            "tuned-A3 policy adapters without running the full thesis experiment."
        )
    )
    parser.add_argument("--trace", required=True, help="Evaluation trace JSONL path.")
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Fresh output directory for replay summary, manifest, and decisions.",
    )
    parser.add_argument(
        "--policies",
        default="fixed_a3_baseline",
        help=(
            "Comma-separated policies: ml,fixed_a3_baseline,tuned_a3_baseline,"
            "strongest_rsrp_baseline,strongest_sinr_baseline,"
            "strongest_rsrq_baseline,load_aware_a3_baseline,"
            "velocity_adaptive_a3_baseline,complexity_aware_ml_a3. "
            "Default: fixed_a3_baseline"
        ),
    )
    parser.add_argument(
        "--calibration-trace",
        help=(
            "Separate calibration JSONL for legacy in-command tuning. Prefer "
            "--tuned-a3-config for evaluation replay."
        ),
    )
    parser.add_argument(
        "--tuned-a3-config",
        help=(
            "Reusable tuned A3 config from scripts.policy_comparison.calibrate_tuned_a3. "
            "Preferred when using tuned_a3_baseline."
        ),
    )
    parser.add_argument(
        "--ml-base-url",
        help="ML service base URL when using ml policy. Falls back to ML_BASE_URL.",
    )
    parser.add_argument(
        "--ml-backend",
        choices=("service", "candidate_ranker"),
        default="service",
        help="ML backend for offline replay. Default: service.",
    )
    parser.add_argument(
        "--ranker-artifact",
        help="Candidate-ranker artifact path when --ml-backend=candidate_ranker.",
    )
    parser.add_argument(
        "--high-complexity-threshold",
        type=int,
        default=3,
        help="Viable candidate count at which complexity_aware_ml_a3 uses ML.",
    )
    parser.add_argument(
        "--ranker-min-margin",
        type=float,
        help=(
            "Override candidate-ranker minimum margin versus stay. Defaults to "
            "artifact metadata, then the conservative ranker default."
        ),
    )
    parser.add_argument(
        "--ranker-min-ml-dwell-s",
        type=float,
        help="Override minimum dwell time after an ML handover before another ML handover.",
    )
    parser.add_argument(
        "--a3-reentry-extra-margin-db",
        type=float,
        help="Override extra sparse-A3 margin required immediately after an ML handover.",
    )
    parser.add_argument(
        "--ml-segment-hold-s",
        type=float,
        help=(
            "Keep ML authority for this many seconds after an ML handover before "
            "sparse/moderate records return to A3. Defaults to artifact metadata, then 0."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except Exception as exc:  # noqa: BLE001 - command should fail visibly
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
