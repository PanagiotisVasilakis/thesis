"""Capture baseline metrics for the current ML handover system."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict

from _common import (
    compute_prediction_stats,
    describe_numeric_feature,
    ensure_logging,
    generate_synthetic_samples,
    get_cell_positions,
    load_selector,
    summarise_class_distribution,
    write_json,
)


def load_metadata(model_path: Path) -> Dict[str, object]:
    meta_path = model_path.with_suffix(model_path.suffix + ".meta.json")
    if not meta_path.exists():
        return {}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument(
        "--model-path",
        type=Path,
        default=Path("output/test_model.joblib"),
        help="Path to the trained model artifact",
    )
    parser.add_argument(
        "--test-samples",
        type=int,
        default=1000,
        help="Number of samples for prediction diagnostics",
    )
    parser.add_argument(
        "--training-samples",
        type=int,
        default=500,
        help="Number of samples for training data inspection",
    )
    parser.add_argument(
        "--num-antennas",
        type=int,
        default=4,
        help="Number of antennas represented in the diagnostics",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("diagnostics/baseline_metrics.json"),
        help="Where to write the combined metrics report",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ensure_logging(args.verbose)

    selector = load_selector(args.model_path)
    cell_positions = get_cell_positions(args.num_antennas)

    prediction_samples = generate_synthetic_samples(args.test_samples, num_antennas=args.num_antennas)
    prediction_stats = compute_prediction_stats(
        selector, prediction_samples, cell_positions=cell_positions
    )

    training_samples = generate_synthetic_samples(
        args.training_samples, num_antennas=args.num_antennas
    )
    labels = [str(item.get("optimal_antenna", "unknown")) for item in training_samples]
    class_summary = summarise_class_distribution(labels)
    lats = [float(item.get("latitude", 0.0)) for item in training_samples]
    lons = [float(item.get("longitude", 0.0)) for item in training_samples]

    report = {
        "model_path": str(args.model_path),
        "model_metadata": load_metadata(args.model_path),
        "feature_count": len(selector.feature_names),
        "prediction_stats": prediction_stats,
        "training_data": {
            "class_summary": class_summary,
            "latitude": describe_numeric_feature(lats),
            "longitude": describe_numeric_feature(lons),
        },
    }

    write_json(args.output, report)
    print(f"Baseline metrics captured in {args.output}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
