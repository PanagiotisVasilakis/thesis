#!/usr/bin/env python3
"""Train a two-stage segment-controller artifact from segment JSONL rows."""

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
from sklearn.metrics import mean_absolute_error, precision_score

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.policy_comparison.segment_controller import (  # noqa: E402
    row_to_segment_feature_vector,
    segment_group_key,
)
from scripts.policy_comparison.segment_controller_artifact import (  # noqa: E402
    SEGMENT_CONTROLLER_MODEL_FAMILY,
    SEGMENT_CONTROLLER_MODEL_TYPE,
    DEFAULT_SEGMENT_DECISION_PARAMETERS,
    select_feature_columns_by_type,
    sha256_file,
)


DEFAULT_MIN_HIGH_COMPLEXITY_CANDIDATE_ROWS = 2500
DEFAULT_MIN_HIGH_COMPLEXITY_SNAPSHOT_GROUPS = 1000


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


def read_segment_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid segment row at {path}:{line_number}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"segment row must be an object at {path}:{line_number}")
            rows.append(payload)
    if not rows:
        raise ValueError("segment dataset contains no rows")
    return rows


def validate_segment_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    forbidden_evaluation_seeds: Sequence[int],
    min_target_std: float,
    min_high_complexity_candidate_rows: int,
    min_high_complexity_snapshot_groups: int,
) -> None:
    row_types = Counter(str(row.get("row_type")) for row in rows)
    for row_type in ("candidate", "entry", "exit"):
        if row_types.get(row_type, 0) <= 0:
            raise ValueError(f"segment dataset missing {row_type} rows")

    seeds = {int(row.get("seed", 0)) for row in rows}
    overlap = seeds.intersection(forbidden_evaluation_seeds)
    if overlap:
        raise ValueError(
            "segment training seed(s) overlap forbidden evaluation seed(s): "
            + ", ".join(str(seed) for seed in sorted(overlap))
        )

    candidate_rows = [row for row in rows if row.get("row_type") == "candidate"]
    entry_rows = [row for row in rows if row.get("row_type") == "entry"]
    exit_rows = [row for row in rows if row.get("row_type") == "exit"]
    if len(candidate_rows) < min_high_complexity_candidate_rows:
        raise ValueError(
            "segment dataset has insufficient high-complexity candidate rows: "
            f"{len(candidate_rows)} < {min_high_complexity_candidate_rows}"
        )
    high_groups = {
        str(row.get("snapshot_group"))
        for row in entry_rows
        if str(row.get("complexity_bucket")) == "high"
    }
    if len(high_groups) < min_high_complexity_snapshot_groups:
        raise ValueError(
            "segment dataset has insufficient high-complexity snapshot groups: "
            f"{len(high_groups)} < {min_high_complexity_snapshot_groups}"
        )

    for row_type, typed_rows, label in (
        ("entry", entry_rows, "enter_ml_segment"),
        ("exit", exit_rows, "exit_segment_to_a3"),
    ):
        values = {int(row.get(label, 0)) for row in typed_rows}
        if values != {0, 1}:
            raise ValueError(f"segment {row_type} labels need both classes")

    targets = np.asarray(
        [float(row["segment_utility_margin_vs_stay"]) for row in candidate_rows],
        dtype=float,
    )
    if not np.all(np.isfinite(targets)):
        raise ValueError("segment candidate targets must be finite")
    if float(np.std(targets)) <= min_target_std:
        raise ValueError("segment candidate target is constant or near-constant")


def grouped_split(
    rows: Sequence[Mapping[str, Any]],
    *,
    validation_split: float,
    seed: int,
) -> tuple[list[int], list[int], dict[str, Any]]:
    groups = sorted({_training_group_key(row) for row in rows})
    if len(groups) < 2:
        raise ValueError("segment validation requires at least two groups")
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
        if _training_group_key(row) in validation_groups:
            validation_indices.append(index)
        else:
            train_indices.append(index)
    if not train_indices or not validation_indices:
        raise ValueError("segment grouped split produced an empty train/validation set")
    return train_indices, validation_indices, {
        "group_count": len(groups),
        "train_group_count": len(groups) - len(validation_groups),
        "validation_group_count": len(validation_groups),
        "train_row_count": len(train_indices),
        "validation_row_count": len(validation_indices),
        "validation_split": validation_split,
        "split_seed": seed,
        "grouping": _grouping_name(rows[0]),
    }


def _training_group_key(row: Mapping[str, Any]) -> str:
    """Return the leakage boundary for segment model validation splits."""
    row_type = str(row.get("row_type") or "")
    if row_type == "exit":
        key = row.get("segment_group")
        if not key:
            raise ValueError("exit rows require segment_group for grouped validation")
        return f"segment:{key}"
    key = row.get("snapshot_group")
    if key:
        return f"snapshot:{key}"
    scenario, seed, ue_id, step = segment_group_key(row)
    return f"snapshot:{scenario}:{seed}:{ue_id}:{step}"


