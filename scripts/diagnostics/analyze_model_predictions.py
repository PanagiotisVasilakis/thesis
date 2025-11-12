"""Analyze ML model prediction diversity and confidence distribution."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, Tuple

from _common import (
    compute_prediction_stats,
    ensure_logging,
    generate_synthetic_samples,
    get_cell_positions,
    load_selector,
    write_json,
)


def parse_cell_centers(raw: str, *, num_antennas: int) -> Dict[str, Tuple[float, float]]:
    parts = [chunk.strip() for chunk in raw.split(";") if chunk.strip()]
    if len(parts) != num_antennas:
        raise ValueError(
            f"Expected {num_antennas} coordinate pairs, received {len(parts)}"
        )
    positions: Dict[str, Tuple[float, float]] = {}
    for idx, item in enumerate(parts, start=1):
        lat_str, lon_str = [value.strip() for value in item.split(",", 1)]
        positions[f"antenna_{idx}"] = (float(lat_str), float(lon_str))
    return positions


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument(
        "--model-path",
        default=Path("output/test_model.joblib"),
        type=Path,
        help="Path to the trained model artifact",
    )
    parser.add_argument(
        "--test-samples",
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
        "--cell-centers",
        type=str,
        default=None,
        help=(
            "Optional semicolon separated latitude,longitude pairs for known "
            "antenna locations (e.g. '37.999,23.819;37.998,23.821')."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("diagnostics/model_diversity_report.json"),
        help="Where to write the analysis report",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ensure_logging(args.verbose)

    selector = load_selector(args.model_path)
    samples = generate_synthetic_samples(args.test_samples, num_antennas=args.num_antennas)

    if args.cell_centers:
        cell_positions = parse_cell_centers(args.cell_centers, num_antennas=args.num_antennas)
    else:
        cell_positions = get_cell_positions(args.num_antennas)

    stats = compute_prediction_stats(selector, samples, cell_positions=cell_positions)
    stats["model_path"] = str(args.model_path)
    stats["num_antennas"] = args.num_antennas

    write_json(args.output, stats)

    total = stats.get("total_samples", 0)
    unique = stats.get("unique_predictions", 0)
    diversity = stats.get("diversity_ratio", 0.0) * 100
    print(f"Analyzed {total} samples -> {unique} unique predictions ({diversity:.1f}% diversity)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
