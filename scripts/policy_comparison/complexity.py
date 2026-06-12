"""Candidate-complexity helpers for thesis handover comparisons."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .schemas import MeasurementTraceRecord, VisibleCellMeasurement


DEFAULT_MIN_VIABLE_RSRP_DBM = -115.0
DEFAULT_MIN_VIABLE_SINR_DB = -5.0
DEFAULT_HIGH_COMPLEXITY_THRESHOLD = 3


@dataclass(frozen=True)
class CandidateComplexity:
    """Viable handover-candidate summary for one decision snapshot."""

    viable_candidate_count: int
    complexity_bucket: str
    viable_candidates: list[str]
    thresholds: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "viable_candidate_count": self.viable_candidate_count,
            "complexity_bucket": self.complexity_bucket,
            "viable_candidates": list(self.viable_candidates),
            "thresholds": dict(self.thresholds),
        }


def complexity_bucket(
    viable_candidate_count: int,
    *,
    high_complexity_threshold: int = DEFAULT_HIGH_COMPLEXITY_THRESHOLD,
) -> str:
    """Return sparse/moderate/high for a viable neighbour count."""
    if viable_candidate_count <= 1:
        return "sparse"
    if viable_candidate_count < high_complexity_threshold:
        return "moderate"
    return "high"


def is_viable_cell(
    cell: VisibleCellMeasurement,
    *,
    min_rsrp_dbm: float = DEFAULT_MIN_VIABLE_RSRP_DBM,
    min_sinr_db: float = DEFAULT_MIN_VIABLE_SINR_DB,
) -> bool:
    """Return True when a neighbour is usable for handover evaluation."""
    if cell.rsrp_dbm < min_rsrp_dbm:
        return False
    if cell.sinr_db is not None and cell.sinr_db < min_sinr_db:
        return False
    return True


def candidate_complexity_for_record(
    record: MeasurementTraceRecord,
    *,
    min_rsrp_dbm: float = DEFAULT_MIN_VIABLE_RSRP_DBM,
    min_sinr_db: float = DEFAULT_MIN_VIABLE_SINR_DB,
    high_complexity_threshold: int = DEFAULT_HIGH_COMPLEXITY_THRESHOLD,
) -> CandidateComplexity:
    """Count viable non-serving candidates in a canonical trace record."""
    candidates = [
        cell.cell_id
        for cell in record.visible_cells
        if cell.cell_id != record.serving_cell
        and is_viable_cell(
            cell,
            min_rsrp_dbm=min_rsrp_dbm,
            min_sinr_db=min_sinr_db,
        )
    ]
    count = len(candidates)
    return CandidateComplexity(
        viable_candidate_count=count,
        complexity_bucket=complexity_bucket(
            count,
            high_complexity_threshold=high_complexity_threshold,
        ),
        viable_candidates=candidates,
        thresholds={
            "min_rsrp_dbm": float(min_rsrp_dbm),
            "min_sinr_db": float(min_sinr_db),
            "high_complexity_threshold": float(high_complexity_threshold),
        },
    )


def candidate_complexity_for_feature_vector(
    feature_vector: Mapping[str, Any],
    *,
    serving_cell: str | None = None,
    min_rsrp_dbm: float = DEFAULT_MIN_VIABLE_RSRP_DBM,
    min_sinr_db: float = DEFAULT_MIN_VIABLE_SINR_DB,
    high_complexity_threshold: int = DEFAULT_HIGH_COMPLEXITY_THRESHOLD,
) -> CandidateComplexity:
    """Count viable non-serving candidates in a NEF feature vector."""
    rsrp_by_cell = feature_vector.get("neighbor_rsrp_dbm") or {}
    sinr_by_cell = feature_vector.get("neighbor_sinrs") or {}
    serving = serving_cell or str(feature_vector.get("connected_to") or "")
    candidates: list[str] = []

    if not isinstance(rsrp_by_cell, Mapping):
        rsrp_by_cell = {}
    if not isinstance(sinr_by_cell, Mapping):
        sinr_by_cell = {}

    for raw_cell_id, raw_rsrp in rsrp_by_cell.items():
        cell_id = str(raw_cell_id)
        if cell_id == serving:
            continue
        try:
            rsrp = float(raw_rsrp)
        except (TypeError, ValueError):
            continue
        raw_sinr = sinr_by_cell.get(raw_cell_id, sinr_by_cell.get(cell_id))
        try:
            sinr = None if raw_sinr is None else float(raw_sinr)
        except (TypeError, ValueError):
            sinr = None
        if rsrp >= min_rsrp_dbm and (sinr is None or sinr >= min_sinr_db):
            candidates.append(cell_id)

    count = len(candidates)
    return CandidateComplexity(
        viable_candidate_count=count,
        complexity_bucket=complexity_bucket(
            count,
            high_complexity_threshold=high_complexity_threshold,
        ),
        viable_candidates=candidates,
        thresholds={
            "min_rsrp_dbm": float(min_rsrp_dbm),
            "min_sinr_db": float(min_sinr_db),
            "high_complexity_threshold": float(high_complexity_threshold),
        },
    )


def candidate_complexity_distribution(
    records: Sequence[MeasurementTraceRecord],
    *,
    min_rsrp_dbm: float = DEFAULT_MIN_VIABLE_RSRP_DBM,
    min_sinr_db: float = DEFAULT_MIN_VIABLE_SINR_DB,
    high_complexity_threshold: int = DEFAULT_HIGH_COMPLEXITY_THRESHOLD,
) -> dict[str, int]:
    """Return sparse/moderate/high record counts for a trace."""
    counts = {"sparse": 0, "moderate": 0, "high": 0}
    for record in records:
        bucket = candidate_complexity_for_record(
            record,
            min_rsrp_dbm=min_rsrp_dbm,
            min_sinr_db=min_sinr_db,
            high_complexity_threshold=high_complexity_threshold,
        ).complexity_bucket
        counts[bucket] += 1
    return counts
