#!/usr/bin/env python3
"""Train an offline candidate-ranker artifact from labeled ranker JSONL."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import joblib
import lightgbm as lgb
import numpy as np
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.policy_comparison.candidate_ranker_artifact import (  # noqa: E402
    LABEL_COLUMNS,
    RANKER_MODEL_TYPE,
    RANKER_TARGET,
    group_key,
    row_to_feature_vector,
    select_feature_columns,
    sha256_file,
)


DEFAULT_MIN_HIGH_COMPLEXITY_ROWS = 1000


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


def parse_seed_list(raw: str | None) -> list[int]:
    if not raw:
        return []
    return [int(item.strip()) for item in raw.split(",") if item.strip()]


def read_ranker_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid ranker row at {path}:{line_number}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"ranker row must be an object at {path}:{line_number}")
            rows.append(payload)
    if not rows:
        raise ValueError("candidate-ranker dataset contains no rows")
    return rows


def validate_ranker_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    forbidden_evaluation_seeds: Sequence[int],
    min_target_std: float,
    min_high_complexity_rows: int,
    min_high_complexity_groups: int,
) -> None:
    if min_high_complexity_rows < 0:
        raise ValueError("min_high_complexity_rows must be non-negative")
    required = {
        "candidate_cell",
        "serving_cell",
        "selected_label",
        "rank_label",
        "handover_desirable",
        RANKER_TARGET,
    }
    for index, row in enumerate(rows):
        missing = sorted(required.difference(row))
        if missing:
            raise ValueError(
                f"ranker row {index} missing required field(s): {', '.join(missing)}"
            )
        target = float(row[RANKER_TARGET])
        if not math.isfinite(target):
            raise ValueError(f"ranker row {index} target must be finite")

    seeds = {int(row.get("seed", 0)) for row in rows}
    overlap = seeds.intersection(forbidden_evaluation_seeds)
    if overlap:
        raise ValueError(
            "ranker training seed(s) overlap forbidden evaluation seed(s): "
            + ", ".join(str(seed) for seed in sorted(overlap))
        )

    high_complexity_rows = sum(
        1 for row in rows if str(row.get("complexity_bucket")) == "high"
    )
    if high_complexity_rows < min_high_complexity_rows:
        raise ValueError(
            "ranker dataset has insufficient high-complexity rows: "
            f"{high_complexity_rows} < {min_high_complexity_rows}"
        )
    high_complexity_groups = {
        group_key(row) for row in rows if str(row.get("complexity_bucket")) == "high"
    }
    if len(high_complexity_groups) < min_high_complexity_groups:
        raise ValueError(
            "ranker dataset has insufficient high-complexity snapshot groups: "
            f"{len(high_complexity_groups)} < {min_high_complexity_groups}"
        )

    targets = np.asarray([float(row[RANKER_TARGET]) for row in rows], dtype=float)
    if float(np.std(targets)) <= min_target_std:
        raise ValueError("ranker target is constant or near-constant")


def grouped_train_validation_split(
    rows: Sequence[Mapping[str, Any]],
    *,
    validation_split: float,
    seed: int,
) -> tuple[list[int], list[int], dict[str, Any]]:
    groups = sorted({group_key(row) for row in rows})
    if len(groups) < 2:
        raise ValueError("ranker validation requires at least two snapshot groups")
    rng = np.random.default_rng(seed)
    shuffled = list(groups)
    rng.shuffle(shuffled)
    validation_count = max(1, int(math.ceil(len(shuffled) * validation_split)))
    if validation_count >= len(shuffled):
        validation_count = len(shuffled) - 1
    validation_groups = set(shuffled[:validation_count])
    train_indices: list[int] = []
    validation_indices: list[int] = []
    for index, row in enumerate(rows):
        if group_key(row) in validation_groups:
            validation_indices.append(index)
        else:
            train_indices.append(index)
    if not train_indices or not validation_indices:
        raise ValueError("ranker grouped split produced an empty train/validation set")
    return train_indices, validation_indices, {
        "group_count": len(groups),
        "train_group_count": len(groups) - len(validation_groups),
        "validation_group_count": len(validation_groups),
        "train_row_count": len(train_indices),
        "validation_row_count": len(validation_indices),
        "validation_split": validation_split,
        "split_seed": seed,
    }


def train_ranker_artifact(args: argparse.Namespace) -> dict[str, Any]:
    dataset_path = Path(args.dataset)
    output_artifact = Path(args.output_artifact)
    manifest_path = Path(args.dataset_manifest) if args.dataset_manifest else Path(
        f"{dataset_path}.manifest.json"
    )
    if output_artifact.exists() and not args.overwrite:
        raise ValueError(f"ranker artifact already exists: {output_artifact}")
    meta_path = Path(f"{output_artifact}.meta.json")
    report_path = Path(f"{output_artifact}.training_report.json")
    for path in (meta_path, report_path):
        if path.exists() and not args.overwrite:
            raise ValueError(f"ranker output already exists: {path}")

    rows = read_ranker_jsonl(dataset_path)
    validate_ranker_rows(
        rows,
        forbidden_evaluation_seeds=parse_seed_list(args.forbid_evaluation_seed),
        min_target_std=args.min_target_std,
        min_high_complexity_rows=args.min_high_complexity_rows,
        min_high_complexity_groups=args.min_high_complexity_groups,
    )
    feature_columns = select_feature_columns(rows)
    forbidden_features = {"ue_id", "serving_cell", "candidate_cell"}
    leaked = sorted(forbidden_features.intersection(feature_columns))
    if leaked:
        raise ValueError("ranker feature columns include raw IDs: " + ", ".join(leaked))

    train_indices, validation_indices, split_report = grouped_train_validation_split(
        rows,
        validation_split=args.validation_split,
        seed=args.seed,
    )
    x = np.asarray(
        [
            row_to_feature_vector(row, feature_columns=feature_columns)
            for row in rows
        ],
        dtype=float,
    )
    y = np.asarray([float(row[RANKER_TARGET]) for row in rows], dtype=float)
    x_train = x[train_indices]
    y_train = y[train_indices]
    x_val = x[validation_indices]
    y_val = y[validation_indices]

    model = lgb.LGBMRegressor(
        n_estimators=args.n_estimators,
        learning_rate=args.learning_rate,
        max_depth=args.max_depth,
        num_leaves=args.num_leaves,
        min_child_samples=args.min_child_samples,
        random_state=args.seed,
    )
    model.fit(x_train, y_train)
    train_predictions = np.asarray(model.predict(x_train), dtype=float)
    validation_predictions = np.asarray(model.predict(x_val), dtype=float)
    if float(np.std(train_predictions)) <= args.min_prediction_std:
        raise ValueError("ranker model produced constant or near-constant scores")

    threshold_tuning = tune_threshold(
        [rows[index] for index in validation_indices],
        validation_predictions,
        default_threshold=args.default_threshold,
    )
    if threshold_tuning["selected_error_rate"] > args.max_target_selection_error:
        raise ValueError(
            "ranker validation target-selection error is too high: "
            f"{threshold_tuning['selected_error_rate']:.4f} > "
            f"{args.max_target_selection_error:.4f}"
        )
    selected_precision = threshold_tuning.get("selected_handover_precision", 0.0)
    if selected_precision < args.min_handover_precision:
        raise ValueError(
            "ranker validation handover precision is too low: "
            f"{selected_precision:.4f} < {args.min_handover_precision:.4f}"
        )
    validation_metrics = {
        "target": RANKER_TARGET,
        "train_rmse": _rmse(y_train, train_predictions),
        "validation_rmse": _rmse(y_val, validation_predictions),
        "validation_mae": float(mean_absolute_error(y_val, validation_predictions)),
        "validation_r2": _safe_r2(y_val, validation_predictions),
        "train_prediction_std": float(np.std(train_predictions)),
        "validation_prediction_std": float(np.std(validation_predictions)),
        "target_std": float(np.std(y)),
    }

    dataset_manifest: dict[str, Any] = {}
    if manifest_path.is_file():
        loaded_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if isinstance(loaded_manifest, dict):
            dataset_manifest = loaded_manifest

    label_counts = Counter(str(row.get("selected_label")) for row in rows)
    complexity_counts = Counter(str(row.get("complexity_bucket")) for row in rows)
    high_complexity_row_count = int(complexity_counts.get("high", 0))
    metadata = {
        "model_type": RANKER_MODEL_TYPE,
        "model_family": "candidate_ranker",
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "training_data_source": {
            "dataset": str(dataset_path),
            "dataset_manifest": str(manifest_path) if manifest_path.is_file() else None,
            "dataset_sha256": sha256_file(dataset_path),
            "trace_hashes": dataset_manifest.get("trace_hashes", {}),
        },
        "scenario_seeds": sorted({int(row.get("seed", 0)) for row in rows}),
        "scenarios": sorted({str(row.get("scenario") or "") for row in rows}),
        "dataset_size": len(rows),
        "selected_features": feature_columns,
        "excluded_columns": sorted(set(rows[0]).intersection(LABEL_COLUMNS) | {
            "ue_id",
            "serving_cell",
            "candidate_cell",
            "scenario",
            "seed",
            "topology_hash",
            "step_index",
            "timestamp_s",
        }),
        "target": RANKER_TARGET,
        "decision_objective": "stay_aware_candidate_margin",
        "validation_metrics": validation_metrics,
        "threshold_tuning_result": threshold_tuning,
        "ranker_decision_parameters": {
            "selection_source": "training_validation_threshold",
            "selected_min_margin": max(
                float(threshold_tuning["selected_threshold"]),
                5.0,
            ),
            "min_ml_dwell_s": 10.0,
            "a3_reentry_extra_margin_db": 3.0,
            "max_target_selection_error": args.max_target_selection_error,
            "min_handover_precision": args.min_handover_precision,
        },
        "seed_split": split_report,
        "git_commit": git_commit(),
        "class_distribution": dict(sorted(label_counts.items())),
        "complexity_bucket_counts": dict(sorted(complexity_counts.items())),
        "high_complexity_row_count": high_complexity_row_count,
        "min_high_complexity_rows": args.min_high_complexity_rows,
        "min_high_complexity_groups": args.min_high_complexity_groups,
        "label_policy": dataset_manifest.get("label_policy", {}),
        "trace_complexity_summaries": dataset_manifest.get(
            "trace_complexity_summaries",
            [],
        ),
        "feature_schema_version": 1,
    }

    output_artifact.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "model": model,
            "feature_columns": feature_columns,
            "metadata": metadata,
        },
        output_artifact,
    )
    metadata["model_sha256"] = sha256_file(output_artifact)
    meta_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    report = {
        "artifact_path": str(output_artifact),
        "metadata_path": str(meta_path),
        "training_metrics": validation_metrics,
        "threshold_tuning_result": threshold_tuning,
        "metadata": metadata,
    }
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return report


def tune_threshold(
    validation_rows: Sequence[Mapping[str, Any]],
    predictions: Sequence[float],
    *,
    default_threshold: float,
) -> dict[str, Any]:
    by_group: dict[tuple[str, int, str, int, float], list[tuple[Mapping[str, Any], float]]] = {}
    for row, prediction in zip(validation_rows, predictions):
        by_group.setdefault(group_key(row), []).append((row, float(prediction)))
    if not by_group:
        raise ValueError("cannot tune ranker threshold without validation groups")

    candidate_thresholds = sorted(
        {
            float(default_threshold),
            0.0,
            *[float(prediction) for prediction in predictions],
        }
    )
    evaluated = [
        _evaluate_threshold(by_group, threshold)
        for threshold in candidate_thresholds
    ]
    selected = min(
        evaluated,
        key=lambda item: (
            item["error_count"],
            item["false_positive_count"],
            item["false_negative_count"],
            abs(item["threshold"] - default_threshold),
            item["threshold"],
        ),
    )
    return {
        "selected_threshold": selected["threshold"],
        "default_threshold": float(default_threshold),
        "validation_group_count": len(by_group),
        "evaluated_threshold_count": len(evaluated),
        "best_evaluated_thresholds": sorted(
            evaluated,
            key=lambda item: (
                item["error_count"],
                item["false_positive_count"],
                item["false_negative_count"],
                abs(item["threshold"] - default_threshold),
                item["threshold"],
            ),
        )[:20],
        "selected_error_rate": selected["error_rate"],
        "selected_handover_precision": selected["handover_precision"],
        "selected_handover_recall": selected["handover_recall"],
        "selected_false_positive_count": selected["false_positive_count"],
        "selected_false_negative_count": selected["false_negative_count"],
        "selected_wrong_target_count": selected["wrong_target_count"],
    }


def _evaluate_threshold(
    grouped_rows: Mapping[tuple[str, int, str, int, float], Sequence[tuple[Mapping[str, Any], float]]],
    threshold: float,
) -> dict[str, Any]:
    error_count = 0
    false_positive_count = 0
    false_negative_count = 0
    wrong_target_count = 0
    true_positive_count = 0
    predicted_positive_count = 0
    actual_positive_count = 0
    for group_rows in grouped_rows.values():
        ordered = sorted(
            group_rows,
            key=lambda item: (item[1], str(item[0].get("candidate_cell"))),
            reverse=True,
        )
        predicted_row, predicted_score = ordered[0]
        predicted_target = (
            str(predicted_row.get("candidate_cell"))
            if predicted_score >= threshold
            else None
        )
        if predicted_target is not None:
            predicted_positive_count += 1
        true_targets: set[str] = set()
        for row, _prediction in group_rows:
            if int(row.get("selected_label", 0)) == 1:
                true_targets.add(str(row.get("candidate_cell")))
        if true_targets:
            actual_positive_count += 1
        if (
            (predicted_target is None and not true_targets)
            or (predicted_target is not None and predicted_target in true_targets)
        ):
            if predicted_target is not None:
                true_positive_count += 1
            continue
        error_count += 1
        if predicted_target is not None and not true_targets:
            false_positive_count += 1
        elif predicted_target is None and true_targets:
            false_negative_count += 1
        else:
            wrong_target_count += 1
    group_count = len(grouped_rows)
    return {
        "threshold": float(threshold),
        "group_count": group_count,
        "error_count": error_count,
        "error_rate": error_count / group_count if group_count else 1.0,
        "false_positive_count": false_positive_count,
        "false_negative_count": false_negative_count,
        "wrong_target_count": wrong_target_count,
        "true_positive_count": true_positive_count,
        "predicted_positive_count": predicted_positive_count,
        "actual_positive_count": actual_positive_count,
        "handover_precision": (
            true_positive_count / predicted_positive_count
            if predicted_positive_count
            else 1.0
        ),
        "handover_recall": (
            true_positive_count / actual_positive_count
            if actual_positive_count
            else 1.0
        ),
    }


def _rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(math.sqrt(mean_squared_error(y_true, y_pred)))


def _safe_r2(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    try:
        value = float(r2_score(y_true, y_pred))
    except ValueError:
        return 0.0
    if not math.isfinite(value):
        return 0.0
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument("--dataset", required=True, help="Labeled ranker JSONL.")
    parser.add_argument("--output-artifact", required=True, help="Output .joblib path.")
    parser.add_argument("--dataset-manifest", help="Optional ranker dataset manifest JSON.")
    parser.add_argument(
        "--forbid-evaluation-seed",
        default="42,43,44",
        help="Comma-separated evaluation seeds that must not appear in training rows.",
    )
    parser.add_argument("--seed", type=int, default=41)
    parser.add_argument("--validation-split", type=float, default=0.2)
    parser.add_argument("--n-estimators", type=int, default=150)
    parser.add_argument("--learning-rate", type=float, default=0.05)
    parser.add_argument("--max-depth", type=int, default=-1)
    parser.add_argument("--num-leaves", type=int, default=31)
    parser.add_argument("--min-child-samples", type=int, default=5)
    parser.add_argument("--default-threshold", type=float, default=2.0)
    parser.add_argument("--min-target-std", type=float, default=1e-6)
    parser.add_argument("--min-prediction-std", type=float, default=1e-6)
    parser.add_argument(
        "--min-high-complexity-rows",
        type=int,
        default=DEFAULT_MIN_HIGH_COMPLEXITY_ROWS,
        help=(
            "Minimum high-complexity candidate rows required in the training "
            "dataset. Default: 1000."
        ),
    )
    parser.add_argument(
        "--min-high-complexity-groups",
        type=int,
        default=500,
        help=(
            "Minimum high-complexity snapshot groups required in the training "
            "dataset. Default: 500."
        ),
    )
    parser.add_argument(
        "--max-target-selection-error",
        type=float,
        default=0.35,
        help="Maximum validation target-selection error rate. Default: 0.35.",
    )
    parser.add_argument(
        "--min-handover-precision",
        type=float,
        default=0.75,
        help="Minimum validation handover precision. Default: 0.75.",
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = train_ranker_artifact(args)
    except Exception as exc:  # noqa: BLE001 - command should fail visibly
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
