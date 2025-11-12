"""Evaluate feature importance using model and permutation metrics."""
from __future__ import annotations

import argparse
from collections import OrderedDict
from pathlib import Path
from typing import Dict, List

import numpy as np
from sklearn.inspection import permutation_importance

from _common import (
    ensure_logging,
    generate_synthetic_samples,
    load_selector,
    write_json,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument(
        "--model-path",
        type=Path,
        default=Path("output/test_model.joblib"),
        help="Path to the trained model artifact",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=1000,
        help="Number of synthetic samples to evaluate",
    )
    parser.add_argument(
        "--num-antennas",
        type=int,
        default=4,
        help="Number of antennas represented in the dataset",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=20,
        help="Number of leading features to include in the summary",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("diagnostics/feature_importance.json"),
        help="Where to write the analysis report",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    return parser.parse_args()


def build_feature_matrix(selector, samples: List[Dict[str, object]]):
    feature_names = selector.feature_names
    X = []
    y = []
    for sample in samples:
        features = selector.extract_features(dict(sample))
        prepared = selector._prepare_features_for_model(features)  # noqa: SLF001 - controlled use for diagnostics
        selector._ensure_feature_defaults(prepared)  # noqa: SLF001
        row = [prepared[name] for name in feature_names]
        X.append(row)
        label = sample.get("optimal_antenna")
        if label is not None:
            y.append(label)
        else:
            y.append(sample.get("connected_to", "unknown"))
    return np.asarray(X, dtype=float), np.asarray(y, dtype=str), feature_names


def normalise_importance(values: Dict[str, float]) -> Dict[str, float]:
    total = float(sum(abs(v) for v in values.values()))
    if total == 0:
        return {k: 0.0 for k in values}
    return {k: abs(v) / total for k, v in values.items()}


def rank_features(scores: Dict[str, float], top_n: int) -> List[Dict[str, float]]:
    ordered = OrderedDict(
        sorted(scores.items(), key=lambda item: item[1], reverse=True)[:top_n]
    )
    return [
        {"feature": name, "score": float(score)} for name, score in ordered.items()
    ]


def main() -> int:
    args = parse_args()
    ensure_logging(args.verbose)

    selector = load_selector(args.model_path)
    samples = generate_synthetic_samples(args.samples, num_antennas=args.num_antennas)

    X, y, feature_names = build_feature_matrix(selector, samples)
    X_scaled = selector.scaler.transform(X) if selector.scaler is not None else X

    model_importance = dict(zip(feature_names, selector.model.feature_importances_))
    model_importance_norm = normalise_importance(model_importance)

    perm_result = permutation_importance(
        selector.model,
        X_scaled,
        y,
        n_repeats=10,
        random_state=42,
        scoring="accuracy",
    )
    perm_importance = dict(zip(feature_names, perm_result.importances_mean))
    perm_importance_norm = normalise_importance(perm_importance)

    report = {
        "model_path": str(args.model_path),
        "samples": len(samples),
        "top_features_model": rank_features(model_importance_norm, args.top_n),
        "top_features_permutation": rank_features(perm_importance_norm, args.top_n),
    }

    write_json(args.output, report)
    print(
        f"Feature importance analysis written to {args.output}. "
        f"Top feature: {report['top_features_model'][0]['feature']}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
