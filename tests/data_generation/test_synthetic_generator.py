"""Unit tests for the synthetic QoS request generator."""
from __future__ import annotations

import csv
import json
import math
import random
import statistics
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Callable, Iterable, Mapping

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.data_generation.synthetic_generator import (
    SERVICE_PROFILES,
    SERVICE_MIX_PROFILES,
    ServiceProfile,
    _normalise_weight_map,
    generate_synthetic_requests,
    get_service_mix,
)

SCRIPT_PATH = REPO_ROOT / "scripts" / "data_generation" / "synthetic_generator.py"


@pytest.fixture(name="cli_runner")
def fixture_cli_runner() -> Callable[[Iterable[str], bool], subprocess.CompletedProcess[str]]:
    """Return a helper that executes the generator CLI.

    The helper captures stdout/stderr so tests can make precise assertions about
    validation errors without re-running the process.  ``expect_success``
    controls whether a non-zero exit code should fail the test immediately.
    """

    def _run_cli(args: Iterable[str], expect_success: bool = True) -> subprocess.CompletedProcess[str]:
        cmd = [sys.executable, str(SCRIPT_PATH), *args]
        completed = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
        )
        if expect_success and completed.returncode != 0:
            pytest.fail(
                "CLI invocation failed:\n"
                f"command: {' '.join(cmd)}\n"
                f"stdout:\n{completed.stdout}\n"
                f"stderr:\n{completed.stderr}"
            )
        return completed

    return _run_cli


def _triangular_mean(low: float, high: float, mode: float) -> float:
    return (low + high + mode) / 3.0


def _triangular_variance(low: float, high: float, mode: float) -> float:
    return (low**2 + high**2 + mode**2 - low * high - low * mode - high * mode) / 18.0


def _chi_squared_statistic(
    observed: Mapping[str, int], expected_weights: Mapping[str, float], sample_size: int
) -> float:
    statistic = 0.0
    for service, expected_weight in expected_weights.items():
        expected_count = expected_weight * sample_size
        if expected_count < 1e-9:
            # Weight rounding can leave a true zero weight for a category; ensure
            # the generator never sampled it.
            assert observed.get(service, 0) == 0
            continue
        statistic += (observed.get(service, 0) - expected_count) ** 2 / expected_count
    return statistic


@pytest.mark.parametrize("profile", sorted(SERVICE_MIX_PROFILES))
def test_generate_synthetic_requests_contains_required_fields(profile: str) -> None:
    records = generate_synthetic_requests(40, profile=profile, seed=1234)
    assert len(records) == 40

    for idx, record in enumerate(records):
        assert set(record) == {
            "request_id",
            "service_type",
            "latency_ms",
            "reliability_pct",
            "throughput_mbps",
            "priority",
        }

        service = record["service_type"]
        profile_cfg = SERVICE_PROFILES[service]
        assert profile_cfg.latency_ms[0] <= record["latency_ms"] <= profile_cfg.latency_ms[1]
        assert profile_cfg.reliability_pct[0] <= record["reliability_pct"] <= profile_cfg.reliability_pct[1]
        assert profile_cfg.throughput_mbps[0] <= record["throughput_mbps"] <= profile_cfg.throughput_mbps[1]
        assert profile_cfg.priority[0] <= record["priority"] <= profile_cfg.priority[1]

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
    records = generate_synthetic_requests(5000, profile=profile, seed=99)
    counts = Counter(record["service_type"] for record in records)
    ratio = counts[expected_service] / len(records)
    assert ratio >= min_ratio * 0.9

    balanced_records = generate_synthetic_requests(5000, profile="balanced", seed=101)
    balanced_counts = Counter(record["service_type"] for record in balanced_records)
    balanced_ratio = balanced_counts[expected_service] / len(balanced_records)
    assert ratio > balanced_ratio


@pytest.mark.parametrize("profile", sorted(SERVICE_MIX_PROFILES))
def test_service_mix_distributions_pass_chi_squared(profile: str) -> None:
    sample_size = 8000
    records = generate_synthetic_requests(sample_size, profile=profile, seed=2024)
    observed = Counter(record["service_type"] for record in records)

    chi_squared = _chi_squared_statistic(observed, get_service_mix(profile), sample_size)

    # Four service classes -> 3 degrees of freedom.
    critical_value = 7.90
    assert chi_squared < critical_value


@pytest.mark.parametrize("service_name", sorted(SERVICE_PROFILES))
def test_service_profile_sampling_matches_triangular_expectation(service_name: str) -> None:
    profile_cfg: ServiceProfile = SERVICE_PROFILES[service_name]
    rng = random.Random(42)
    sample_size = 6000
    latencies = []
    reliabilities = []
    throughputs = []
    priorities = []

    for idx in range(sample_size):
        record = profile_cfg.sample(rng, request_id=f"sample_{idx:06d}")
        latencies.append(record["latency_ms"])
        reliabilities.append(record["reliability_pct"])
        throughputs.append(record["throughput_mbps"])
        priorities.append(record["priority"])

    def assert_mean_within_ci(values: list[float], expected_mean: float, variance: float) -> None:
        sample_mean = statistics.fmean(values)
        standard_error = math.sqrt(max(variance, 1e-12) / len(values))
        tolerance = 2.8 * standard_error + 1e-3
        assert abs(sample_mean - expected_mean) <= tolerance

    assert_mean_within_ci(
        latencies,
        _triangular_mean(*profile_cfg.latency_ms, profile_cfg.latency_mode),
        _triangular_variance(*profile_cfg.latency_ms, profile_cfg.latency_mode),
    )
    assert_mean_within_ci(
        reliabilities,
        _triangular_mean(*profile_cfg.reliability_pct, profile_cfg.reliability_mode),
        _triangular_variance(*profile_cfg.reliability_pct, profile_cfg.reliability_mode),
    )
    assert_mean_within_ci(
        throughputs,
        _triangular_mean(*profile_cfg.throughput_mbps, profile_cfg.throughput_mode),
        _triangular_variance(*profile_cfg.throughput_mbps, profile_cfg.throughput_mode),
    )

    low, high = profile_cfg.priority
    expected_priority_mean = (low + high) / 2
    priority_variance = ((high - low + 1) ** 2 - 1) / 12
    assert_mean_within_ci(priorities, expected_priority_mean, priority_variance)


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


