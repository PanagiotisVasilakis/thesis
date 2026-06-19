"""Cost-to-go oracle labels and candidate-independent action features."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Mapping, Sequence

from .complexity import candidate_complexity_for_record, is_viable_cell
from .qos_model import estimate_counterfactual_qos, qos_compliance
from .schemas import MeasurementTraceRecord


ORACLE_LABEL_POLICY = "physical_cost_to_go_v1"
RAW_ID_COLUMNS = {"ue_id", "serving_cell", "candidate_cell", "action_cell"}


def action_features(
    record: MeasurementTraceRecord,
    *,
    serving_cell: str,
    action_cell: str,
    recent_handover_count: int = 0,
    dwell_time_s: float = 0.0,
) -> dict[str, float]:
    visible = record.visible_cell_map
    serving = visible[serving_cell]
    action = visible[action_cell]
    complexity = candidate_complexity_for_record(record.with_serving_cell(serving_cell))
    serving_sinr = float(serving.sinr_db if serving.sinr_db is not None else -30.0)
    action_sinr = float(action.sinr_db if action.sinr_db is not None else -30.0)
    serving_load = float(serving.load or 0.0)
    action_load = float(action.load or 0.0)
    return {
        "action_is_stay": float(action_cell == serving_cell),
        "candidate_count": float(complexity.viable_candidate_count),
        "viable_cell_count": float(complexity.viable_cell_count),
        "environment_complexity": {"sparse": 0.0, "moderate": 1.0, "high": 2.0}[
            complexity.environment_complexity_bucket
        ],
        "serving_rsrp_dbm": float(serving.rsrp_dbm),
        "action_rsrp_dbm": float(action.rsrp_dbm),
        "delta_rsrp_db": float(action.rsrp_dbm - serving.rsrp_dbm),
        "serving_sinr_db": serving_sinr,
        "action_sinr_db": action_sinr,
        "delta_sinr_db": action_sinr - serving_sinr,
        "serving_rsrq_db": float(serving.rsrq_db if serving.rsrq_db is not None else -30.0),
        "action_rsrq_db": float(action.rsrq_db if action.rsrq_db is not None else -30.0),
        "serving_load": serving_load,
        "action_load": action_load,
        "delta_load": action_load - serving_load,
        "speed_mps": float(record.speed_mps or 0.0),
        "recent_handover_count": float(recent_handover_count),
        "dwell_time_s": float(dwell_time_s),
        "latency_requirement_ms": float(
            (record.qos_requirements or {}).get("latency_requirement_ms", 100.0)
        ),
        "throughput_requirement_mbps": float(
            (record.qos_requirements or {}).get("throughput_requirement_mbps", 0.0)
        ),
        "reliability_pct": float(
            (record.qos_requirements or {}).get("reliability_pct", 0.0)
        ),
    }


def solve_cost_to_go(
    records: Sequence[MeasurementTraceRecord],
    *,
    discount: float = 0.98,
    horizon_steps: int = 20,
) -> list[dict[str, Any]]:
    """Return oracle action rows along the oracle's forward serving trajectory."""
    ordered = sorted(records, key=lambda item: (item.timestamp_s, item.step_index))
    if not ordered:
        return []
    if horizon_steps <= 0:
        raise ValueError("horizon_steps must be positive")
    value_previous = [
        {cell.cell_id: 0.0 for cell in record.visible_cells} for record in ordered
    ]
    action_costs_by_step: list[dict[str, dict[str, float]]] = []
    for _depth in range(1, horizon_steps + 1):
        values_current: list[dict[str, float]] = []
        costs_current: list[dict[str, dict[str, float]]] = []
        for index, record in enumerate(ordered):
            visible = record.visible_cell_map
            values: dict[str, float] = {}
            costs_by_serving: dict[str, dict[str, float]] = {}
            for serving_cell in visible:
                actions = [serving_cell] + [
                    cell.cell_id
                    for cell in record.visible_cells
                    if cell.cell_id != serving_cell and is_viable_cell(cell)
                ]
                costs: dict[str, float] = {}
                for action_cell in actions:
                    cost = _immediate_cost(record, serving_cell, action_cell)
                    if index + 1 < len(ordered):
                        if action_cell in ordered[index + 1].visible_cell_map:
                            cost += discount * value_previous[index + 1].get(
                                action_cell, 30.0
                            )
                        else:
                            cost += 30.0
                    costs[action_cell] = float(cost)
                costs_by_serving[serving_cell] = costs
                values[serving_cell] = min(costs.values())
            costs_current.append(costs_by_serving)
            values_current.append(values)
        action_costs_by_step = costs_current
        value_previous = values_current

    serving_cell = ordered[0].initial_serving_cell or ordered[0].serving_cell
    recent_handover_times: list[float] = []
    dwell_started = ordered[0].timestamp_s
    previous_serving_cell: str | None = None
    rows: list[dict[str, Any]] = []
    for index, record in enumerate(ordered):
        if serving_cell not in record.visible_cell_map:
            serving_cell = record.serving_cell
            dwell_started = record.timestamp_s
        costs = dict(action_costs_by_step[index][serving_cell])
        dwell_time = max(0.0, record.timestamp_s - dwell_started)
        for action_cell in costs:
            if action_cell != serving_cell and action_cell == previous_serving_cell:
                costs[action_cell] += 5.0
            if action_cell != serving_cell and dwell_time < 3.0:
                costs[action_cell] += 3.0
        best_action, best_cost = min(costs.items(), key=lambda item: (item[1], item[0]))
        recent_handover_times = [
            value for value in recent_handover_times if record.timestamp_s - value <= 60.0
        ]
        group = f"{record.scenario}:{record.seed}:{record.ue_id}:{record.step_index}"
        ordered_costs = sorted(set(costs.values()))
        for action_cell, action_cost in costs.items():
            rank = ordered_costs.index(action_cost)
            relevance = max(0, 3 - rank)
            rows.append(
                {
                    "scenario": record.scenario,
                    "seed": record.seed,
                    "ue_id": record.ue_id,
                    "step_index": record.step_index,
                    "snapshot_group": group,
                    "serving_cell": serving_cell,
                    "action_cell": action_cell,
                    "selected_label": int(action_cell == best_action),
                    "oracle_action_cost": float(action_cost),
                    "oracle_regret": float(action_cost - best_cost),
                    "oracle_utility": float(best_cost - action_cost),
                    "relevance": int(relevance),
                    **action_features(
                        record,
                        serving_cell=serving_cell,
                        action_cell=action_cell,
                        recent_handover_count=len(recent_handover_times),
                        dwell_time_s=dwell_time,
                    ),
                }
            )
        if best_action != serving_cell:
            recent_handover_times.append(record.timestamp_s)
            previous_serving_cell = serving_cell
            serving_cell = best_action
            dwell_started = record.timestamp_s
    return rows


