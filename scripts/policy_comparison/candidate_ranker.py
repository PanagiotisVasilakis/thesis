"""Candidate-ranker feature construction and sequence-aware labels."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Mapping, Optional, Sequence

from .complexity import candidate_complexity_for_record
from .schemas import MeasurementTraceRecord, VisibleCellMeasurement


def build_candidate_ranker_features(
    record: MeasurementTraceRecord,
    *,
    recent_handover_count: Optional[int] = None,
    time_since_last_handover_s: Optional[float] = None,
    current_dwell_time_s: Optional[float] = None,
    last_handover_source: Optional[str] = None,
    previous_serving_cell: Optional[str] = None,
    previous_target_cell: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Return one feature row per viable non-serving handover candidate."""
    visible = record.visible_cell_map
    serving = visible[record.serving_cell]
    ml_features = record.metadata.get("ml_features")
    if not isinstance(ml_features, Mapping):
        ml_features = {}

    complexity = candidate_complexity_for_record(record)
    distances = _numeric_mapping(
        ml_features.get("cell_distances_m")
        or ml_features.get("distance_to_cells")
        or ml_features.get("distance_by_cell")
    )
    movement_alignment = _numeric_mapping(
        ml_features.get("moving_toward_cells")
        or ml_features.get("movement_alignment_by_cell")
        or ml_features.get("approach_by_cell")
    )
    observed_qos = _latest_observed_qos(record.observed_qos)

    handover_count = recent_handover_count
    if handover_count is None:
        handover_count = _optional_int(ml_features.get("handover_count"), default=0)
    time_since_handover = time_since_last_handover_s
    if time_since_handover is None:
        time_since_handover = _optional_float(
            ml_features.get("time_since_handover"),
            default=0.0,
        )
    dwell_time = current_dwell_time_s
    if dwell_time is None:
        dwell_time = _optional_float(ml_features.get("current_dwell_time_s"), default=0.0)
    source = str(last_handover_source or ml_features.get("last_handover_source") or "")
    previous_serving = (
        None
        if previous_serving_cell is None
        else str(previous_serving_cell)
    )
    if previous_serving is None and ml_features.get("previous_serving_cell") is not None:
        previous_serving = str(ml_features.get("previous_serving_cell"))
    previous_target = (
        None
        if previous_target_cell is None
        else str(previous_target_cell)
    )
    if previous_target is None and ml_features.get("previous_target_cell") is not None:
        previous_target = str(ml_features.get("previous_target_cell"))

    rows: list[dict[str, Any]] = []
    for candidate_id in complexity.viable_candidates:
        candidate = visible[candidate_id]
        rows.append(
            {
                "scenario": record.scenario,
                "seed": record.seed,
                "topology_hash": record.topology_hash,
                "ue_id": record.ue_id,
                "step_index": record.step_index,
                "timestamp_s": record.timestamp_s,
                "serving_cell": record.serving_cell,
                "candidate_cell": candidate_id,
                "candidate_count": complexity.viable_candidate_count,
                "complexity_bucket": complexity.complexity_bucket,
                "rsrp_dbm": float(candidate.rsrp_dbm),
                "serving_rsrp_dbm": float(serving.rsrp_dbm),
                "delta_rsrp_db": float(candidate.rsrp_dbm - serving.rsrp_dbm),
                "sinr_db": _measurement_value(candidate, "sinr_db", default=0.0),
                "serving_sinr_db": _measurement_value(serving, "sinr_db", default=0.0),
                "delta_sinr_db": _delta_measurement(candidate, serving, "sinr_db"),
                "rsrq_db": _measurement_value(candidate, "rsrq_db", default=0.0),
                "serving_rsrq_db": _measurement_value(serving, "rsrq_db", default=0.0),
                "delta_rsrq_db": _delta_measurement(candidate, serving, "rsrq_db"),
                "candidate_load": float(candidate.load or 0.0),
                "serving_load": float(serving.load or 0.0),
                "delta_load": float((candidate.load or 0.0) - (serving.load or 0.0)),
                "speed_mps": float(record.speed_mps or 0.0),
                "signal_trend": _optional_float(ml_features.get("signal_trend"), default=0.0),
                "distance_to_candidate_m": distances.get(candidate_id, 0.0),
                "moving_toward_candidate": movement_alignment.get(candidate_id, 0.0),
                "recent_handover_count": int(handover_count),
                "time_since_last_handover_s": float(time_since_handover),
                "current_dwell_time_s": float(dwell_time),
                "last_handover_source_ml": float(
                    source in {"ml_high_complexity", "candidate_ranker", "ml_policy"}
                ),
                "last_handover_source_a3": float(
                    source in {"a3_complexity_gate", "tuned_a3_baseline", "fixed_a3_baseline"}
                ),
                "has_prior_handover": float(handover_count > 0),
                "candidate_is_previous_serving": float(candidate_id == previous_serving),
                "candidate_is_previous_target": float(candidate_id == previous_target),
                "service_priority": _optional_int(
                    ml_features.get("service_priority"),
                    default=5,
                ),
                "latency_ms": _optional_float(observed_qos.get("latency_ms"), default=0.0),
                "throughput_mbps": _optional_float(
                    observed_qos.get("throughput_mbps"),
                    default=0.0,
                ),
                "packet_loss_rate": _optional_float(
                    observed_qos.get("packet_loss_rate"),
                    default=0.0,
                ),
            }
        )
    return rows


