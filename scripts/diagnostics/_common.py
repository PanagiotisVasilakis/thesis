"""Shared helpers for ML diagnostics scripts.

All utilities here intentionally avoid external dependencies so the
scripts can run inside the thesis repository virtual environment
without additional setup steps.
"""
from __future__ import annotations

import json
import logging
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Tuple

LOGGER = logging.getLogger("ml_diagnostics")

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICES_PATH = REPO_ROOT / "5g-network-optimization" / "services"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SERVICES_PATH) not in sys.path:
    sys.path.insert(0, str(SERVICES_PATH))


def ensure_logging(verbose: bool = False) -> None:
    """Configure root logging for the diagnostics tooling."""
    if logging.getLogger().handlers:
        return
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")


def ensure_parent(path: Path) -> None:
    """Create parent directory for *path* if it does not exist."""
    path.parent.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Persist *payload* to *path* as pretty-printed JSON."""
    ensure_parent(path)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def load_selector(model_path: Path | str):
    """Load the AntennaSelector model from *model_path*.

    The import is intentionally inside the function to avoid importing the
    ML stack when the helpers are only used for data analysis.
    """
    from ml_service.app.models.antenna_selector import AntennaSelector

    selector = AntennaSelector(model_path=str(model_path))
    if selector.model is None:
        selector.load(str(model_path))
    return selector


def generate_synthetic_samples(
    count: int,
    *,
    num_antennas: int = 4,
    seed: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Return synthetic UE samples for diagnostics.

    The upstream generator currently uses a fixed numpy seed. When *seed* is
    provided we offset the generated UE IDs to avoid cache collisions within
    the feature extractor.
    """
    from ml_service.app.utils.synthetic_data import generate_synthetic_training_data

    samples = generate_synthetic_training_data(num_samples=count, num_antennas=num_antennas)
    if seed is not None:
        suffix = f"diag{seed}"
        for sample in samples:
            if "ue_id" in sample:
                sample["ue_id"] = f"{sample['ue_id']}_{suffix}"
    return samples


def get_cell_positions(num_antennas: int = 4) -> Dict[str, Tuple[float, float]]:
    """Return synthetic cell coordinates used by the generator."""
    from ml_service.app.utils.synthetic_data import _generate_antenna_positions

    return _generate_antenna_positions(num_antennas)


def _euclidean_distance(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def compute_prediction_stats(
    selector,
    samples: Iterable[Mapping[str, Any]],
    *,
    cell_positions: Optional[Mapping[str, Tuple[float, float]]] = None,
) -> Dict[str, Any]:
    """Compute prediction distribution, confidence and distance metrics."""
    total = 0
    predictions: List[str] = []
    confidences: List[float] = []
    confidence_by_label: MutableMapping[str, List[float]] = defaultdict(list)
    distance_to_prediction: List[float] = []
    distance_by_label: MutableMapping[str, List[float]] = defaultdict(list)

    for sample in samples:
        try:
            features = selector.extract_features(dict(sample))
            result = selector.predict(features)
        except Exception as exc:  # noqa: BLE001 - diagnostics must continue
            LOGGER.debug("Prediction failed for sample %s: %s", sample.get("ue_id"), exc)
            continue

        antenna_id = str(result.get("antenna_id", "unknown"))
        confidence = float(result.get("confidence", 0.0))
        predictions.append(antenna_id)
        confidences.append(confidence)
        confidence_by_label[antenna_id].append(confidence)
        total += 1

        if cell_positions and "latitude" in sample and "longitude" in sample:
            ue_xy = (float(sample.get("latitude", 0.0)), float(sample.get("longitude", 0.0)))
            cell_xy = cell_positions.get(antenna_id)
            if cell_xy is not None:
                distance = _euclidean_distance(ue_xy, cell_xy)
                distance_to_prediction.append(distance)
                distance_by_label[antenna_id].append(distance)

    distribution = Counter(predictions)
    unique_predictions = len(distribution)
    diversity_ratio = (unique_predictions / total) if total else 0.0
    entropy = 0.0
    if total:
        for count in distribution.values():
            probability = count / total
            if probability > 0:
                entropy -= probability * math.log(probability, 2)

    def _summarise(values: List[float]) -> Dict[str, float]:
        if not values:
            return {"count": 0}
        return {
            "count": len(values),
            "mean": float(statistics.fmean(values)),
            "median": float(statistics.median(values)),
            "min": float(min(values)),
            "max": float(max(values)),
        }

    per_class_confidence = {
        label: _summarise(vals) for label, vals in confidence_by_label.items()
    }
    per_class_distance = {
        label: _summarise(vals) for label, vals in distance_by_label.items()
    }

    distribution_pct = {
        label: {
            "count": count,
            "ratio": (count / total) if total else 0.0,
        }
        for label, count in distribution.items()
    }

    summary: Dict[str, Any] = {
        "total_samples": total,
        "unique_predictions": unique_predictions,
        "diversity_ratio": diversity_ratio,
        "entropy_bits": entropy,
        "distribution": distribution_pct,
        "confidence_overall": _summarise(confidences),
        "confidence_per_class": per_class_confidence,
    }

    if distance_to_prediction:
        summary["distance_to_prediction"] = _summarise(distance_to_prediction)
        summary["distance_per_class"] = per_class_distance

    return summary


def summarise_class_distribution(labels: Iterable[str]) -> Dict[str, Any]:
    """Return counts and ratios for *labels*."""
    values = list(labels)
    total = len(values)
    counter = Counter(values)
    imbalance_ratio = 0.0
    if counter:
        counts = counter.values()
        imbalance_ratio = max(counts) / min(counts) if min(counts) > 0 else float("inf")
    return {
        "total_samples": total,
        "class_distribution": {
            label: {
                "count": count,
                "ratio": (count / total) if total else 0.0,
            }
            for label, count in counter.items()
        },
        "imbalance_ratio": imbalance_ratio,
    }


def describe_numeric_feature(values: Iterable[float]) -> Dict[str, float]:
    """Summarise numeric values using common statistics."""
    data = list(values)
    if not data:
        return {"count": 0}
    return {
        "count": len(data),
        "mean": float(statistics.fmean(data)),
        "median": float(statistics.median(data)),
        "min": float(min(data)),
        "max": float(max(data)),
        "stdev": float(statistics.pstdev(data)),
    }
