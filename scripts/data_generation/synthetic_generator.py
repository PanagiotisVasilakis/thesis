"""Synthetic QoS request generator for 5G service classes.

The generator produces synthetic service requests enriched with QoS fields
required by downstream experimentation pipelines.  It supports three
3GPP-aligned service classes (eMBB, URLLC, mMTC) plus a ``default`` catch-all
profile.  Each profile models latency, throughput, reliability and priority
using lightweight triangular distributions that keep values within realistic
ranges while biasing towards expected operating points.

The module can be imported from tests or executed directly as a CLI utility.  A
``--profile`` flag exposes pre-defined service mixes (balanced, eMBB-heavy,
etc.) so experimenters can quickly adjust demand scenarios without memorising
weight vectors.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Mapping, Sequence

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ServiceProfile:
    """Configuration describing how to sample QoS metrics for a service class."""

    service_type: str
    latency_ms: tuple[float, float]
    latency_mode: float
    reliability_pct: tuple[float, float]
    reliability_mode: float
    throughput_mbps: tuple[float, float]
    throughput_mode: float
    priority: tuple[int, int]

    def sample(self, rng: random.Random, *, request_id: str) -> Dict[str, object]:
        """Sample QoS metrics using triangular distributions.

        Triangular distributions keep sampling bounded while favouring the
        ``*_mode`` values that represent typical behaviour for each service.
        ``random.triangular`` already clamps results to the provided range, so
        only minimal additional handling is required.
        """

        latency = rng.triangular(
            self.latency_ms[0], self.latency_ms[1], self.latency_mode
        )
        reliability = rng.triangular(
            self.reliability_pct[0], self.reliability_pct[1], self.reliability_mode
        )
        throughput = rng.triangular(
            self.throughput_mbps[0], self.throughput_mbps[1], self.throughput_mode
        )
        priority = rng.randint(self.priority[0], self.priority[1])

        return {
            "request_id": request_id,
            "service_type": self.service_type,
            "latency_ms": round(latency, 3),
            "reliability_pct": round(reliability, 5),
            "throughput_mbps": round(throughput, 3),
            "priority": priority,
        }


SERVICE_PROFILES: Dict[str, ServiceProfile] = {
    "urllc": ServiceProfile(
        service_type="urllc",
        latency_ms=(1.0, 10.0),
        latency_mode=2.0,
        reliability_pct=(99.95, 99.999),
        reliability_mode=99.995,
        throughput_mbps=(0.5, 5.0),
        throughput_mode=1.5,
        priority=(9, 10),
    ),
    "embb": ServiceProfile(
        service_type="embb",
        latency_ms=(20.0, 80.0),
        latency_mode=45.0,
        reliability_pct=(98.5, 99.9),
        reliability_mode=99.4,
        throughput_mbps=(50.0, 350.0),
        throughput_mode=200.0,
        priority=(6, 9),
    ),
    "mmtc": ServiceProfile(
        service_type="mmtc",
        latency_ms=(100.0, 1000.0),
        latency_mode=600.0,
        reliability_pct=(94.0, 98.5),
        reliability_mode=96.0,
        throughput_mbps=(0.01, 1.0),
        throughput_mode=0.2,
        priority=(2, 4),
    ),
    "default": ServiceProfile(
        service_type="default",
        latency_ms=(30.0, 200.0),
        latency_mode=80.0,
        reliability_pct=(95.0, 99.0),
        reliability_mode=97.5,
        throughput_mbps=(5.0, 80.0),
        throughput_mode=25.0,
        priority=(4, 6),
    ),
}

# Service mix presets prioritise clarity over configurability.  Ratios sum to 1.0
# and cover common simulation scenarios for QoS experiments.
SERVICE_MIX_PROFILES: Dict[str, Mapping[str, float]] = {
    "balanced": {
        "urllc": 0.25,
        "embb": 0.35,
        "mmtc": 0.25,
        "default": 0.15,
    },
    "embb-heavy": {
        "urllc": 0.1,
        "embb": 0.6,
        "mmtc": 0.15,
        "default": 0.15,
    },
    "urllc-heavy": {
        "urllc": 0.6,
        "embb": 0.2,
        "mmtc": 0.1,
        "default": 0.1,
    },
    "mmtc-heavy": {
        "urllc": 0.1,
        "embb": 0.2,
        "mmtc": 0.6,
        "default": 0.1,
    },
    "uniform": {
        "urllc": 0.25,
        "embb": 0.25,
        "mmtc": 0.25,
        "default": 0.25,
    },
}


def get_service_mix(profile: str) -> Dict[str, float]:
    """Return a normalized weight map for the requested mix profile."""

    if profile not in SERVICE_MIX_PROFILES:
        raise ValueError(
            f"Unknown service mix profile '{profile}'. Available options: "
            f"{', '.join(sorted(SERVICE_MIX_PROFILES))}"
        )

    mix = dict(SERVICE_MIX_PROFILES[profile])

    # Ensure every service type is represented even if a mix omits it.
    for service in SERVICE_PROFILES:
        mix.setdefault(service, 0.0)

    total = sum(mix.values())
    if total <= 0:
        raise ValueError(f"Invalid mix definition for profile '{profile}': sum is {total}")

    return {service: weight / total for service, weight in mix.items()}


def _choose_service_type(rng: random.Random, weights: Mapping[str, float]) -> str:
    """Sample a service type using cumulative weight selection."""

    cumulative = 0.0
    target = rng.random()
    for service, weight in weights.items():
        cumulative += weight
        if target <= cumulative:
            return service
    # Numerical errors can leave a remainder close to zero.
    return next(reversed(weights))


def generate_synthetic_requests(
    num_records: int,
    *,
    profile: str = "balanced",
    seed: int | None = None,
) -> List[Dict[str, object]]:
    """Generate synthetic QoS requests.

    Args:
        num_records: Number of records to emit. Must be non-negative.
        profile: Named service mix profile from :data:`SERVICE_MIX_PROFILES`.
        seed: Optional deterministic seed for reproducibility.
    """

    if num_records < 0:
        raise ValueError("num_records must be non-negative")

    rng = random.Random(seed)
    mix = get_service_mix(profile)

    records: List[Dict[str, object]] = []
    for idx in range(num_records):
        svc = _choose_service_type(rng, mix)
        profile_cfg = SERVICE_PROFILES[svc]
        record = profile_cfg.sample(rng, request_id=f"req_{idx:06d}")
        records.append(record)

    return records


def _write_csv(path: Path, records: Sequence[Mapping[str, object]]) -> None:
    if not records:
        LOGGER.warning("No records generated; writing an empty CSV with headers")
        headers = [
            "request_id",
            "service_type",
            "latency_ms",
            "reliability_pct",
            "throughput_mbps",
            "priority",
        ]
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=headers)
            writer.writeheader()
        return

    headers = list(records[0].keys())
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=headers)
        writer.writeheader()
        writer.writerows(records)


def _write_json(path: Path, records: Sequence[Mapping[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        json.dump(records, fh, indent=2)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate synthetic QoS requests")
    parser.add_argument(
        "--records",
        type=int,
        default=1000,
        help="Number of records to generate (default: 1000)",
    )
    parser.add_argument(
        "--profile",
        choices=sorted(SERVICE_MIX_PROFILES.keys()),
        default="balanced",
        help="Preconfigured service mix profile",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Optional random seed for reproducible datasets",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Destination file. If omitted, the dataset is printed to stdout",
    )
    parser.add_argument(
        "--format",
        choices=("csv", "json"),
        default="csv",
        help="Serialization format for the generated dataset",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    records = generate_synthetic_requests(
        args.records, profile=args.profile, seed=args.seed
    )

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if args.format == "csv":
            _write_csv(args.output, records)
        else:
            _write_json(args.output, records)
        LOGGER.info("Wrote %s records to %s", len(records), args.output)
    else:
        if args.format == "json":
            print(json.dumps(records, indent=2))
        else:
            fieldnames = (
                list(records[0].keys())
                if records
                else [
                    "request_id",
                    "service_type",
                    "latency_ms",
                    "reliability_pct",
                    "throughput_mbps",
                    "priority",
                ]
            )
            writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(records)

    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via CLI test
    raise SystemExit(main())