def build_candidate_ranker_dataset(
    records: Sequence[MeasurementTraceRecord],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records:
        rows.extend(build_candidate_ranker_features(record))
    return rows


def build_labeled_candidate_ranker_dataset(
    records: Sequence[MeasurementTraceRecord],
    *,
    sequence_window_steps: int = 3,
    stay_margin_db: float = 2.0,
    handover_penalty_db: float = 1.0,
    load_penalty_db: float = 4.0,
    sinr_weight: float = 0.2,
    rsrq_weight: float = 0.1,
    missing_future_cell_score: float = -160.0,
    same_site_penalty_db: float = 6.0,
    rf_regression_penalty_db: float = 4.0,
    short_dwell_penalty_db: float = 4.0,
    ping_pong_risk_penalty_db: float = 5.0,
    min_dwell_time_s: float = 10.0,
    tie_tolerance: float = 1e-9,
) -> list[dict[str, Any]]:
    """Return candidate rows with labels from a short future measurement window.

    Labels are derived from policy-free traces only. A candidate is positive
    only when its sequence utility beats the serving cell by the stay margin
    after a handover penalty. This avoids training a ranker on the greedy
    strongest-signal-now rule.
    """
    if sequence_window_steps < 1:
        raise ValueError("sequence_window_steps must be >= 1")

    rows: list[dict[str, Any]] = []
    for group_records in _group_records(records):
        ordered = sorted(group_records, key=lambda record: record.step_index)
        for index, record in enumerate(ordered):
            feature_rows = build_candidate_ranker_features(record)
            if not feature_rows:
                continue

            serving_score = _sequence_cell_score(
                ordered,
                index,
                record.serving_cell,
                sequence_window_steps=sequence_window_steps,
                load_penalty_db=load_penalty_db,
                sinr_weight=sinr_weight,
                rsrq_weight=rsrq_weight,
                missing_future_cell_score=missing_future_cell_score,
            )
            candidate_scores = {}
            candidate_penalties = {}
            for row in feature_rows:
                candidate_id = str(row["candidate_cell"])
                raw_score = _sequence_cell_score(
                    ordered,
                    index,
                    candidate_id,
                    sequence_window_steps=sequence_window_steps,
                    load_penalty_db=load_penalty_db,
                    sinr_weight=sinr_weight,
                    rsrq_weight=rsrq_weight,
                    missing_future_cell_score=missing_future_cell_score,
                )
                penalties = _candidate_decision_penalties(
                    row,
                    serving_cell=record.serving_cell,
                    handover_penalty_db=handover_penalty_db,
                    same_site_penalty_db=same_site_penalty_db,
                    rf_regression_penalty_db=rf_regression_penalty_db,
                    short_dwell_penalty_db=short_dwell_penalty_db,
                    ping_pong_risk_penalty_db=ping_pong_risk_penalty_db,
                    min_dwell_time_s=min_dwell_time_s,
                )
                candidate_penalties[candidate_id] = penalties
                candidate_scores[candidate_id] = raw_score - penalties["total_penalty"]
            ranked_candidates = sorted(
                candidate_scores.items(),
                key=lambda item: item[1],
                reverse=True,
            )
            best_candidate, best_score = ranked_candidates[0]
            selected_candidate_set = {
                candidate_id
                for candidate_id, score in ranked_candidates
                if abs(score - best_score) <= tie_tolerance
            }
            handover_desirable = best_score - serving_score >= stay_margin_db
            rank_by_candidate = {
                candidate_id: rank
                for rank, (candidate_id, _) in enumerate(ranked_candidates, start=1)
            }

            for row in feature_rows:
                candidate_id = str(row["candidate_cell"])
                candidate_score = candidate_scores[candidate_id]
                penalties = candidate_penalties[candidate_id]
                row.update(
                    {
                        "candidate_sequence_score": float(candidate_score),
                        "candidate_raw_sequence_score": float(
                            candidate_score + penalties["total_penalty"]
                        ),
                        "serving_sequence_score": float(serving_score),
                        "stay_sequence_score": float(serving_score),
                        "utility_margin_vs_serving": float(
                            candidate_score - serving_score
                        ),
                        "utility_margin_vs_stay": float(candidate_score - serving_score),
                        "handover_action_penalty": float(handover_penalty_db),
                        "same_site_penalty": float(penalties["same_site_penalty"]),
                        "rf_regression_penalty": float(penalties["rf_regression_penalty"]),
                        "short_dwell_penalty": float(penalties["short_dwell_penalty"]),
                        "ping_pong_risk_penalty": float(penalties["ping_pong_risk_penalty"]),
                        "total_decision_penalty": float(penalties["total_penalty"]),
                        "rank_label": int(rank_by_candidate[candidate_id]),
                        "selected_label": int(
                            handover_desirable and candidate_id in selected_candidate_set
                        ),
                        "selected_label_tie_count": int(
                            len(selected_candidate_set) if handover_desirable else 0
                        ),
                        "handover_desirable": bool(handover_desirable),
                    }
                )
                rows.append(row)
    return rows


def _candidate_decision_penalties(
    row: Mapping[str, Any],
    *,
    serving_cell: str,
    handover_penalty_db: float,
    same_site_penalty_db: float,
    rf_regression_penalty_db: float,
    short_dwell_penalty_db: float,
    ping_pong_risk_penalty_db: float,
    min_dwell_time_s: float,
) -> dict[str, float]:
    candidate_id = str(row.get("candidate_cell") or "")
    same_site_penalty = (
        float(same_site_penalty_db)
        if _same_site_sector(serving_cell, candidate_id)
        else 0.0
    )
    delta_rsrp = _optional_float(row.get("delta_rsrp_db"), default=0.0)
    delta_sinr = _optional_float(row.get("delta_sinr_db"), default=0.0)
    rf_regression_penalty = (
        float(rf_regression_penalty_db)
        if delta_rsrp <= 0.0 or delta_sinr < -1.0
        else 0.0
    )
    recent_count = _optional_int(row.get("recent_handover_count"), default=0)
    time_since = _optional_float(row.get("time_since_last_handover_s"), default=0.0)
    short_dwell_penalty = (
        float(short_dwell_penalty_db)
        if recent_count > 0 and time_since < min_dwell_time_s
        else 0.0
    )
    ping_pong_penalty = (
        float(ping_pong_risk_penalty_db)
        if candidate_id == str(row.get("candidate_is_previous_serving") or "")
        else 0.0
    )
    if float(row.get("candidate_is_previous_serving", 0.0) or 0.0) > 0.0:
        ping_pong_penalty = float(ping_pong_risk_penalty_db)
    total = (
        float(handover_penalty_db)
        + same_site_penalty
        + rf_regression_penalty
        + short_dwell_penalty
        + ping_pong_penalty
    )
    return {
        "same_site_penalty": same_site_penalty,
        "rf_regression_penalty": rf_regression_penalty,
        "short_dwell_penalty": short_dwell_penalty,
        "ping_pong_risk_penalty": ping_pong_penalty,
        "total_penalty": total,
    }


def _same_site_sector(cell_a: str, cell_b: str, *, sectors_per_site: int = 4) -> bool:
    try:
        a = int(str(cell_a))
        b = int(str(cell_b))
    except (TypeError, ValueError):
        return False
    if a == b:
        return False
    if a <= 0 or b <= 0:
        return False
    return (a - 1) // sectors_per_site == (b - 1) // sectors_per_site


def _measurement_value(
    cell: VisibleCellMeasurement,
    field_name: str,
    *,
    default: float,
) -> float:
    value = getattr(cell, field_name)
    return default if value is None else float(value)


def _delta_measurement(
    candidate: VisibleCellMeasurement,
    serving: VisibleCellMeasurement,
    field_name: str,
) -> float:
    candidate_value = getattr(candidate, field_name)
    serving_value = getattr(serving, field_name)
    if candidate_value is None or serving_value is None:
        return 0.0
    return float(candidate_value - serving_value)


def _numeric_mapping(raw: Any) -> dict[str, float]:
    if not isinstance(raw, Mapping):
        return {}
    values: dict[str, float] = {}
    for key, value in raw.items():
        try:
            values[str(key)] = float(value)
        except (TypeError, ValueError):
            continue
    return values


def _latest_observed_qos(raw: Any) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        return {}
    latest = raw.get("latest")
    if isinstance(latest, Mapping):
        return latest
    return raw


def _optional_float(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _optional_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _group_records(
    records: Iterable[MeasurementTraceRecord],
) -> Iterable[list[MeasurementTraceRecord]]:
    groups: dict[tuple[str, int, str], list[MeasurementTraceRecord]] = defaultdict(list)
    for record in records:
        groups[(record.scenario, record.seed, record.ue_id)].append(record)
    return groups.values()


def _sequence_cell_score(
    records: Sequence[MeasurementTraceRecord],
    start_index: int,
    cell_id: str,
    *,
    sequence_window_steps: int,
    load_penalty_db: float,
    sinr_weight: float,
    rsrq_weight: float,
    missing_future_cell_score: float,
) -> float:
    scores: list[float] = []
    end_index = min(len(records), start_index + sequence_window_steps)
    for record in records[start_index:end_index]:
        cell = record.visible_cell_map.get(cell_id)
        if cell is None:
            scores.append(float(missing_future_cell_score))
            continue
        scores.append(
            _cell_utility_score(
                cell,
                max_load=_max_visible_load(record.visible_cells),
                load_penalty_db=load_penalty_db,
                sinr_weight=sinr_weight,
                rsrq_weight=rsrq_weight,
            )
        )
    if not scores:
        return float(missing_future_cell_score)
    return float(sum(scores) / len(scores))


def _cell_utility_score(
    cell: VisibleCellMeasurement,
    *,
    max_load: float,
    load_penalty_db: float,
    sinr_weight: float,
    rsrq_weight: float,
) -> float:
    load = float(cell.load or 0.0)
    normalized_load = load / max_load if max_load > 1.0 else load
    return float(
        cell.rsrp_dbm
        + sinr_weight * _measurement_value(cell, "sinr_db", default=0.0)
        + rsrq_weight * _measurement_value(cell, "rsrq_db", default=-30.0)
        - load_penalty_db * max(0.0, normalized_load)
    )


def _max_visible_load(cells: Sequence[VisibleCellMeasurement]) -> float:
    return max((float(cell.load or 0.0) for cell in cells), default=0.0)
