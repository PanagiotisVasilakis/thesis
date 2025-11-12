"""Validation tests for the synthetic training-data generator."""
from __future__ import annotations

from collections import Counter

import pytest

from ml_service.app.utils.synthetic_data import (
    generate_synthetic_training_data,
    validate_training_data,
)

_DATASET_PARAMS = {
    "num_samples": 4000,
    "num_antennas": 4,
    "balance_classes": True,
    "edge_case_ratio": 0.25,
    "seed": 20251109,
}


@pytest.fixture(scope="module")
def balanced_dataset():
    return generate_synthetic_training_data(**_DATASET_PARAMS)


@pytest.fixture(scope="module")
def validation_report(balanced_dataset):
    return validate_training_data(balanced_dataset)


def test_balanced_class_distribution(balanced_dataset, validation_report):
    labels = [sample["optimal_antenna"] for sample in balanced_dataset]
    counts = Counter(labels)

    assert len(counts) == _DATASET_PARAMS["num_antennas"]
    assert set(counts.values()) == {int(_DATASET_PARAMS["num_samples"] / _DATASET_PARAMS["num_antennas"])}
    assert validation_report["imbalance_ratio"] == pytest.approx(1.0, abs=1e-9)


def test_spatial_coverage(validation_report):
    lat_range = validation_report["latitude_range"]
    lon_range = validation_report["longitude_range"]

    assert lat_range[1] - lat_range[0] >= 600.0
    assert lon_range[1] - lon_range[0] >= 520.0


def test_edge_case_representation(balanced_dataset, validation_report):
    edge_outcomes = validation_report["edge_case_outcomes"]

    reassigned_ratio = edge_outcomes.get("reassigned", 0) / len(balanced_dataset)

    assert 0.22 <= reassigned_ratio <= 0.28
    assert edge_outcomes.get("reassigned", 0) > 0
    assert edge_outcomes.get("unchanged", 0) > 0
    assert sum(edge_outcomes.values()) == len(balanced_dataset)
