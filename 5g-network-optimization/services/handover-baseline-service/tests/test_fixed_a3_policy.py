import pytest

from handover_baseline import (
    A3Parameters,
    CellMeasurement,
    FixedA3Policy,
    MeasurementSnapshot,
    PolicyDecision,
)


def snapshot(
    timestamp_s: float,
    serving_rsrp: float,
    neighbours: dict[str, float],
    *,
    serving_cell: str = "cell_a",
    ue_id: str = "ue-1",
) -> MeasurementSnapshot:
    return MeasurementSnapshot(
        ue_id=ue_id,
        timestamp_s=timestamp_s,
        serving_cell=CellMeasurement(serving_cell, serving_rsrp),
        neighbour_cells=[
            CellMeasurement(cell_id, rsrp) for cell_id, rsrp in neighbours.items()
        ],
    )


def test_stays_when_no_neighbour_is_better_enough():
    policy = FixedA3Policy(A3Parameters(hysteresis_db=3.0, time_to_trigger_s=0.0))

    decision = policy.decide(snapshot(0.0, -80.0, {"cell_b": -78.0}))

    assert decision.decision_type == "stay"
    assert decision.selected_target_cell is None
    assert decision.trigger_condition_result is False
    assert decision.reason == "a3_condition_not_met"


def test_selects_best_neighbour_when_better_enough():
    policy = FixedA3Policy(A3Parameters(hysteresis_db=3.0, time_to_trigger_s=0.0))

    decision = policy.decide(
        snapshot(0.0, -85.0, {"cell_b": -78.0, "cell_c": -74.0})
    )

    assert decision.decision_type == "handover"
    assert decision.selected_target_cell == "cell_c"
    assert decision.confidence is None
    assert "selected_margin_db" in decision.debug


def test_does_not_trigger_before_time_to_trigger_is_satisfied():
    policy = FixedA3Policy(A3Parameters(hysteresis_db=1.0, time_to_trigger_s=2.0))

    first = policy.decide(snapshot(0.0, -85.0, {"cell_b": -80.0}))
    second = policy.decide(snapshot(1.0, -85.0, {"cell_b": -80.0}))

    assert first.decision_type == "stay"
    assert second.decision_type == "stay"
    assert second.reason == "time_to_trigger_pending"
    assert second.time_to_trigger_state["cell_b"]["elapsed_s"] == 1.0


def test_triggers_after_time_to_trigger_is_satisfied():
    policy = FixedA3Policy(A3Parameters(hysteresis_db=1.0, time_to_trigger_s=2.0))

    policy.decide(snapshot(0.0, -85.0, {"cell_b": -80.0}))
    decision = policy.decide(snapshot(2.0, -85.0, {"cell_b": -80.0}))

    assert decision.decision_type == "handover"
    assert decision.selected_target_cell == "cell_b"
    assert decision.time_to_trigger_state["cell_b"]["satisfied"] is True


def test_hysteresis_changes_decision_boundary():
    permissive = FixedA3Policy(A3Parameters(hysteresis_db=1.0, time_to_trigger_s=0.0))
    conservative = FixedA3Policy(A3Parameters(hysteresis_db=3.0, time_to_trigger_s=0.0))
    sample = snapshot(0.0, -80.0, {"cell_b": -78.0})

    assert permissive.decide(sample).decision_type == "handover"
    assert conservative.decide(sample).decision_type == "stay"


def test_cooldown_prevents_immediate_ping_pong():
    policy = FixedA3Policy(
        A3Parameters(hysteresis_db=1.0, time_to_trigger_s=0.0, cooldown_s=10.0)
    )

    first = policy.decide(snapshot(0.0, -85.0, {"cell_b": -80.0}))
    assert first.decision_type == "handover"

    reverse = policy.decide(
        snapshot(
            1.0,
            -85.0,
            {"cell_a": -80.0},
            serving_cell="cell_b",
        )
    )

    assert reverse.decision_type == "stay"
    assert reverse.cooldown_state["active"] is True
    assert "cooldown_active" in reverse.reason


@pytest.mark.parametrize(
    "kwargs",
    [
        {"a3_offset_db": 25.0},
        {"hysteresis_db": -1.0},
        {"time_to_trigger_s": -0.1},
        {"cooldown_s": -1.0},
        {"minimum_neighbour_rsrp_dbm": -200.0},
    ],
)
def test_invalid_parameters_are_rejected(kwargs):
    with pytest.raises(ValueError):
        A3Parameters(**kwargs)


def test_policy_output_has_explainable_schema():
    policy = FixedA3Policy(A3Parameters(hysteresis_db=3.0, time_to_trigger_s=0.0))

    decision = policy.decide(snapshot(0.0, -85.0, {"cell_b": -80.0}))

    assert isinstance(decision, PolicyDecision)
    as_dict = decision.to_dict()
    assert as_dict["ue_id"] == "ue-1"
    assert as_dict["policy_name"] == "fixed_a3_baseline"
    assert "reason" in as_dict
    assert "debug" in as_dict
    assert "time_to_trigger_state" in as_dict
    assert "cooldown_state" in as_dict
