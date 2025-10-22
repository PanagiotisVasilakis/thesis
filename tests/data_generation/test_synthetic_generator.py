"""Unit tests for the synthetic QoS request generator."""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.data_generation.synthetic_generator import (
    SERVICE_PROFILES,
    SERVICE_MIX_PROFILES,
    generate_synthetic_requests,
    get_service_mix,
)

SCRIPT_PATH = REPO_ROOT / "scripts" / "data_generation" / "synthetic_generator.py"


@pytest.mark.parametrize("profile", sorted(SERVICE_MIX_PROFILES))
def test_generate_synthetic_requests_contains_required_fields(profile: str) -> None:
    records = generate_synthetic_requests(25, profile=profile, seed=1234)
    assert len(records) == 25

    for idx, record in enumerate(records):
        assert set(record) == {
            "request_id",
            "service_type",
            "latency_ms",
            "reliability_pct",
            "throughput_mbps",
            "priority",
        }
        assert record["service_type"] in SERVICE_PROFILES
        assert record["priority"] >= 0
        assert record["latency_ms"] > 0
        assert 0 <= record["throughput_mbps"]
        assert 90.0 <= record["reliability_pct"] <= 100.0
        assert record["request_id"].startswith("req_")
        assert record["request_id"].endswith(f"{idx:06d}")


@pytest.mark.parametrize(
    "profile, expected_service, min_ratio",
    [
        ("embb-heavy", "embb", 0.5),
        ("urllc-heavy", "urllc", 0.5),
        ("mmtc-heavy", "mmtc", 0.5),
    ],
)
def test_service_mix_profiles_bias_distribution(
    profile: str, expected_service: str, min_ratio: float
) -> None:
    records = generate_synthetic_requests(2000, profile=profile, seed=99)
    counts = Counter(record["service_type"] for record in records)
    ratio = counts[expected_service] / len(records)
    assert ratio >= min_ratio * 0.85

    balanced_records = generate_synthetic_requests(2000, profile="balanced", seed=101)
    balanced_counts = Counter(record["service_type"] for record in balanced_records)
    balanced_ratio = balanced_counts[expected_service] / len(balanced_records)
    assert ratio > balanced_ratio


@pytest.mark.parametrize("output_format", ["csv", "json"])
def test_cli_generates_dataset(tmp_path: Path, output_format: str) -> None:
    output_path = tmp_path / f"synthetic.{output_format}"
    cmd = [
        sys.executable,
        str(SCRIPT_PATH),
        "--records",
        "50",
        "--profile",
        "urllc-heavy",
        "--seed",
        "7",
        "--output",
        str(output_path),
        "--format",
        output_format,
    ]

    subprocess.run(cmd, check=True, capture_output=True, text=True)
    assert output_path.exists()

    if output_format == "csv":
        with output_path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        assert len(rows) == 50
        assert set(row["service_type"] for row in rows).issubset(SERVICE_PROFILES)
    else:
        with output_path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        assert len(payload) == 50
        assert set(item["service_type"] for item in payload).issubset(SERVICE_PROFILES)


def test_get_service_mix_normalises_weights() -> None:
    mix = get_service_mix("balanced")
    assert pytest.approx(sum(mix.values()), abs=1e-9) == 1.0
    for service in SERVICE_PROFILES:
        assert service in mix