def test_normalise_weight_map_rejects_unknown_services() -> None:
    with pytest.raises(ValueError):
        _normalise_weight_map({"unknown": 1.0})


def test_normalise_weight_map_handles_partial_overrides() -> None:
    base_mix = get_service_mix("balanced")
    overrides = {"embb": 5.0}
    combined = {**base_mix, **overrides}
    normalised = _normalise_weight_map(combined)

    assert pytest.approx(sum(normalised.values()), abs=1e-9) == 1.0
    assert normalised["embb"] > 0.7
    assert normalised["embb"] > normalised["urllc"]
    assert normalised["urllc"] == pytest.approx(normalised["mmtc"])


def test_generate_synthetic_requests_accepts_custom_weights() -> None:
    weights = {"urllc": 2.0, "embb": 1.0, "mmtc": 1.0, "default": 0.0}
    records = generate_synthetic_requests(5000, seed=123, weights=weights)

    counts = Counter(record["service_type"] for record in records)
    ratios = {
        service: counts.get(service, 0) / len(records) for service in SERVICE_PROFILES
    }
    assert ratios["urllc"] == pytest.approx(0.5, abs=0.05)
    assert ratios["embb"] == pytest.approx(0.25, abs=0.04)
    assert ratios["mmtc"] == pytest.approx(0.25, abs=0.04)
    assert counts.get("default", 0) == 0


@pytest.mark.parametrize(
    "invalid_weights",
    [
        {"urllc": -0.1, "embb": 0.5, "mmtc": 0.5},
        {service: 0.0 for service in SERVICE_PROFILES},
        {"embb": 0.0, "urllc": 0.0, "mmtc": 0.0, "default": 0.0},
    ],
)
def test_generate_synthetic_requests_rejects_invalid_weights(
    invalid_weights: Mapping[str, float]
) -> None:
    with pytest.raises(ValueError):
        generate_synthetic_requests(10, weights=invalid_weights)


def test_cli_accepts_custom_weights(tmp_path: Path) -> None:
    output_path = tmp_path / "weighted.json"
    cmd = [
        sys.executable,
        str(SCRIPT_PATH),
        "--records",
        "400",
        "--profile",
        "balanced",
        "--seed",
        "5",
        "--output",
        str(output_path),
        "--format",
        "json",
        "--embb-weight",
        "5.0",
        "--urllc-weight",
        "1.0",
        "--mmtc-weight",
        "0.5",
    ]

    subprocess.run(cmd, check=True, capture_output=True, text=True)
    with output_path.open(encoding="utf-8") as handle:
        payload = json.load(handle)

    counts = Counter(item["service_type"] for item in payload)
    ratio = counts["embb"] / len(payload)
    assert ratio > 0.6
    assert counts["embb"] > counts["urllc"] > counts["mmtc"]


def test_cli_partial_weight_override_matches_expected_distribution(tmp_path: Path) -> None:
    output_path = tmp_path / "partial.json"
    cmd = [
        sys.executable,
        str(SCRIPT_PATH),
        "--records",
        "6000",
        "--profile",
        "balanced",
        "--seed",
        "17",
        "--output",
        str(output_path),
        "--format",
        "json",
        "--embb-weight",
        "5.0",
    ]

    subprocess.run(cmd, check=True, capture_output=True, text=True)
    with output_path.open(encoding="utf-8") as handle:
        payload = json.load(handle)

    observed_counts = Counter(item["service_type"] for item in payload)
    expected_mix = _normalise_weight_map({**get_service_mix("balanced"), "embb": 5.0})

    chi_squared = _chi_squared_statistic(observed_counts, expected_mix, len(payload))
    assert chi_squared < 7.90


def test_cli_rejects_negative_weights(
    tmp_path: Path,
    cli_runner: Callable[[Iterable[str], bool], subprocess.CompletedProcess[str]],
) -> None:
    output_path = tmp_path / "invalid.json"
    args = [
        "--records",
        "10",
        "--profile",
        "balanced",
        "--output",
        str(output_path),
        "--format",
        "json",
        "--urllc-weight",
        "-1.0",
    ]

    completed = cli_runner(args, expect_success=False)
    assert completed.returncode != 0
    assert "non-negative" in completed.stderr.lower()


def test_cli_zero_weight_overrides_fall_back_to_profile(
    tmp_path: Path,
    cli_runner: Callable[[Iterable[str], bool], subprocess.CompletedProcess[str]],
) -> None:
    output_path = tmp_path / "invalid_zero.json"
    args = [
        "--records",
        "10",
        "--profile",
        "balanced",
        "--output",
        str(output_path),
        "--format",
        "json",
        "--embb-weight",
        "0",
        "--urllc-weight",
        "0",
        "--mmtc-weight",
        "0",
    ]

    completed = cli_runner(args, expect_success=True)
    assert completed.returncode == 0

    with output_path.open(encoding="utf-8") as handle:
        payload = json.load(handle)

    counts = Counter(item["service_type"] for item in payload)
    ratio_default = counts["default"] / len(payload)
    # With all explicit overrides set to zero the base mix's default weight
    # should dominate the sampling process.
    assert ratio_default > 0.85