def _immediate_cost(
    record: MeasurementTraceRecord,
    serving_cell: str,
    action_cell: str,
) -> float:
    visible = record.visible_cell_map
    serving = visible[serving_cell]
    action = visible[action_cell]
    handover = action_cell != serving_cell
    cost = 1.0 if handover else 0.0
    if action.rsrp_dbm < -110.0:
        cost += 2.0
    if action.rsrp_dbm < -115.0:
        cost += 8.0
    action_sinr = float(action.sinr_db if action.sinr_db is not None else -30.0)
    if action_sinr < -5.0:
        cost += 2.0
        if handover:
            cost += 3.0
    if handover and action.rsrp_dbm <= serving.rsrp_dbm:
        cost += 3.0
    if handover and float(action.load or 0.0) > float(serving.load or 0.0):
        cost += 2.0
    observed = estimate_counterfactual_qos(
        record,
        serving_cell=action_cell,
        load=float(action.load or 0.0),
        handover_interruption=handover,
    )
    if not qos_compliance(record.qos_requirements, observed)["passed"]:
        cost += 10.0
    return cost


def feature_columns(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    excluded = {
        "scenario", "seed", "ue_id", "step_index", "snapshot_group",
        "serving_cell", "action_cell", "selected_label", "oracle_action_cost",
        "oracle_regret", "oracle_utility", "relevance",
    }
    columns = sorted(
        key
        for key in rows[0]
        if key not in excluded and all(isinstance(row.get(key), (int, float)) for row in rows)
    )
    if RAW_ID_COLUMNS.intersection(columns):
        raise ValueError("raw IDs leaked into oracle feature columns")
    return columns