def _grouping_name(row: Mapping[str, Any]) -> str:
    return "segment_group" if str(row.get("row_type") or "") == "exit" else "snapshot_group"


def train_segment_controller_artifact(args: argparse.Namespace) -> dict[str, Any]:
    dataset_path = Path(args.dataset)
    output_artifact = Path(args.output_artifact)
    manifest_path = Path(args.dataset_manifest) if args.dataset_manifest else Path(
        f"{dataset_path}.manifest.json"
    )
    if output_artifact.exists() and not args.overwrite:
        raise ValueError(f"segment artifact already exists: {output_artifact}")
    meta_path = Path(f"{output_artifact}.meta.json")
    report_path = Path(f"{output_artifact}.training_report.json")
    for path in (meta_path, report_path):
        if path.exists() and not args.overwrite:
            raise ValueError(f"segment output already exists: {path}")

    rows = read_segment_jsonl(dataset_path)
    validate_segment_rows(
        rows,
        forbidden_evaluation_seeds=parse_seed_list(args.forbid_evaluation_seed),
        min_target_std=args.min_target_std,
        min_high_complexity_candidate_rows=args.min_high_complexity_candidate_rows,
        min_high_complexity_snapshot_groups=args.min_high_complexity_snapshot_groups,
    )
    feature_columns = select_feature_columns_by_type(rows)
    leaked = sorted(
        {"ue_id", "serving_cell", "candidate_cell"}.intersection(
            set(feature_columns["candidate"])
            | set(feature_columns["entry"])
            | set(feature_columns["exit"])
        )
    )
    if leaked:
        raise ValueError("segment feature columns include raw IDs: " + ", ".join(leaked))

    candidate_model, candidate_metrics, candidate_split = _train_candidate_stage(
        [row for row in rows if row.get("row_type") == "candidate"],
        feature_columns=feature_columns["candidate"],
        args=args,
    )
    entry_model, entry_metrics, entry_split = _train_classifier_stage(
        [row for row in rows if row.get("row_type") == "entry"],
        feature_columns=feature_columns["entry"],
        label="enter_ml_segment",
        stage_name="entry",
        args=args,
    )
    exit_model, exit_metrics, exit_split = _train_classifier_stage(
        [row for row in rows if row.get("row_type") == "exit"],
        feature_columns=feature_columns["exit"],
        label="exit_segment_to_a3",
        stage_name="exit",
        args=args,
    )

    if candidate_metrics["target_selection_error"] > args.max_target_selection_error:
        raise ValueError(
            "segment candidate target-selection error is too high: "
            f"{candidate_metrics['target_selection_error']:.4f} > "
            f"{args.max_target_selection_error:.4f}"
        )
    if entry_metrics["validation_precision"] < args.min_entry_precision:
        raise ValueError(
            "segment entry precision is too low: "
            f"{entry_metrics['validation_precision']:.4f} < "
            f"{args.min_entry_precision:.4f}"
        )
    if exit_metrics["validation_precision"] < args.min_exit_precision:
        raise ValueError(
            "segment exit precision is too low: "
            f"{exit_metrics['validation_precision']:.4f} < "
            f"{args.min_exit_precision:.4f}"
        )

    dataset_manifest: dict[str, Any] = {}
    if manifest_path.is_file():
        loaded_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if isinstance(loaded_manifest, dict):
            dataset_manifest = loaded_manifest

    decision_parameters = dict(DEFAULT_SEGMENT_DECISION_PARAMETERS)
    decision_parameters.update(
        {
            "entry_threshold": float(args.default_entry_threshold),
            "candidate_margin_min": float(args.default_candidate_margin_min),
            "exit_threshold": float(args.default_exit_threshold),
            "consecutive_exit_votes": float(args.default_consecutive_exit_votes),
            "min_segment_duration_s": float(args.default_min_segment_duration_s),
            "max_segment_duration_s": float(args.default_max_segment_duration_s),
            "emergency_rsrp_floor_dbm": float(args.default_emergency_rsrp_floor_dbm),
            "post_exit_a3_guard_s": float(
                getattr(args, "default_post_exit_a3_guard_s", 0.0)
            ),
            "post_exit_a3_extra_margin_db": float(
                getattr(args, "default_post_exit_a3_extra_margin_db", 0.0)
            ),
            "high_reject_hold_s": float(
                getattr(args, "default_high_reject_hold_s", 0.0)
            ),
        }
    )
    row_type_counts = Counter(str(row.get("row_type")) for row in rows)
    metadata = {
        "model_type": SEGMENT_CONTROLLER_MODEL_TYPE,
        "model_family": SEGMENT_CONTROLLER_MODEL_FAMILY,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "training_data_source": {
            "dataset": str(dataset_path),
            "dataset_manifest": str(manifest_path) if manifest_path.is_file() else None,
            "dataset_sha256": sha256_file(dataset_path),
            "trace_hashes": dataset_manifest.get("trace_hashes", {}),
        },
        "calibration_seeds": sorted({int(row.get("seed", 0)) for row in rows}),
        "forbidden_evaluation_seeds": parse_seed_list(args.forbid_evaluation_seed),
        "scenarios": sorted({str(row.get("scenario") or "") for row in rows}),
        "topology_hash": dataset_manifest.get("topology_hash"),
        "dataset_size": len(rows),
        "row_type_counts": dict(sorted(row_type_counts.items())),
        "feature_columns": feature_columns,
        "excluded_raw_id_columns": ["ue_id", "serving_cell", "candidate_cell"],
        "targets": {
            "candidate": "segment_utility_margin_vs_stay",
            "entry": "enter_ml_segment",
            "exit": "exit_segment_to_a3",
        },
        "validation_metrics": {
            "candidate": candidate_metrics,
            "entry": entry_metrics,
            "exit": exit_metrics,
        },
        "grouped_split": {
            "candidate": candidate_split,
            "entry": entry_split,
            "exit": exit_split,
        },
        "segment_decision_parameters": decision_parameters,
        "git_commit": git_commit(),
        "label_policy": dataset_manifest.get("label_policy", {}),
        "trace_hashes": dataset_manifest.get("trace_hashes", {}),
        "trace_complexity_summaries": dataset_manifest.get(
            "trace_complexity_summaries",
            [],
        ),
        "high_complexity_snapshot_count": dataset_manifest.get(
            "high_complexity_snapshot_count",
        ),
        "high_complexity_candidate_row_count": dataset_manifest.get(
            "high_complexity_candidate_row_count",
        ),
        "segment_entry_label_distribution": dataset_manifest.get(
            "segment_entry_label_distribution",
            {},
        ),
        "segment_exit_label_distribution": dataset_manifest.get(
            "segment_exit_label_distribution",
            {},
        ),
    }

    output_artifact.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "models": {
                "candidate": candidate_model,
                "entry": entry_model,
                "exit": exit_model,
            },
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
        "training_metrics": metadata["validation_metrics"],
        "metadata": metadata,
    }
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return report


