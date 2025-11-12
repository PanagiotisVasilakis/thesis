"""Inspect training data for class balance and spatial coverage."""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Mapping

from _common import (
    describe_numeric_feature,
    ensure_logging,
    generate_synthetic_samples,
    summarise_class_distribution,
    write_json,
)

TARGET_FIELD = "optimal_antenna"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="Optional CSV dataset to inspect. When omitted, synthetic data is generated.",
    )
    parser.add_argument(
        "--synthetic-samples",
        type=int,
        default=500,
        help="Number of synthetic samples to generate when --input is not provided.",
    )
    parser.add_argument(
        "--num-antennas",
        type=int,
        default=4,
        help="Number of antennas represented in the synthetic dataset.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("diagnostics/training_data_report.json"),
        help="Where to write the analysis report.",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    return parser.parse_args()


def _load_csv(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader)


def _extract_field(sample: Mapping[str, str], key: str) -> float:
    value = sample.get(key)
    try:
        return float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def load_dataset(args: argparse.Namespace) -> List[Mapping[str, object]]:
    if args.input:
        rows = _load_csv(args.input)
        return rows
    return generate_synthetic_samples(args.synthetic_samples, num_antennas=args.num_antennas)


def build_report(dataset: Iterable[Mapping[str, object]]) -> Dict[str, object]:
    labels: List[str] = []
    latitudes: List[float] = []
    longitudes: List[float] = []
    per_class_lat: Dict[str, List[float]] = defaultdict(list)
    per_class_lon: Dict[str, List[float]] = defaultdict(list)
    service_types: List[str] = []

    for sample in dataset:
        label = str(sample.get(TARGET_FIELD, "unknown"))
        labels.append(label)

        lat = float(sample.get("latitude", 0.0))
        lon = float(sample.get("longitude", 0.0))
        latitudes.append(lat)
        longitudes.append(lon)
        per_class_lat[label].append(lat)
        per_class_lon[label].append(lon)

        service_type = sample.get("service_type")
        if service_type is not None:
            service_types.append(str(service_type))

    report = summarise_class_distribution(labels)
    report["latitude"] = describe_numeric_feature(latitudes)
    report["longitude"] = describe_numeric_feature(longitudes)

    per_class = {}
    for label in per_class_lat:
        per_class[label] = {
            "latitude": describe_numeric_feature(per_class_lat[label]),
            "longitude": describe_numeric_feature(per_class_lon[label]),
        }
    report["per_class_spatial"] = per_class

    if service_types:
        service_counts = summarise_class_distribution(service_types)
        report["service_type_distribution"] = service_counts["class_distribution"]

    return report


def main() -> int:
    args = parse_args()
    ensure_logging(args.verbose)

    dataset = load_dataset(args)
    report = build_report(dataset)
    write_json(args.output, report)

    imbalance = report.get("imbalance_ratio", 0.0)
    print(
        "Training data imbalance ratio:",
        f"{imbalance:.2f} (1.0 means perfectly balanced)",
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
