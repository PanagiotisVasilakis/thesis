"""Segment-controller dataset and feature construction.

This module keeps the new sequence-aware segment objective separate from the
older candidate-ranker row labels. It builds three row types:

* entry rows: should ML enter a handover segment at this high-complexity step?
* candidate rows: which candidate has the best segment utility if entering?
* exit rows: is it safe to return authority to A3 from an active segment?
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional, Sequence

from .candidate_ranker import build_candidate_ranker_features
from .complexity import candidate_complexity_for_record
from .schemas import MeasurementTraceRecord, VisibleCellMeasurement


SEGMENT_LABEL_POLICY_VERSION = "segment_policy_v1"
DEFAULT_SEGMENT_HORIZON_STEPS = 20
DEFAULT_MIN_SEGMENT_DURATION_S = 6.0
DEFAULT_MAX_SEGMENT_DURATION_S = 45.0
DEFAULT_STAY_MARGIN = 2.0
DEFAULT_HANDOVER_ACTION_PENALTY = 1.0
DEFAULT_PING_PONG_PENALTY = 8.0
DEFAULT_SPARSE_REENTRY_PENALTY = 8.0
DEFAULT_WEAK_SERVING_RSRP_DBM = -105.0
DEFAULT_MISSING_FUTURE_CELL_SCORE = -160.0
DEFAULT_LOAD_PENALTY = 4.0
DEFAULT_SINR_WEIGHT = 0.2
DEFAULT_RSRQ_WEIGHT = 0.1
DEFAULT_QOS_VIOLATION_PENALTY = 10.0
DEFAULT_TARGET_DISAPPEARS_PENALTY = 30.0
DEFAULT_A3_RECOVERY_MARGIN_DB = 3.0
DEFAULT_POST_SEGMENT_CHURN_PENALTY = 8.0
DEFAULT_HIGH_REJECT_RECOVERY_RISK_PENALTY = 6.0

RAW_ID_COLUMNS = {"ue_id", "serving_cell", "candidate_cell"}
COMMON_NON_FEATURE_COLUMNS = {
    "row_type",
    "scenario",
    "seed",
    "topology_hash",
    "ue_id",
    "step_index",
    "timestamp_s",
    "snapshot_group",
    "segment_group",
    "serving_cell",
    "candidate_cell",
    "best_candidate",
    "best_candidate_label",
    "best_candidate_margin",
    "best_candidate_score",
    "enter_ml_segment",
    "exit_segment_to_a3",
    "selected_label",
    "segment_utility_margin_vs_stay",
    "segment_candidate_sequence_score",
    "segment_stay_sequence_score",
    "segment_target_disappears",
    "segment_label_reason",
    "stay_score",
    "future_a3_recovery_trigger_count",
    "future_sparse_a3_trigger_count",
    "future_a3_reverse_churn_risk_count",
    "future_a3_max_margin_db",
}
COMPLEXITY_BUCKET_ENCODING = {
    "sparse": 0.0,
    "moderate": 1.0,
    "high": 2.0,
    "unknown": -1.0,
}


@dataclass(frozen=True)
class SegmentDataset:
    rows: list[dict[str, Any]]
    metadata: dict[str, Any]

    @property
    def candidate_rows(self) -> list[dict[str, Any]]:
        return [row for row in self.rows if row.get("row_type") == "candidate"]

    @property
    def entry_rows(self) -> list[dict[str, Any]]:
        return [row for row in self.rows if row.get("row_type") == "entry"]

    @property
    def exit_rows(self) -> list[dict[str, Any]]:
        return [row for row in self.rows if row.get("row_type") == "exit"]


def build_segment_policy_dataset(
    records: Sequence[MeasurementTraceRecord],
    *,
    segment_horizon_steps: int = DEFAULT_SEGMENT_HORIZON_STEPS,
    min_segment_duration_s: float = DEFAULT_MIN_SEGMENT_DURATION_S,
    max_segment_duration_s: float = DEFAULT_MAX_SEGMENT_DURATION_S,
    stay_margin: float = DEFAULT_STAY_MARGIN,
    handover_action_penalty: float = DEFAULT_HANDOVER_ACTION_PENALTY,
    ping_pong_penalty: float = DEFAULT_PING_PONG_PENALTY,
    sparse_reentry_penalty: float = DEFAULT_SPARSE_REENTRY_PENALTY,
    weak_serving_rsrp_dbm: float = DEFAULT_WEAK_SERVING_RSRP_DBM,
    invalid_target_penalty: float = DEFAULT_TARGET_DISAPPEARS_PENALTY,
    missing_future_cell_score: float = DEFAULT_MISSING_FUTURE_CELL_SCORE,
    load_penalty: float = DEFAULT_LOAD_PENALTY,
    sinr_weight: float = DEFAULT_SINR_WEIGHT,
    rsrq_weight: float = DEFAULT_RSRQ_WEIGHT,
    qos_violation_penalty: float = DEFAULT_QOS_VIOLATION_PENALTY,
    a3_recovery_margin_db: float = DEFAULT_A3_RECOVERY_MARGIN_DB,
    post_segment_churn_penalty: float = DEFAULT_POST_SEGMENT_CHURN_PENALTY,
    high_reject_recovery_risk_penalty: float = DEFAULT_HIGH_REJECT_RECOVERY_RISK_PENALTY,
) -> SegmentDataset:
    if segment_horizon_steps < 1:
        raise ValueError("segment_horizon_steps must be >= 1")
    if min_segment_duration_s < 0:
        raise ValueError("min_segment_duration_s must be non-negative")
    if max_segment_duration_s < min_segment_duration_s:
        raise ValueError("max_segment_duration_s must be >= min_segment_duration_s")

    rows: list[dict[str, Any]] = []
    high_complexity_snapshot_count = 0
    high_complexity_candidate_count = 0
    entry_label_counts: Counter[int] = Counter()
    exit_label_counts: Counter[int] = Counter()

    for group_records in _group_records(records):
        ordered = sorted(group_records, key=lambda record: record.step_index)
        for index, record in enumerate(ordered):
            complexity = candidate_complexity_for_record(record)
            if complexity.complexity_bucket != "high":
                continue

            feature_rows = build_candidate_ranker_features(record)
            feature_rows = [
                row
                for row in feature_rows
                if str(row.get("candidate_cell")) in complexity.viable_candidates
            ]
            if not feature_rows:
                continue

            high_complexity_snapshot_count += 1
            high_complexity_candidate_count += len(feature_rows)
            serving_score = _sequence_cell_score(
                ordered,
                index,
                record.serving_cell,
                segment_horizon_steps=segment_horizon_steps,
                load_penalty=load_penalty,
                sinr_weight=sinr_weight,
                rsrq_weight=rsrq_weight,
                missing_future_cell_score=missing_future_cell_score,
                qos_violation_penalty=qos_violation_penalty,
            )
            recovery_features = _future_a3_recovery_features(
                ordered,
                index,
                record.serving_cell,
                segment_horizon_steps=segment_horizon_steps,
                a3_recovery_margin_db=a3_recovery_margin_db,
            )
            candidate_scores: dict[str, float] = {}
            candidate_reasons: dict[str, str] = {}
            target_disappears: dict[str, bool] = {}
            for base_row in feature_rows:
                candidate_id = str(base_row["candidate_cell"])
                raw_score = _sequence_cell_score(
                    ordered,
                    index,
                    candidate_id,
                    segment_horizon_steps=segment_horizon_steps,
                    load_penalty=load_penalty,
                    sinr_weight=sinr_weight,
                    rsrq_weight=rsrq_weight,
                    missing_future_cell_score=missing_future_cell_score,
                    qos_violation_penalty=qos_violation_penalty,
                )
                candidate_recovery_features = _future_a3_recovery_features(
                    ordered,
                    index,
                    candidate_id,
                    segment_horizon_steps=segment_horizon_steps,
                    a3_recovery_margin_db=a3_recovery_margin_db,
                )
                disappears = _cell_disappears_before_horizon(
                    ordered,
                    index,
                    candidate_id,
                    segment_horizon_steps=segment_horizon_steps,
                )
                if candidate_recovery_features["future_sparse_a3_trigger_count"] > 0:
                    raw_score -= float(post_segment_churn_penalty)
                target_disappears[candidate_id] = disappears
                penalties = _segment_candidate_penalty(
                    base_row,
                    serving_cell=record.serving_cell,
                    serving_rsrp_dbm=record.visible_cell_map[record.serving_cell].rsrp_dbm,
                    handover_action_penalty=handover_action_penalty,
                    ping_pong_penalty=ping_pong_penalty,
                    weak_serving_rsrp_dbm=weak_serving_rsrp_dbm,
                    target_disappears_penalty=invalid_target_penalty if disappears else 0.0,
                )
                candidate_scores[candidate_id] = raw_score - penalties["total_penalty"]
                candidate_reasons[candidate_id] = penalties["reason"]

            ranked = sorted(candidate_scores.items(), key=lambda item: (item[1], item[0]), reverse=True)
            best_candidate, best_score = ranked[0]
            best_margin = float(best_score - serving_score)
            enter_label = int(best_margin >= stay_margin)
            entry_label_counts[enter_label] += 1
            snapshot_group = _snapshot_group(record)
            common = _common_snapshot_features(record)
            best_feature = next(
                row for row in feature_rows if str(row["candidate_cell"]) == best_candidate
            )
            entry_row = {
                **common,
                **recovery_features,
                "row_type": "entry",
                "snapshot_group": snapshot_group,
                "segment_group": f"{snapshot_group}:entry",
                "best_candidate": best_candidate,
                "best_candidate_label": best_candidate,
                "best_candidate_margin": best_margin,
                "best_candidate_score": float(best_score),
                "stay_score": float(serving_score),
                "best_candidate_delta_rsrp_db": _float(best_feature.get("delta_rsrp_db")),
                "best_candidate_delta_sinr_db": _float(best_feature.get("delta_sinr_db")),
                "best_candidate_load": _float(best_feature.get("candidate_load")),
                "best_candidate_distance_m": _float(best_feature.get("distance_to_candidate_m")),
                "best_candidate_moving_toward": _float(best_feature.get("moving_toward_candidate")),
                "segment_horizon_steps": float(segment_horizon_steps),
                "min_segment_duration_s": float(min_segment_duration_s),
                "max_segment_duration_s": float(max_segment_duration_s),
                "enter_ml_segment": enter_label,
                "segment_label_reason": (
                    "best_margin_exceeds_stay"
                    if enter_label
                    else "best_margin_below_stay"
                ),
            }
            rows.append(entry_row)

            for base_row in feature_rows:
                candidate_id = str(base_row["candidate_cell"])
                candidate_recovery_features = _future_a3_recovery_features(
                    ordered,
                    index,
                    candidate_id,
                    segment_horizon_steps=segment_horizon_steps,
                    a3_recovery_margin_db=a3_recovery_margin_db,
                )
                margin = float(candidate_scores[candidate_id] - serving_score)
                if recovery_features["future_sparse_a3_trigger_count"] > 0 and not enter_label:
                    margin -= float(high_reject_recovery_risk_penalty)
                candidate_row = {
                    **base_row,
                    **candidate_recovery_features,
                    "row_type": "candidate",
                    "snapshot_group": snapshot_group,
                    "segment_group": f"{snapshot_group}:candidate",
                    "segment_utility_margin_vs_stay": margin,
                    "segment_candidate_sequence_score": float(candidate_scores[candidate_id]),
                    "segment_stay_sequence_score": float(serving_score),
                    "segment_target_disappears": int(target_disappears[candidate_id]),
                    "best_candidate_label": best_candidate,
                    "selected_label": int(
                        enter_label and candidate_id == best_candidate
                    ),
                    "enter_ml_segment": enter_label,
                    "segment_label_reason": candidate_reasons[candidate_id],
                }
                rows.append(candidate_row)

            exit_rows = _build_exit_rows(
                ordered,
                entry_index=index,
                entry_record=record,
                selected_candidate=best_candidate,
                enter_label=enter_label,
                min_segment_duration_s=min_segment_duration_s,
                max_segment_duration_s=max_segment_duration_s,
                sparse_reentry_penalty=sparse_reentry_penalty,
            )
            for row in exit_rows:
                exit_label_counts[int(row["exit_segment_to_a3"])] += 1
            rows.extend(exit_rows)

    metadata = {
        "label_policy_version": SEGMENT_LABEL_POLICY_VERSION,
        "segment_horizon_steps": int(segment_horizon_steps),
        "min_segment_duration_s": float(min_segment_duration_s),
        "max_segment_duration_s": float(max_segment_duration_s),
        "stay_margin": float(stay_margin),
        "penalty_weights": {
            "handover_action_penalty": float(handover_action_penalty),
            "ping_pong_penalty": float(ping_pong_penalty),
            "sparse_reentry_penalty": float(sparse_reentry_penalty),
            "weak_serving_rsrp_dbm": float(weak_serving_rsrp_dbm),
            "invalid_target_penalty": float(invalid_target_penalty),
            "missing_future_cell_score": float(missing_future_cell_score),
            "load_penalty": float(load_penalty),
            "sinr_weight": float(sinr_weight),
            "rsrq_weight": float(rsrq_weight),
            "qos_violation_penalty": float(qos_violation_penalty),
            "a3_recovery_margin_db": float(a3_recovery_margin_db),
            "post_segment_churn_penalty": float(post_segment_churn_penalty),
            "high_reject_recovery_risk_penalty": float(
                high_reject_recovery_risk_penalty
            ),
        },
        "high_complexity_snapshot_count": high_complexity_snapshot_count,
        "high_complexity_candidate_row_count": high_complexity_candidate_count,
        "segment_entry_label_distribution": dict(entry_label_counts),
        "segment_exit_label_distribution": dict(exit_label_counts),
        "row_type_counts": dict(Counter(str(row.get("row_type")) for row in rows)),
    }
    return SegmentDataset(rows=rows, metadata=metadata)


def select_segment_feature_columns(
    rows: Sequence[Mapping[str, Any]],
    *,
    row_type: str,
) -> list[str]:
    typed_rows = [row for row in rows if row.get("row_type") == row_type]
    if not typed_rows:
        raise ValueError(f"no {row_type} rows available for feature selection")
    columns = set(typed_rows[0].keys())
    for row in typed_rows[1:]:
        columns.intersection_update(row.keys())
    features: list[str] = []
    for column in sorted(columns):
        if column in COMMON_NON_FEATURE_COLUMNS or column in RAW_ID_COLUMNS:
            continue
        if column == "complexity_bucket":
            features.append(column)
            continue
        if all(_is_numeric(row.get(column)) for row in typed_rows):
            features.append(column)
    if not features:
        raise ValueError(f"{row_type} rows produced no numeric feature columns")
    leaked = sorted(RAW_ID_COLUMNS.intersection(features))
    if leaked:
        raise ValueError("raw ID columns leaked into features: " + ", ".join(leaked))
    return features


def row_to_segment_feature_vector(
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
        value = _float(raw)
        if not math.isfinite(value):
            raise ValueError(f"segment feature {column!r} must be finite")
        values.append(value)
    return values


def segment_group_key(row: Mapping[str, Any]) -> tuple[str, int, str, int]:
    return (
        str(row.get("scenario") or ""),
        int(row.get("seed") or 0),
        str(row.get("ue_id") or ""),
        int(row.get("step_index") or 0),
    )


def _build_exit_rows(
    ordered: Sequence[MeasurementTraceRecord],
    *,
    entry_index: int,
    entry_record: MeasurementTraceRecord,
    selected_candidate: str,
    enter_label: int,
    min_segment_duration_s: float,
    max_segment_duration_s: float,
    sparse_reentry_penalty: float,
) -> list[dict[str, Any]]:
    if not enter_label:
        return []
    rows: list[dict[str, Any]] = []
    entry_time = entry_record.timestamp_s
    snapshot_group = _snapshot_group(entry_record)
    for future in ordered[entry_index + 1 :]:
        age = float(future.timestamp_s - entry_time)
        if age > max_segment_duration_s:
            break
        if selected_candidate not in future.visible_cell_map:
            rows.append(
                _exit_row(
                    entry_record,
                    future,
                    selected_candidate=selected_candidate,
                    snapshot_group=snapshot_group,
                    age_s=age,
                    exit_label=1,
                    sparse_reentry_penalty=sparse_reentry_penalty,
                    reason="candidate_disappeared",
                )
            )
            break
        if age < min_segment_duration_s:
            exit_label = 0
            reason = "minimum_duration_not_met"
        else:
            exit_label, reason = _exit_label_for_record(
                future,
                segment_cell=selected_candidate,
                entry_serving=entry_record.serving_cell,
            )
        rows.append(
            _exit_row(
                entry_record,
                future,
                selected_candidate=selected_candidate,
                snapshot_group=snapshot_group,
                age_s=age,
                exit_label=exit_label,
                sparse_reentry_penalty=sparse_reentry_penalty,
                reason=reason,
            )
        )
    return rows


def _exit_row(
    entry_record: MeasurementTraceRecord,
    record: MeasurementTraceRecord,
    *,
    selected_candidate: str,
    snapshot_group: str,
    age_s: float,
    exit_label: int,
    sparse_reentry_penalty: float,
    reason: str,
) -> dict[str, Any]:
    visible = record.visible_cell_map
    segment_cell = visible.get(selected_candidate)
    original_serving = visible.get(entry_record.serving_cell)
    best_neighbour = _best_neighbour(record, excluding=selected_candidate)
    segment_rsrp = segment_cell.rsrp_dbm if segment_cell is not None else -160.0
    original_rsrp = original_serving.rsrp_dbm if original_serving is not None else -160.0
    best_rsrp = best_neighbour.rsrp_dbm if best_neighbour is not None else -160.0
    churn_risk = float(
        best_neighbour is not None
        and (
            best_neighbour.cell_id == entry_record.serving_cell
            or _same_site_sector(best_neighbour.cell_id, selected_candidate)
        )
    )
    common = _common_snapshot_features(record)
    return {
        **common,
        "row_type": "exit",
        "snapshot_group": _snapshot_group(record),
        "segment_group": f"{snapshot_group}:segment",
        "candidate_cell": selected_candidate,
        "segment_age_s": float(age_s),
        "segment_current_rsrp_dbm": float(segment_rsrp),
        "entry_serving_visible": float(original_serving is not None),
        "entry_serving_rsrp_dbm": float(original_rsrp),
        "best_non_segment_rsrp_dbm": float(best_rsrp),
        "best_non_segment_margin_db": float(best_rsrp - segment_rsrp),
        "reverse_or_same_sector_risk": churn_risk,
        "sparse_reentry_penalty": float(sparse_reentry_penalty if churn_risk else 0.0),
        "exit_segment_to_a3": int(exit_label),
        "segment_label_reason": reason,
    }


def _exit_label_for_record(
    record: MeasurementTraceRecord,
    *,
    segment_cell: str,
    entry_serving: str,
) -> tuple[int, str]:
    visible = record.visible_cell_map
    current = visible.get(segment_cell)
    if current is None:
        return 1, "segment_cell_missing"
    best = _best_neighbour(record, excluding=segment_cell)
    if best is None:
        return 0, "no_alternative"
    reverse_or_same_sector = (
        best.cell_id == entry_serving
        or _same_site_sector(best.cell_id, segment_cell)
    )
    if reverse_or_same_sector and best.rsrp_dbm - current.rsrp_dbm < 6.0:
        return 0, "reverse_or_same_sector_churn_risk"
    if current.rsrp_dbm < -112.0:
        return 1, "segment_rf_weak"
    if best.rsrp_dbm - current.rsrp_dbm >= 4.0:
        return 1, "stable_alternative_margin"
    return 0, "segment_still_stable"


def _common_snapshot_features(record: MeasurementTraceRecord) -> dict[str, Any]:
    visible = record.visible_cell_map
    serving = visible[record.serving_cell]
    complexity = candidate_complexity_for_record(record)
    observed = record.observed_qos or {}
    ml_features = record.metadata.get("ml_features")
    if not isinstance(ml_features, Mapping):
        ml_features = {}
    return {
        "scenario": record.scenario,
        "seed": record.seed,
        "topology_hash": record.topology_hash,
        "ue_id": record.ue_id,
        "step_index": record.step_index,
        "timestamp_s": record.timestamp_s,
        "serving_cell": record.serving_cell,
        "candidate_count": complexity.viable_candidate_count,
        "complexity_bucket": complexity.complexity_bucket,
        "serving_rsrp_dbm": float(serving.rsrp_dbm),
        "serving_sinr_db": _measurement_value(serving, "sinr_db", 0.0),
        "serving_rsrq_db": _measurement_value(serving, "rsrq_db", 0.0),
        "serving_load": float(serving.load or 0.0),
        "speed_mps": float(record.speed_mps or 0.0),
        "signal_trend": _float(ml_features.get("signal_trend"), default=0.0),
        "recent_handover_count": _int(ml_features.get("handover_count"), default=0),
        "time_since_last_handover_s": _float(
            ml_features.get("time_since_handover"),
            default=0.0,
        ),
        "latency_ms": _float(observed.get("latency_ms"), default=0.0),
        "throughput_mbps": _float(observed.get("throughput_mbps"), default=0.0),
        "packet_loss_rate": _float(observed.get("packet_loss_rate"), default=0.0),
    }


def _segment_candidate_penalty(
    row: Mapping[str, Any],
    *,
    serving_cell: str,
    serving_rsrp_dbm: float,
    handover_action_penalty: float,
    ping_pong_penalty: float,
    weak_serving_rsrp_dbm: float,
    target_disappears_penalty: float,
) -> dict[str, Any]:
    candidate = str(row.get("candidate_cell") or "")
    penalty = float(handover_action_penalty)
    reasons = ["handover_action"]
    if _same_site_sector(serving_cell, candidate):
        penalty += 4.0
        reasons.append("same_site")
    if _float(row.get("candidate_is_previous_serving")) > 0.0:
        penalty += float(ping_pong_penalty)
        reasons.append("ping_pong_risk")
    if _float(row.get("delta_rsrp_db")) < 0.0 or _float(row.get("delta_sinr_db")) < -1.0:
        penalty += 4.0
        reasons.append("rf_regression")
    if serving_rsrp_dbm < weak_serving_rsrp_dbm:
        penalty = max(0.0, penalty - 2.0)
        reasons.append("weak_serving_relief")
    if target_disappears_penalty:
        penalty += float(target_disappears_penalty)
        reasons.append("target_disappears")
    return {"total_penalty": penalty, "reason": "+".join(reasons)}


def _sequence_cell_score(
    records: Sequence[MeasurementTraceRecord],
    start_index: int,
    cell_id: str,
    *,
    segment_horizon_steps: int,
    load_penalty: float,
    sinr_weight: float,
    rsrq_weight: float,
    missing_future_cell_score: float,
    qos_violation_penalty: float,
) -> float:
    scores: list[float] = []
    for record in records[start_index : start_index + segment_horizon_steps]:
        cell = record.visible_cell_map.get(cell_id)
        if cell is None:
            scores.append(float(missing_future_cell_score))
            continue
        score = _cell_score(
            cell,
            load_penalty=load_penalty,
            sinr_weight=sinr_weight,
            rsrq_weight=rsrq_weight,
        )
        if _has_qos_violation(record):
            score -= float(qos_violation_penalty)
        scores.append(score)
    if not scores:
        return float(missing_future_cell_score)
    return float(sum(scores) / len(scores))


def _cell_score(
    cell: VisibleCellMeasurement,
    *,
    load_penalty: float,
    sinr_weight: float,
    rsrq_weight: float,
) -> float:
    return (
        float(cell.rsrp_dbm)
        + sinr_weight * _measurement_value(cell, "sinr_db", 0.0)
        + rsrq_weight * _measurement_value(cell, "rsrq_db", 0.0)
        - load_penalty * float(cell.load or 0.0)
    )


def _cell_disappears_before_horizon(
    records: Sequence[MeasurementTraceRecord],
    start_index: int,
    cell_id: str,
    *,
    segment_horizon_steps: int,
) -> bool:
    return any(
        cell_id not in record.visible_cell_map
        for record in records[start_index : start_index + segment_horizon_steps]
    )


def _future_a3_recovery_features(
    records: Sequence[MeasurementTraceRecord],
    start_index: int,
    serving_cell: str,
    *,
    segment_horizon_steps: int,
    a3_recovery_margin_db: float,
) -> dict[str, float]:
    trigger_count = 0
    sparse_trigger_count = 0
    reverse_or_same_sector_count = 0
    max_margin = 0.0
    for future in records[start_index : start_index + segment_horizon_steps]:
        current = future.visible_cell_map.get(serving_cell)
        if current is None:
            continue
        best = _best_neighbour(future, excluding=serving_cell)
        if best is None:
            continue
        margin = float(best.rsrp_dbm - current.rsrp_dbm)
        max_margin = max(max_margin, margin)
        if margin < a3_recovery_margin_db:
            continue
        trigger_count += 1
        complexity = candidate_complexity_for_record(future)
        if complexity.complexity_bucket != "high":
            sparse_trigger_count += 1
        if _same_site_sector(best.cell_id, serving_cell):
            reverse_or_same_sector_count += 1
    return {
        "future_a3_recovery_trigger_count": float(trigger_count),
        "future_sparse_a3_trigger_count": float(sparse_trigger_count),
        "future_a3_reverse_churn_risk_count": float(reverse_or_same_sector_count),
        "future_a3_max_margin_db": float(max_margin),
    }


def _best_neighbour(
    record: MeasurementTraceRecord,
    *,
    excluding: Optional[str] = None,
) -> Optional[VisibleCellMeasurement]:
    candidates = [
        cell
        for cell in record.visible_cells
        if cell.cell_id != excluding and cell.cell_id != record.serving_cell
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda cell: (cell.rsrp_dbm, cell.cell_id))


def _group_records(
    records: Iterable[MeasurementTraceRecord],
) -> list[list[MeasurementTraceRecord]]:
    grouped: dict[tuple[str, int, str], list[MeasurementTraceRecord]] = defaultdict(list)
    for record in records:
        grouped[(record.scenario, record.seed, record.ue_id)].append(record)
    return list(grouped.values())


def _snapshot_group(record: MeasurementTraceRecord) -> str:
    return f"{record.scenario}:{record.seed}:{record.ue_id}:{record.step_index}"


def _has_qos_violation(record: MeasurementTraceRecord) -> bool:
    requirements = record.qos_requirements or {}
    observed = record.observed_qos or {}
    latency_requirement = requirements.get("latency_requirement_ms")
    observed_latency = observed.get("latency_ms")
    if latency_requirement is not None and observed_latency is not None:
        if float(observed_latency) > float(latency_requirement):
            return True
    throughput_requirement = requirements.get("throughput_requirement_mbps")
    observed_throughput = observed.get("throughput_mbps")
    if throughput_requirement is not None and observed_throughput is not None:
        if float(observed_throughput) < float(throughput_requirement):
            return True
    return False


def _measurement_value(
    cell: VisibleCellMeasurement,
    name: str,
    default: float,
) -> float:
    value = getattr(cell, name)
    return default if value is None else float(value)


def _same_site_sector(cell_a: Optional[str], cell_b: Optional[str], *, sectors_per_site: int = 4) -> bool:
    if cell_a is None or cell_b is None:
        return False
    try:
        a = int(str(cell_a))
        b = int(str(cell_b))
    except ValueError:
        return False
    return a != b and (a - 1) // sectors_per_site == (b - 1) // sectors_per_site


def _is_numeric(value: Any) -> bool:
    if isinstance(value, bool):
        return True
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(converted)


def _float(value: Any, default: float = 0.0) -> float:
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return float(default)
    return converted if math.isfinite(converted) else float(default)


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)