def _train_candidate_stage(
    rows: Sequence[Mapping[str, Any]],
    *,
    feature_columns: Sequence[str],
    args: argparse.Namespace,
) -> tuple[Any, dict[str, Any], dict[str, Any]]:
    train_indices, validation_indices, split_report = grouped_split(
        rows,
        validation_split=args.validation_split,
        seed=args.seed,
    )
    x = np.asarray(
        [
            row_to_segment_feature_vector(row, feature_columns=feature_columns)
            for row in rows
        ],
        dtype=float,
    )
    y = np.asarray(
        [float(row["segment_utility_margin_vs_stay"]) for row in rows],
        dtype=float,
    )
    model = lgb.LGBMRegressor(
        n_estimators=args.n_estimators,
        learning_rate=args.learning_rate,
        max_depth=args.max_depth,
        num_leaves=args.num_leaves,
        min_child_samples=args.min_child_samples,
        random_state=args.seed,
        verbose=-1,
    )
    model.fit(x[train_indices], y[train_indices])
    validation_predictions = np.asarray(model.predict(x[validation_indices]), dtype=float)
    train_predictions = np.asarray(model.predict(x[train_indices]), dtype=float)
    if float(np.std(validation_predictions)) <= args.min_prediction_std:
        raise ValueError("segment candidate model predictions are constant")
    metrics = {
        "validation_mae": float(
            mean_absolute_error(y[validation_indices], validation_predictions)
        ),
        "validation_prediction_std": float(np.std(validation_predictions)),
        "train_prediction_std": float(np.std(train_predictions)),
        "target_std": float(np.std(y)),
        "target_selection_error": _target_selection_error(
            [rows[index] for index in validation_indices],
            validation_predictions,
        ),
    }
    return model, metrics, split_report


