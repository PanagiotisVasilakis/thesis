import pytest

from handover_baseline import A3ParameterGrid, A3Parameters, A3TraceTuner
from handover_baseline.models import PolicyDecision
from handover_baseline.tuned_a3_policy import TunedA3Policy, build_snapshot_trace


def test_parameter_grid_is_deterministic():
    grid = A3ParameterGrid(
        a3_offset_db_values=(0.0, 1.0),
        hysteresis_db_values=(1.0,),
        time_to_trigger_s_values=(0.0, 1.0),
        cooldown_s_values=(0.0,),
    )

    params = grid.as_tuple()

    assert [p.to_dict() for p in params] == [
        A3Parameters(0.0, 1.0, 0.0, 0.0).to_dict(),
        A3Parameters(0.0, 1.0, 1.0, 0.0).to_dict(),
        A3Parameters(1.0, 1.0, 0.0, 0.0).to_dict(),
        A3Parameters(1.0, 1.0, 1.0, 0.0).to_dict(),
    ]


def test_invalid_grid_values_are_rejected():
    with pytest.raises(ValueError):
        A3ParameterGrid(
            a3_offset_db_values=(99.0,),
            hysteresis_db_values=(1.0,),
            time_to_trigger_s_values=(0.0,),
            cooldown_s_values=(0.0,),
        )


def test_tuner_selects_best_candidate_on_deterministic_trace():
    trace = build_snapshot_trace(
        "ue-1",
        [
            (0.0, "cell_a", {"cell_a": -112.0, "cell_b": -108.0}),
            (1.0, "cell_a", {"cell_a": -113.0, "cell_b": -107.0}),
            (2.0, "cell_a", {"cell_a": -113.0, "cell_b": -107.0}),
        ],
    )
    grid = A3ParameterGrid(
        a3_offset_db_values=(0.0,),
        hysteresis_db_values=(0.0, 5.0),
        time_to_trigger_s_values=(0.0,),
        cooldown_s_values=(0.0,),
    )

    result = A3TraceTuner(grid, low_quality_rsrp_floor_dbm=-110.0).fit(trace)

    assert result.selected_parameters.hysteresis_db == 0.0
    assert result.selected_score == 11.0
    assert len(result.evaluated_configurations) == 2
    assert [entry.score for entry in result.evaluated_configurations] == [11.0, 21.0]


def test_tuning_result_preserves_configurations_and_scores():
    trace = build_snapshot_trace(
        "ue-1",
        [(0.0, "cell_a", {"cell_a": -100.0, "cell_b": -98.0})],
    )
    grid = A3ParameterGrid(
        a3_offset_db_values=(0.0, 1.0),
        hysteresis_db_values=(1.0,),
        time_to_trigger_s_values=(0.0,),
        cooldown_s_values=(0.0,),
    )

    result = A3TraceTuner(grid).fit(trace)
    serialized = result.to_dict()

    assert len(serialized["evaluated_configurations"]) == 2
    assert "score" in serialized["evaluated_configurations"][0]
    assert "selected_parameters" in serialized


def test_tuned_policy_uses_same_decision_schema_as_fixed_a3():
    trace = build_snapshot_trace(
        "ue-1",
        [(0.0, "cell_a", {"cell_a": -112.0, "cell_b": -108.0})],
    )
    grid = A3ParameterGrid(
        a3_offset_db_values=(0.0,),
        hysteresis_db_values=(0.0,),
        time_to_trigger_s_values=(0.0,),
        cooldown_s_values=(0.0,),
    )

    policy = TunedA3Policy.from_trace(trace, grid)
    decision = policy.decide(trace[0])

    assert isinstance(decision, PolicyDecision)
    assert decision.policy_name == "tuned_a3_baseline"
    assert decision.policy_parameters == policy.parameters


def test_tuner_does_not_require_or_consume_ml_outputs():
    trace = build_snapshot_trace(
        "ue-1",
        [
            (0.0, "cell_a", {"cell_a": -112.0, "cell_b": -108.0}),
            (1.0, "cell_a", {"cell_a": -113.0, "cell_b": -107.0}),
        ],
    )
    grid = A3ParameterGrid(
        a3_offset_db_values=(0.0,),
        hysteresis_db_values=(0.0,),
        time_to_trigger_s_values=(0.0,),
        cooldown_s_values=(0.0,),
    )

    result = A3TraceTuner(grid).fit(trace)

    assert result.selected_parameters.hysteresis_db == 0.0
    assert "ml" not in result.to_dict()["objective"].lower()
