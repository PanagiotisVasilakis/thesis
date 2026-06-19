#!/usr/bin/env python3
"""Train and compare linear utility and LambdaMART explicit-stay rankers."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import joblib
import lightgbm as lgb
import numpy as np
from sklearn.linear_model import Ridge
from sklearn.metrics import ndcg_score, precision_score, recall_score

from .oracle_ranker_artifact import MODEL_TYPE, sha256_file


def _read_rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _matrix(rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> np.ndarray:
    return np.asarray([[float(row[column]) for column in columns] for row in rows], dtype=float)


def _ordered_for_ranker(rows: Sequence[dict]) -> tuple[list[dict], list[int]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[str(row["snapshot_group"])].append(row)
    ordered: list[dict] = []
    groups: list[int] = []
    for key in sorted(grouped):
        items = grouped[key]
        ordered.extend(items)
        groups.append(len(items))
    return ordered, groups


def _train_models(rows: Sequence[dict], columns: Sequence[str], seed: int) -> dict[str, Any]:
    linear = Ridge(alpha=1.0)
    linear.fit(_matrix(rows, columns), np.asarray([row["oracle_utility"] for row in rows]))
    ordered, groups = _ordered_for_ranker(rows)
    ranker = lgb.LGBMRanker(
        objective="lambdarank",
        n_estimators=300,
        learning_rate=0.04,
        num_leaves=31,
        min_child_samples=30,
        random_state=seed,
        verbose=-1,
    )
    ranker.fit(
        _matrix(ordered, columns),
        np.asarray([int(row["relevance"]) for row in ordered]),
        group=groups,
    )
    return {"linear_utility": linear, "lightgbm_lambdarank": ranker}


def _evaluate(model: Any, rows: Sequence[dict], columns: Sequence[str]) -> dict[str, float]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[str(row["snapshot_group"])].append(row)
    regrets: list[float] = []
    correct: list[int] = []
    true_handover: list[int] = []
    predicted_handover: list[int] = []
    brier_values: list[float] = []
    ndcg_values: list[float] = []
    for items in grouped.values():
        scores = np.asarray(model.predict(_matrix(items, columns)), dtype=float)
        selected_index = int(np.argmax(scores))
        true_index = next(index for index, row in enumerate(items) if row["selected_label"] == 1)
        regrets.append(float(items[selected_index]["oracle_regret"]))
        correct.append(int(selected_index == true_index))
        true_handover.append(int(items[true_index]["action_is_stay"] == 0.0))
        predicted_handover.append(int(items[selected_index]["action_is_stay"] == 0.0))
        shifted = scores - float(np.max(scores))
        probabilities = np.exp(np.clip(shifted, -50.0, 0.0))
        probabilities /= max(float(np.sum(probabilities)), 1e-12)
        stay_probability = sum(
            probabilities[index]
            for index, row in enumerate(items)
            if row["action_is_stay"] == 1.0
        )
        brier_values.append((1.0 - stay_probability - true_handover[-1]) ** 2)
        if len(items) == 1:
            ndcg_values.append(1.0)
        else:
            relevance = np.asarray([[float(row["relevance"]) for row in items]])
            ndcg_values.append(
                float(
                    ndcg_score(
                        relevance,
                        scores.reshape(1, -1),
                        k=min(5, len(items)),
                    )
                )
            )
    return {
        "mean_oracle_regret": float(np.mean(regrets)),
        "top_action_accuracy": float(np.mean(correct)),
        "ndcg_at_5": float(np.mean(ndcg_values)),
        "handover_precision": float(precision_score(true_handover, predicted_handover, zero_division=0)),
        "handover_recall": float(recall_score(true_handover, predicted_handover, zero_division=0)),
        "handover_brier_score": float(np.mean(brier_values)),
        "snapshot_count": float(len(grouped)),
    }


def train_ladder(
    dataset: Path,
    manifest_path: Path,
    output: Path,
    *,
    seed: int = 20260619,
) -> dict:
    rows = _read_rows(dataset)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    columns = [str(item) for item in manifest["feature_columns"]]
    if {"ue_id", "serving_cell", "action_cell"}.intersection(columns):
        raise ValueError("raw IDs are forbidden model features")
    seeds = sorted({int(row["seed"]) for row in rows})
    if len(seeds) < 2:
        raise ValueError("trajectory-safe validation requires at least two training seeds")

    fold_metrics: dict[str, list[dict]] = defaultdict(list)
    for held_out_seed in seeds:
        train_rows = [row for row in rows if int(row["seed"]) != held_out_seed]
        validation_rows = [row for row in rows if int(row["seed"]) == held_out_seed]
        models = _train_models(train_rows, columns, seed)
        for family, model in models.items():
            fold_metrics[family].append(
                {"held_out_seed": held_out_seed, **_evaluate(model, validation_rows, columns)}
            )

    aggregate: dict[str, dict[str, float]] = {}
    for family, folds in fold_metrics.items():
        aggregate[family] = {
            key: float(np.mean([fold[key] for fold in folds]))
            for key in (
                "mean_oracle_regret", "top_action_accuracy", "ndcg_at_5",
                "handover_precision", "handover_recall", "handover_brier_score",
            )
        }
    selected_family = min(
        aggregate,
        key=lambda family: (
            aggregate[family]["mean_oracle_regret"],
            -aggregate[family]["top_action_accuracy"],
        ),
    )
    final_models = _train_models(rows, columns, seed)
    output.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {"selected_model": final_models[selected_family], "candidate_models": final_models},
        output,
    )
    metadata = {
        "model_type": MODEL_TYPE,
        "model_family": "explicit_stay_cost_to_go_ranker",
        "selected_model_family": selected_family,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "feature_columns": columns,
        "training_seeds": seeds,
        "forbidden_evaluation_seeds": manifest.get("forbidden_evaluation_seeds", []),
        "dataset_sha256": sha256_file(dataset),
        "trace_hashes": manifest.get("trace_hashes", {}),
        "label_policy": manifest.get("label_policy"),
        "validation_split": "leave_one_seed_out_complete_trajectories",
        "leave_one_seed_out_metrics": dict(fold_metrics),
        "aggregate_validation_metrics": aggregate,
        "selected_min_utility_margin": 0.0,
        "model_c": {
            "minimum_snapshot_count": 100000,
            "eligible": manifest.get("snapshot_group_count", 0) >= 100000,
            "trained": False,
            "reason": "only eligible after LambdaMART fails replay calibration",
        },
        "git_commit": subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False
        ).stdout.strip() or None,
    }
    metadata["model_sha256"] = sha256_file(output)
    Path(f"{output}.meta.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8"
    )
    return metadata


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-artifact", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260619)
    args = parser.parse_args(argv)
    try:
        report = train_ladder(args.dataset, args.manifest, args.output_artifact, seed=args.seed)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
