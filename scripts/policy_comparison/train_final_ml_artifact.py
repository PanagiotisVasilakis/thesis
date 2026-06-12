#!/usr/bin/env python3
"""Train a reproducible final ML handover artifact from policy-free traces."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
ML_SERVICE_ROOT = REPO_ROOT / "5g-network-optimization" / "services" / "ml-service"

for import_path in (REPO_ROOT, ML_SERVICE_ROOT):
    path_text = str(import_path)
    if path_text not in sys.path:
        sys.path.insert(0, path_text)

from scripts.policy_comparison.policy_adapters import trace_record_to_ml_payload
from scripts.policy_comparison.schemas import MeasurementTraceRecord, VisibleCellMeasurement
from scripts.policy_comparison.trace_io import read_trace_jsonl

from ml_service.app.config.feature_specs import sanitize_feature_ranges
from ml_service.app.core.qos_encoding import encode_service_type
from ml_service.app.initialization.model_version import MODEL_VERSION
from ml_service.app.models.lightgbm_selector import LightGBMSelector


DEFAULT_FEATURE_CONFIG = (
    ML_SERVICE_ROOT / "ml_service" / "app" / "config" / "features.yaml"
)


def sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:  # noqa: BLE001 - metadata should still be written
        return "unknown"


def parse_seed_list(raw: str | None) -> List[int]:
    if not raw:
        return []
    return [int(item.strip()) for item in raw.split(",") if item.strip()]


def _load_records(trace_paths: Sequence[Path]) -> List[MeasurementTraceRecord]:
    records: List[MeasurementTraceRecord] = []
    for path in trace_paths:
        records.extend(read_trace_jsonl(path))
    if not records:
        raise ValueError("training traces produced no records")
    return records


def validate_seed_split(
    records: Sequence[MeasurementTraceRecord],
    forbidden_evaluation_seeds: Sequence[int],
) -> None:
    training_seeds = {record.seed for record in records}
    overlap = training_seeds.intersection(forbidden_evaluation_seeds)
    if overlap:
        raise ValueError(
            "training trace seed(s) overlap forbidden evaluation seed(s): "
            + ", ".join(str(seed) for seed in sorted(overlap))
        )


def _normalized_load(cell: VisibleCellMeasurement, max_load: float) -> float:
    if cell.load is None:
        return 0.0
    load = max(0.0, float(cell.load))
    if max_load > 1.0:
        return load / max_load
    return load


def score_visible_cell(
    cell: VisibleCellMeasurement,
    *,
    max_load: float,
    load_penalty_db: float,
    sinr_weight: float,
    rsrq_weight: float,
) -> float:
    """Return a deterministic RF/QoS/load score used only for trace labels."""

    return (
        float(cell.rsrp_dbm)
        + sinr_weight * float(cell.sinr_db if cell.sinr_db is not None else 0.0)
        + rsrq_weight * float(cell.rsrq_db if cell.rsrq_db is not None else -30.0)
        - load_penalty_db * _normalized_load(cell, max_load)
    )


def label_record(
    record: MeasurementTraceRecord,
    *,
    stay_margin_db: float,
    load_penalty_db: float,
    sinr_weight: float,
    rsrq_weight: float,
) -> tuple[str, Dict[str, float], float, float]:
    max_load = max(float(cell.load or 0.0) for cell in record.visible_cells)
    scores = {
        cell.cell_id: score_visible_cell(
            cell,
            max_load=max_load,
            load_penalty_db=load_penalty_db,
            sinr_weight=sinr_weight,
            rsrq_weight=rsrq_weight,
        )
        for cell in record.visible_cells
    }
    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_cell, best_score = ordered[0]
    serving_score = scores[record.serving_cell]
    selected = best_cell
    if best_cell != record.serving_cell and best_score - serving_score < stay_margin_db:
        selected = record.serving_cell

    margin = ordered[0][1] - ordered[1][1] if len(ordered) > 1 else ordered[0][1]
    connected_rank = next(
        idx + 1
        for idx, (cell_id, _) in enumerate(ordered)
        if cell_id == record.serving_cell
    )
    return selected, scores, float(margin), float(connected_rank)


def record_to_training_sample(
    record: MeasurementTraceRecord,
    *,
    stay_margin_db: float,
    load_penalty_db: float,
    sinr_weight: float,
    rsrq_weight: float,
) -> Dict[str, Any]:
    label, scores, margin, connected_rank = label_record(
        record,
        stay_margin_db=stay_margin_db,
        load_penalty_db=load_penalty_db,
        sinr_weight=sinr_weight,
        rsrq_weight=rsrq_weight,
    )
    payload = trace_record_to_ml_payload(record)
    serving = record.visible_cell_map[record.serving_cell]
    payload.update(
        {
            "optimal_antenna": label,
            "antenna_selection_scores": scores,
            "optimal_score_margin": margin,
            "connected_signal_rank": connected_rank,
            "cell_load": float(serving.load or 0.0),
        }
    )
    return payload


def build_training_dataset(
    records: Sequence[MeasurementTraceRecord],
    *,
    stay_margin_db: float,
    load_penalty_db: float,
    sinr_weight: float,
    rsrq_weight: float,
) -> tuple[List[Dict[str, Any]], Counter[str], int]:
    samples = [
        record_to_training_sample(
            record,
            stay_margin_db=stay_margin_db,
            load_penalty_db=load_penalty_db,
            sinr_weight=sinr_weight,
            rsrq_weight=rsrq_weight,
        )
        for record in records
    ]
    label_counts: Counter[str] = Counter(str(sample["optimal_antenna"]) for sample in samples)
    max_neighbors = max(
        len(sample.get("rf_metrics") or {}) - 1
        for sample in samples
    )
    return samples, label_counts, max_neighbors


def _raw_predict(selector: LightGBMSelector, sample: Mapping[str, Any]) -> tuple[str, float]:
    features = selector.extract_features(dict(sample))
    prepared = selector._prepare_features_for_model(features)  # noqa: SLF001
    selector._ensure_feature_defaults(prepared)  # noqa: SLF001
    sanitize_feature_ranges(prepared)

    service_type = prepared.get("service_type")
    if service_type is not None and not isinstance(service_type, (int, float)):
        prepared["service_type"] = encode_service_type(service_type)

    x_arr = np.array([[prepared[name] for name in selector.feature_names]], dtype=float)
    x_arr = selector.scaler.transform(x_arr)
    prediction_model = selector.calibrated_model or selector.model
    if prediction_model is None:
        raise ValueError("selector has no trained model")
    probabilities = np.asarray(prediction_model.predict_proba(x_arr))[0]
    classes = np.asarray(prediction_model.classes_)
    index = int(np.argmax(probabilities))
    return str(classes[index]), float(probabilities[index])


def sanity_check_predictions(
    selector: LightGBMSelector,
    records: Sequence[MeasurementTraceRecord],
    samples: Sequence[Mapping[str, Any]],
    *,
    min_unique_predictions: int,
    max_poor_rsrp_gap_db: float,
    max_poor_rsrp_rate: float,
    min_training_accuracy: float,
) -> Dict[str, Any]:
    predictions: Counter[str] = Counter()
    confidences: List[float] = []
    label_matches = 0
    invalid_predictions = 0
    poor_rsrp_predictions = 0

    for record, sample in zip(records, samples):
        predicted, confidence = _raw_predict(selector, sample)
        predictions[predicted] += 1
        confidences.append(confidence)
        if predicted == str(sample["optimal_antenna"]):
            label_matches += 1

        visible = record.visible_cell_map
        if predicted not in visible:
            invalid_predictions += 1
            continue
        best_rsrp = max(cell.rsrp_dbm for cell in record.visible_cells)
        predicted_rsrp = visible[predicted].rsrp_dbm
        if best_rsrp - predicted_rsrp > max_poor_rsrp_gap_db:
            poor_rsrp_predictions += 1

    total = len(samples)
    accuracy = label_matches / total if total else 0.0
    poor_rate = poor_rsrp_predictions / total if total else 0.0
    unique_predictions = len(predictions)
    report = {
        "total_predictions": total,
        "unique_predictions": unique_predictions,
        "prediction_distribution": dict(sorted(predictions.items())),
        "training_label_accuracy": accuracy,
        "invalid_prediction_count": invalid_predictions,
        "poor_rsrp_prediction_count": poor_rsrp_predictions,
        "poor_rsrp_prediction_rate": poor_rate,
        "max_poor_rsrp_gap_db": max_poor_rsrp_gap_db,
        "avg_confidence": float(np.mean(confidences)) if confidences else None,
        "min_confidence": float(np.min(confidences)) if confidences else None,
    }
    if invalid_predictions:
        raise ValueError(f"model predicted {invalid_predictions} cells absent from traces")
    if unique_predictions < min_unique_predictions:
        raise ValueError(
            f"model collapse detected: {unique_predictions} unique predictions "
            f"< required {min_unique_predictions}"
        )
    if poor_rate > max_poor_rsrp_rate:
        raise ValueError(
            f"model selected poor-RSRP cells too often: {poor_rate:.3f} "
            f"> allowed {max_poor_rsrp_rate:.3f}"
        )
    if accuracy < min_training_accuracy:
        raise ValueError(
            f"training-label accuracy too low: {accuracy:.3f} "
            f"< required {min_training_accuracy:.3f}"
        )
    return report


def write_final_metadata(
    *,
    model_path: Path,
    feature_config: Path,
    trace_paths: Sequence[Path],
    records: Sequence[MeasurementTraceRecord],
    selector: LightGBMSelector,
    training_metrics: Mapping[str, Any],
    sanity_report: Mapping[str, Any],
    label_counts: Counter[str],
    label_policy: Mapping[str, Any],
) -> Dict[str, Any]:
    meta_path = Path(f"{model_path}.meta.json")
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    feature_config_hash = sha256_file(feature_config)
    trace_hashes = {str(path): sha256_file(path) for path in trace_paths}
    metadata.update(
        {
            "model_type": "lightgbm",
            "version": MODEL_VERSION,
            "training_data_source": {
                "mode": "policy_free_calibration_trace",
                "traces": [str(path) for path in trace_paths],
            },
            "scenario_seeds": sorted({record.seed for record in records}),
            "dataset_size": len(records),
            "selected_features": list(selector.feature_names),
            "validation_metrics": dict(training_metrics),
            "calibration_state": {
                "confidence_calibrated": bool(
                    training_metrics.get("confidence_calibrated")
                ),
                "method": training_metrics.get("calibration_method"),
            },
            "git_commit": git_commit(),
            "feature_config_path": str(feature_config),
            "feature_config_sha256": feature_config_hash,
            "model_sha256": sha256_file(model_path),
            "scaler_sha256": sha256_file(Path(f"{model_path}.scaler")),
            "dataset_manifest": {
                "record_count": len(records),
                "scenarios": sorted({record.scenario for record in records}),
                "topology_hashes": sorted(
                    {record.topology_hash for record in records if record.topology_hash}
                ),
                "trace_hashes": trace_hashes,
            },
            "label_policy": dict(label_policy),
            "class_distribution": dict(sorted(label_counts.items())),
            "post_training_sanity": dict(sanity_report),
        }
    )
    meta_path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
    return metadata


def train_artifact(args: argparse.Namespace) -> Dict[str, Any]:
    trace_paths = [Path(path) for path in args.trace]
    feature_config = Path(args.feature_config)
    output_model = Path(args.output_model)

    if output_model.exists() and not args.overwrite:
        raise ValueError(f"output model already exists: {output_model}")
    if Path(f"{output_model}.meta.json").exists() and not args.overwrite:
        raise ValueError(f"output metadata already exists: {output_model}.meta.json")
    if Path(f"{output_model}.scaler").exists() and not args.overwrite:
        raise ValueError(f"output scaler already exists: {output_model}.scaler")

    records = _load_records(trace_paths)
    validate_seed_split(records, parse_seed_list(args.forbid_evaluation_seed))

    label_policy = {
        "name": "rf_qos_load_score_with_stay_margin",
        "stay_margin_db": args.stay_margin_db,
        "load_penalty_db": args.load_penalty_db,
        "sinr_weight": args.sinr_weight,
        "rsrq_weight": args.rsrq_weight,
    }
    samples, label_counts, max_neighbors = build_training_dataset(
        records,
        stay_margin_db=args.stay_margin_db,
        load_penalty_db=args.load_penalty_db,
        sinr_weight=args.sinr_weight,
        rsrq_weight=args.rsrq_weight,
    )

    neighbor_count = args.neighbor_count or max_neighbors
    selector = LightGBMSelector(
        model_path=str(output_model),
        neighbor_count=neighbor_count,
        config_path=str(feature_config),
        n_estimators=args.n_estimators,
        random_state=args.seed,
    )
    training_metrics = selector.train(
        samples,
        validation_split=args.validation_split,
        early_stopping_rounds=args.early_stopping_rounds,
    )
    sanity_report = sanity_check_predictions(
        selector,
        records,
        samples,
        min_unique_predictions=args.min_unique_predictions,
        max_poor_rsrp_gap_db=args.max_poor_rsrp_gap_db,
        max_poor_rsrp_rate=args.max_poor_rsrp_rate,
        min_training_accuracy=args.min_training_accuracy,
    )

    output_model.parent.mkdir(parents=True, exist_ok=True)
    if not selector.save(
        str(output_model),
        metrics=dict(training_metrics),
        model_type="lightgbm",
        version=MODEL_VERSION,
    ):
        raise ValueError(f"failed to save model artifact: {output_model}")

    metadata = write_final_metadata(
        model_path=output_model,
        feature_config=feature_config,
        trace_paths=trace_paths,
        records=records,
        selector=selector,
        training_metrics=training_metrics,
        sanity_report=sanity_report,
        label_counts=label_counts,
        label_policy=label_policy,
    )

    report_path = Path(f"{output_model}.training_report.json")
    report_path.write_text(
        json.dumps(
            {
                "model_path": str(output_model),
                "metadata_path": str(output_model) + ".meta.json",
                "scaler_path": str(output_model) + ".scaler",
                "training_metrics": training_metrics,
                "post_training_sanity": sanity_report,
                "class_distribution": dict(sorted(label_counts.items())),
                "metadata": metadata,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return {
        "model_path": str(output_model),
        "metadata_path": str(output_model) + ".meta.json",
        "scaler_path": str(output_model) + ".scaler",
        "training_report_path": str(report_path),
        "dataset_size": len(records),
        "class_distribution": dict(sorted(label_counts.items())),
        "post_training_sanity": sanity_report,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument(
        "--trace",
        action="append",
        required=True,
        help="Policy-free calibration trace JSONL. May be supplied multiple times.",
    )
    parser.add_argument(
        "--output-model",
        required=True,
        help="Where to write the final .joblib artifact.",
    )
    parser.add_argument(
        "--feature-config",
        default=str(DEFAULT_FEATURE_CONFIG),
        help="Feature config used for training and recorded in metadata.",
    )
    parser.add_argument(
        "--forbid-evaluation-seed",
        default="42,43,44",
        help="Comma-separated evaluation seeds that must not appear in training traces.",
    )
    parser.add_argument("--seed", type=int, default=41, help="LightGBM random seed.")
    parser.add_argument("--neighbor-count", type=int, default=0)
    parser.add_argument("--n-estimators", type=int, default=150)
    parser.add_argument("--validation-split", type=float, default=0.2)
    parser.add_argument("--early-stopping-rounds", type=int, default=20)
    parser.add_argument("--stay-margin-db", type=float, default=2.0)
    parser.add_argument("--load-penalty-db", type=float, default=4.0)
    parser.add_argument("--sinr-weight", type=float, default=0.2)
    parser.add_argument("--rsrq-weight", type=float, default=0.1)
    parser.add_argument("--min-unique-predictions", type=int, default=4)
    parser.add_argument("--max-poor-rsrp-gap-db", type=float, default=8.0)
    parser.add_argument("--max-poor-rsrp-rate", type=float, default=0.05)
    parser.add_argument("--min-training-accuracy", type=float, default=0.70)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = train_artifact(args)
    except Exception as exc:  # noqa: BLE001 - command should fail visibly
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
