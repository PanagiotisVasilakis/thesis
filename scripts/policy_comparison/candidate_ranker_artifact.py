"""Candidate-ranker artifact helpers shared by training and offline replay."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import joblib
import numpy as np


RANKER_MODEL_TYPE = "candidate_ranker_lightgbm_regressor"
RANKER_TARGET = "utility_margin_vs_stay"
DEFAULT_RANKER_MIN_MARGIN = 5.0
DEFAULT_RANKER_MIN_ML_DWELL_S = 10.0
DEFAULT_A3_REENTRY_EXTRA_MARGIN_DB = 3.0

NON_FEATURE_COLUMNS = {
    "scenario",
    "seed",
    "topology_hash",
    "ue_id",
    "step_index",
    "timestamp_s",
    "serving_cell",
    "candidate_cell",
    "selected_label",
    "selected_label_tie_count",
    "rank_label",
    "handover_desirable",
    "candidate_sequence_score",
    "candidate_raw_sequence_score",
    "serving_sequence_score",
    "stay_sequence_score",
    "utility_margin_vs_serving",
    "utility_margin_vs_stay",
    "handover_action_penalty",
    "same_site_penalty",
    "rf_regression_penalty",
    "short_dwell_penalty",
    "ping_pong_risk_penalty",
    "total_decision_penalty",
}

LABEL_COLUMNS = {
    "selected_label",
    "selected_label_tie_count",
    "rank_label",
    "handover_desirable",
    "candidate_sequence_score",
    "candidate_raw_sequence_score",
    "serving_sequence_score",
    "utility_margin_vs_serving",
    "stay_sequence_score",
    "utility_margin_vs_stay",
    "handover_action_penalty",
    "same_site_penalty",
    "rf_regression_penalty",
    "short_dwell_penalty",
    "ping_pong_risk_penalty",
    "total_decision_penalty",
}

COMPLEXITY_BUCKET_ENCODING = {
    "sparse": 0.0,
    "moderate": 1.0,
    "high": 2.0,
    "unknown": -1.0,
}


@dataclass(frozen=True)
class CandidateRankerArtifact:
    """Loaded ranker artifact used for deterministic offline replay."""

    path: Path
    model: Any
    feature_columns: list[str]
    selected_threshold: float
    metadata: dict[str, Any]
    artifact_sha256: str

    @property
    def model_family(self) -> str:
        return str(self.metadata.get("model_family") or "candidate_ranker")

    @property
    def decision_parameters(self) -> dict[str, float]:
        raw = self.metadata.get("ranker_decision_parameters")
        params = raw if isinstance(raw, Mapping) else {}
        threshold = params.get("selected_min_margin")
        if threshold is None:
            threshold = params.get("min_margin")
        if threshold is None:
            threshold = max(float(self.selected_threshold), DEFAULT_RANKER_MIN_MARGIN)
        min_dwell = params.get("min_ml_dwell_s", DEFAULT_RANKER_MIN_ML_DWELL_S)
        a3_guard = params.get(
            "a3_reentry_extra_margin_db",
            DEFAULT_A3_REENTRY_EXTRA_MARGIN_DB,
        )
        return {
            "selected_min_margin": _finite_float(
                threshold,
                default=DEFAULT_RANKER_MIN_MARGIN,
            ),
            "min_ml_dwell_s": _finite_float(
                min_dwell,
                default=DEFAULT_RANKER_MIN_ML_DWELL_S,
            ),
            "a3_reentry_extra_margin_db": _finite_float(
                a3_guard,
                default=DEFAULT_A3_REENTRY_EXTRA_MARGIN_DB,
            ),
        }

    def score_rows(self, rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
        if not rows:
            return {}
        matrix = np.array(
            [
                row_to_feature_vector(row, feature_columns=self.feature_columns)
                for row in rows
            ],
            dtype=float,
        )
        predictions = np.asarray(self.model.predict(matrix), dtype=float)
        return {
            str(row["candidate_cell"]): float(score)
            for row, score in zip(rows, predictions)
        }

    def safe_metadata(self) -> dict[str, Any]:
        allowed = {
            "model_type",
            "model_family",
            "target",
            "selected_features",
            "validation_metrics",
            "threshold_tuning_result",
            "seed_split",
            "dataset_size",
            "scenario_seeds",
            "model_sha256",
            "complexity_bucket_counts",
            "high_complexity_row_count",
            "min_high_complexity_rows",
            "trace_complexity_summaries",
            "label_policy",
            "ranker_decision_parameters",
            "decision_objective",
        }
        return {key: self.metadata[key] for key in allowed if key in self.metadata}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_candidate_ranker_artifact(path: Path) -> CandidateRankerArtifact:
    if not path.is_file():
        raise FileNotFoundError(f"ranker artifact does not exist: {path}")
    payload = joblib.load(path)
    if not isinstance(payload, Mapping):
        raise ValueError("ranker artifact payload must be a mapping")
    model = payload.get("model")
    feature_columns = payload.get("feature_columns")
    if model is None or not isinstance(feature_columns, list) or not feature_columns:
        raise ValueError("ranker artifact missing model or feature_columns")
    metadata_path = Path(f"{path}.meta.json")
    metadata = payload.get("metadata")
    if metadata_path.is_file():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if not isinstance(metadata, Mapping):
        raise ValueError("ranker artifact missing metadata")
    selected_threshold = _selected_threshold(metadata)
    artifact_hash = sha256_file(path)
    meta_hash = metadata.get("model_sha256")
    if meta_hash and str(meta_hash) != artifact_hash:
        raise ValueError("ranker artifact hash does not match metadata model_sha256")
    return CandidateRankerArtifact(
        path=path,
        model=model,
        feature_columns=[str(column) for column in feature_columns],
        selected_threshold=selected_threshold,
        metadata={str(key): value for key, value in metadata.items()},
        artifact_sha256=artifact_hash,
    )


def select_feature_columns(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    if not rows:
        raise ValueError("cannot select ranker features from empty rows")
    columns = set(rows[0].keys())
    for row in rows[1:]:
        columns.intersection_update(row.keys())
    candidates = []
    for column in sorted(columns):
        if column in NON_FEATURE_COLUMNS:
            continue
        if column == "complexity_bucket":
            candidates.append(column)
            continue
        if all(_is_numeric(row.get(column)) for row in rows):
            candidates.append(column)
    if not candidates:
        raise ValueError("ranker dataset produced no numeric feature columns")
    return candidates


def row_to_feature_vector(
    row: Mapping[str, Any],
    *,
    feature_columns: Sequence[str],
) -> list[float]:
    values: list[float] = []
    for column in feature_columns:
        raw = row.get(column)
        if column == "complexity_bucket":
            values.append(COMPLEXITY_BUCKET_ENCODING.get(str(raw), -1.0))
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"ranker feature {column!r} is not numeric: {raw!r}"
            ) from exc
        if not math.isfinite(value):
            raise ValueError(f"ranker feature {column!r} must be finite")
        values.append(value)
    return values


def group_key(row: Mapping[str, Any]) -> tuple[str, int, str, int, float]:
    return (
        str(row.get("scenario") or ""),
        int(row.get("seed") or 0),
        str(row.get("ue_id") or ""),
        int(row.get("step_index") or 0),
        float(row.get("timestamp_s") or 0.0),
    )


def _selected_threshold(metadata: Mapping[str, Any]) -> float:
    tuning = metadata.get("threshold_tuning_result")
    if not isinstance(tuning, Mapping):
        raise ValueError("ranker metadata missing threshold_tuning_result")
    threshold = tuning.get("selected_threshold")
    if threshold is None:
        raise ValueError("ranker metadata missing selected_threshold")
    threshold_value = float(threshold)
    if not math.isfinite(threshold_value):
        raise ValueError("ranker selected_threshold must be finite")
    return threshold_value


def _finite_float(value: Any, *, default: float) -> float:
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return float(default)
    return converted if math.isfinite(converted) else float(default)


def _is_numeric(value: Any) -> bool:
    if isinstance(value, bool):
        return True
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(converted)
