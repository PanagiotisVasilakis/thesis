"""Segment-controller artifact helpers for training and offline replay."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import joblib
import numpy as np

from .segment_controller import (
    row_to_segment_feature_vector,
    select_segment_feature_columns,
)


SEGMENT_CONTROLLER_MODEL_TYPE = "segment_controller_lightgbm_v1"
SEGMENT_CONTROLLER_MODEL_FAMILY = "segment_controller"
SEGMENT_SPARSE_AUTHORITY_MODES = {
    "tuned_a3",
    "quality_gated_a3",
    "stay_unless_weak",
}
DEFAULT_SEGMENT_DECISION_PARAMETERS = {
    "high_complexity_threshold": 3.0,
    "entry_threshold": 0.5,
    "candidate_margin_min": 20.0,
    "exit_threshold": 0.7,
    "consecutive_exit_votes": 3.0,
    "min_segment_duration_s": 6.0,
    "max_segment_duration_s": 45.0,
    "emergency_rsrp_floor_dbm": -112.0,
    "post_exit_a3_guard_s": 0.0,
    "post_exit_a3_extra_margin_db": 0.0,
    "high_reject_hold_s": 0.0,
    "sparse_authority_mode": "tuned_a3",
    "sparse_serving_rsrp_floor_dbm": -105.0,
    "sparse_serving_sinr_floor_db": -5.0,
    "sparse_a3_extra_margin_db": 3.0,
}


@dataclass(frozen=True)
class SegmentControllerArtifact:
    path: Path
    candidate_model: Any
    entry_model: Any
    exit_model: Any
    candidate_feature_columns: list[str]
    entry_feature_columns: list[str]
    exit_feature_columns: list[str]
    metadata: dict[str, Any]
    artifact_sha256: str

    @property
    def model_family(self) -> str:
        return str(self.metadata.get("model_family") or SEGMENT_CONTROLLER_MODEL_FAMILY)

    @property
    def decision_parameters(self) -> dict[str, Any]:
        raw = self.metadata.get("segment_decision_parameters")
        params = raw if isinstance(raw, Mapping) else {}
        resolved: dict[str, Any] = {}
        for key, default in DEFAULT_SEGMENT_DECISION_PARAMETERS.items():
            if key == "sparse_authority_mode":
                mode = str(params.get(key) or default)
                resolved[key] = (
                    mode if mode in SEGMENT_SPARSE_AUTHORITY_MODES else default
                )
            else:
                resolved[key] = _finite_float(params.get(key), default=float(default))
        return resolved

    def score_candidates(self, rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
        if not rows:
            return {}
        matrix = np.array(
            [
                row_to_segment_feature_vector(
                    row,
                    feature_columns=self.candidate_feature_columns,
                )
                for row in rows
            ],
            dtype=float,
        )
        predictions = np.asarray(self.candidate_model.predict(matrix), dtype=float)
        return {
            str(row["candidate_cell"]): float(score)
            for row, score in zip(rows, predictions)
        }

    def score_entry(self, row: Mapping[str, Any]) -> float:
        return _predict_score(self.entry_model, row, self.entry_feature_columns)

    def score_exit(self, row: Mapping[str, Any]) -> float:
        return _predict_score(self.exit_model, row, self.exit_feature_columns)

    def safe_metadata(self) -> dict[str, Any]:
        allowed = {
            "model_type",
            "model_family",
            "label_policy",
            "feature_columns",
            "validation_metrics",
            "grouped_split",
            "trace_hashes",
            "calibration_seeds",
            "forbidden_evaluation_seeds",
            "topology_hash",
            "model_sha256",
            "segment_decision_parameters",
            "high_complexity_snapshot_count",
            "high_complexity_candidate_row_count",
            "segment_entry_label_distribution",
            "segment_exit_label_distribution",
            "row_type_counts",
        }
        return {key: self.metadata[key] for key in allowed if key in self.metadata}


def select_feature_columns_by_type(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, list[str]]:
    return {
        "candidate": select_segment_feature_columns(rows, row_type="candidate"),
        "entry": select_segment_feature_columns(rows, row_type="entry"),
        "exit": select_segment_feature_columns(rows, row_type="exit"),
    }


def load_segment_controller_artifact(path: Path) -> SegmentControllerArtifact:
    if not path.is_file():
        raise FileNotFoundError(f"segment controller artifact does not exist: {path}")
    payload = joblib.load(path)
    if not isinstance(payload, Mapping):
        raise ValueError("segment controller artifact payload must be a mapping")
    metadata_path = Path(f"{path}.meta.json")
    metadata: Any = payload.get("metadata")
    if metadata_path.is_file():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if not isinstance(metadata, Mapping):
        raise ValueError("segment controller artifact missing metadata")
    if metadata.get("model_type") != SEGMENT_CONTROLLER_MODEL_TYPE:
        raise ValueError("segment controller artifact has wrong model_type")
    if metadata.get("model_family") != SEGMENT_CONTROLLER_MODEL_FAMILY:
        raise ValueError("segment controller artifact has wrong model_family")

    models = payload.get("models")
    features = payload.get("feature_columns")
    if not isinstance(models, Mapping):
        raise ValueError("segment controller artifact missing models")
    if not isinstance(features, Mapping):
        raise ValueError("segment controller artifact missing feature_columns")
    candidate_model = models.get("candidate")
    entry_model = models.get("entry")
    exit_model = models.get("exit")
    if candidate_model is None or entry_model is None or exit_model is None:
        raise ValueError("segment controller artifact missing one or more stage models")
    for key in ("candidate", "entry", "exit"):
        if not isinstance(features.get(key), list) or not features.get(key):
            raise ValueError(f"segment controller artifact missing {key} feature columns")

    artifact_hash = sha256_file(path)
    meta_hash = metadata.get("model_sha256")
    if meta_hash and str(meta_hash) != artifact_hash:
        raise ValueError("segment controller hash does not match metadata model_sha256")

    return SegmentControllerArtifact(
        path=path,
        candidate_model=candidate_model,
        entry_model=entry_model,
        exit_model=exit_model,
        candidate_feature_columns=[str(item) for item in features["candidate"]],
        entry_feature_columns=[str(item) for item in features["entry"]],
        exit_feature_columns=[str(item) for item in features["exit"]],
        metadata={str(key): value for key, value in metadata.items()},
        artifact_sha256=artifact_hash,
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _predict_score(model: Any, row: Mapping[str, Any], feature_columns: Sequence[str]) -> float:
    matrix = np.array(
        [
            row_to_segment_feature_vector(
                row,
                feature_columns=feature_columns,
            )
        ],
        dtype=float,
    )
    if hasattr(model, "predict_proba"):
        probabilities = np.asarray(model.predict_proba(matrix), dtype=float)
        if probabilities.ndim == 2 and probabilities.shape[1] >= 2:
            return float(probabilities[0, 1])
    predictions = np.asarray(model.predict(matrix), dtype=float)
    return float(predictions[0])


def _finite_float(value: Any, *, default: float) -> float:
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return float(default)
    return converted if math.isfinite(converted) else float(default)