def _train_classifier_stage(
    rows: Sequence[Mapping[str, Any]],
    *,
    feature_columns: Sequence[str],
    label: str,
    stage_name: str,
    args: argparse.Namespace,
) -> tuple[Any, dict[str, Any], dict[str, Any]]:
    train_indices, validation_indices, split_report = grouped_split(
        rows,
        validation_split=args.validation_split,
        seed=args.seed,
    )
    x = np.asarray(
        [
            row_to_segment_feature_vector(row, feature_columns=feature_columns)
            for row in rows
        ],
        dtype=float,
    )
    y = np.asarray([int(row[label]) for row in rows], dtype=int)
    if set(y.tolist()) != {0, 1}:
        raise ValueError(f"segment {stage_name} labels must contain both classes")
    model = lgb.LGBMClassifier(
        n_estimators=args.n_estimators,
        learning_rate=args.learning_rate,
        max_depth=args.max_depth,
        num_leaves=args.num_leaves,
        min_child_samples=args.min_child_samples,
        random_state=args.seed,
        verbose=-1,
    )
    model.fit(x[train_indices], y[train_indices])
    probabilities = np.asarray(model.predict_proba(x[validation_indices]), dtype=float)
    if probabilities.ndim != 2 or probabilities.shape[1] < 2:
        raise ValueError(f"segment {stage_name} classifier produced invalid probabilities")
    positive_scores = probabilities[:, 1]
    if float(np.std(positive_scores)) <= args.min_prediction_std:
        raise ValueError(f"segment {stage_name} predictions are constant")
    predictions = (positive_scores >= 0.5).astype(int)
    y_val = y[validation_indices]
    precision = float(precision_score(y_val, predictions, zero_division=0))
    metrics = {
        "validation_precision": precision,
        "validation_positive_rate": float(np.mean(predictions)),
        "validation_label_positive_rate": float(np.mean(y_val)),
        "validation_prediction_std": float(np.std(positive_scores)),
    }
    return model, metrics, split_report


def _target_selection_error(
    validation_rows: Sequence[Mapping[str, Any]],
    predictions: Sequence[float],
) -> float:
    grouped: dict[tuple[str, int, str, int], list[tuple[Mapping[str, Any], float]]] = {}
    for row, prediction in zip(validation_rows, predictions):
        grouped.setdefault(segment_group_key(row), []).append((row, float(prediction)))
    if not grouped:
        raise ValueError("cannot compute target-selection error without groups")
    errors = 0
    evaluated = 0
    for items in grouped.values():
        positives = [row for row, _ in items if int(row.get("selected_label", 0)) == 1]
        if not positives:
            continue
        predicted_row, _score = max(items, key=lambda item: (item[1], str(item[0].get("candidate_cell"))))
        evaluated += 1
        if int(predicted_row.get("selected_label", 0)) != 1:
            errors += 1
    if evaluated == 0:
        raise ValueError("validation split contains no positive target-selection groups")
    return float(errors / evaluated)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument("--dataset", required=True, help="Segment dataset JSONL.")
    parser.add_argument("--dataset-manifest", help="Segment dataset manifest JSON.")
    parser.add_argument("--output-artifact", required=True, help="Output .joblib path.")
    parser.add_argument(
        "--forbid-evaluation-seed",
        default="61,62,63,64,65",
        help="Comma-separated evaluation seeds forbidden in training data.",
    )
    parser.add_argument("--validation-split", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=20260612)
    parser.add_argument("--n-estimators", type=int, default=200)
    parser.add_argument("--learning-rate", type=float, default=0.05)
    parser.add_argument("--max-depth", type=int, default=-1)
    parser.add_argument("--num-leaves", type=int, default=31)
    parser.add_argument("--min-child-samples", type=int, default=20)
    parser.add_argument("--min-target-std", type=float, default=1e-6)
    parser.add_argument("--min-prediction-std", type=float, default=1e-8)
    parser.add_argument(
        "--max-target-selection-error",
        type=float,
        default=0.35,
    )
    parser.add_argument("--min-entry-precision", type=float, default=0.75)
    parser.add_argument("--min-exit-precision", type=float, default=0.75)
    parser.add_argument(
        "--min-high-complexity-candidate-rows",
        type=int,
        default=DEFAULT_MIN_HIGH_COMPLEXITY_CANDIDATE_ROWS,
    )
    parser.add_argument(
        "--min-high-complexity-snapshot-groups",
        type=int,
        default=DEFAULT_MIN_HIGH_COMPLEXITY_SNAPSHOT_GROUPS,
    )
    parser.add_argument("--default-entry-threshold", type=float, default=0.5)
    parser.add_argument("--default-candidate-margin-min", type=float, default=20.0)
    parser.add_argument("--default-exit-threshold", type=float, default=0.7)
    parser.add_argument("--default-consecutive-exit-votes", type=int, default=3)
    parser.add_argument("--default-min-segment-duration-s", type=float, default=6.0)
    parser.add_argument("--default-max-segment-duration-s", type=float, default=45.0)
    parser.add_argument("--default-emergency-rsrp-floor-dbm", type=float, default=-112.0)
    parser.add_argument("--default-post-exit-a3-guard-s", type=float, default=0.0)
    parser.add_argument("--default-post-exit-a3-extra-margin-db", type=float, default=0.0)
    parser.add_argument("--default-high-reject-hold-s", type=float, default=0.0)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        report = train_segment_controller_artifact(args)
    except Exception as exc:  # noqa: BLE001 - command should fail visibly
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
