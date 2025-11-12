"""Validate synthetic training dataset balance and coverage."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict

from _common import ensure_logging, write_json
from ml_service.app.utils.synthetic_data import (
    generate_synthetic_training_data,
    validate_training_data,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument(
        "--num-samples",
        type=int,
        default=2000,
        help="Number of synthetic samples to generate",
    )
    parser.add_argument(
        "--num-antennas",
        type=int,
        default=4,
        help="Number of antennas represented in the dataset",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Optional RNG seed for reproducibility",
    )
    parser.add_argument(
        "--balance-classes",
        action="store_true",
        help="Generate a balanced dataset by enforcing equal class assignments",
    )
    parser.add_argument(
        "--edge-case-ratio",
        type=float,
        default=0.25,
        help="Fraction of samples to place near cell boundaries when balancing",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("diagnostics/training_data_validation.json"),
        help="Path to write the validation report",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ensure_logging(args.verbose)

    samples = generate_synthetic_training_data(
        num_samples=args.num_samples,
        num_antennas=args.num_antennas,
        seed=args.seed,
        balance_classes=args.balance_classes,
        edge_case_ratio=args.edge_case_ratio,
    )

    report: Dict[str, Any] = validate_training_data(samples)
    report["num_samples"] = args.num_samples
    report["num_antennas"] = args.num_antennas
    report["seed"] = args.seed
    report["balance_classes"] = args.balance_classes
    report["edge_case_ratio"] = args.edge_case_ratio

    write_json(args.output, report)
    imbalance = report.get("imbalance_ratio", float("inf"))
    print(
        "Validation complete -> imbalance ratio:",
        f"{imbalance:.2f} (1.0 means perfectly balanced)",
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
