from scripts.policy_comparison.metrics import summarize_policy_decisions
from scripts.policy_comparison.schemas import PolicyDecisionRecord


def decision(
    step,
    serving,
    target=None,
    serving_rsrp=-85.0,
    target_rsrp=-78.0,
    debug=None,
):
    handover = target is not None
    return PolicyDecisionRecord(
        ue_id="ue-1",
        timestamp_s=float(step),
        step_index=step,
        current_serving_cell=serving,
        selected_target_cell=target,
        decision_type="handover" if handover else "stay",
        policy_name="test-policy",
        policy_parameters={},
        serving_measurement_value=serving_rsrp,
        neighbour_measurements_considered=(
            {target: target_rsrp} if target is not None else {"cell-b": target_rsrp}
        ),
        trigger_condition_result=handover,
        time_to_trigger_state={},
        cooldown_state={},
        reason="test",
        debug=debug or {},
        decision_latency_ms=2.0,
    )


def test_metrics_include_dwell_low_quality_and_target_quality():
    summary = summarize_policy_decisions(
        "test-policy",
        [
            decision(0, "cell-a", serving_rsrp=-112.0),
            decision(5, "cell-a", target="cell-b", serving_rsrp=-111.0),
            decision(8, "cell-b", serving_rsrp=-80.0),
            decision(10, "cell-b", target="cell-a", serving_rsrp=-79.0),
        ],
        low_quality_rsrp_floor_dbm=-110.0,
    )

    assert summary.handover_count == 2
    assert summary.stay_count == 2
    assert summary.low_quality_step_count == 2
    assert summary.avg_dwell_time_s == 5.0
    assert summary.avg_handover_target_rsrp_dbm == -78.0
    assert summary.avg_decision_latency_ms == 2.0
    assert summary.ping_pong_count == 1
    assert summary.per_ue["ue-1"]["low_quality_steps"] == 2
    assert summary.composite_cost > 0
    assert summary.complexity_bucket_counts == {"unknown": 4}


def test_metrics_include_thesis_proxy_counts_and_load_impact():
    summary = summarize_policy_decisions(
        "test-policy",
        [
            decision(
                0,
                "cell-a",
                serving_rsrp=-112.0,
                target_rsrp=-80.0,
                debug={"cell_loads": {"cell-a": 1.0, "cell-b": 2.0}},
            ),
            decision(
                1,
                "cell-a",
                target="cell-b",
                serving_rsrp=-85.0,
                target_rsrp=-86.0,
                debug={
                    "cell_loads": {"cell-a": 1.0, "cell-b": 3.0},
                    "qos_compliance": {
                        "checked": True,
                        "passed": False,
                        "violations": [{"metric": "latency_ms"}],
                    },
                },
            ),
            decision(
                2,
                "cell-b",
                target="cell-a",
                serving_rsrp=-80.0,
                target_rsrp=-116.0,
                debug={"cell_loads": {"cell-b": 3.0, "cell-a": 1.0}},
            ),
        ],
        low_quality_rsrp_floor_dbm=-110.0,
        rlf_rsrp_floor_dbm=-115.0,
    )

    assert summary.late_handover_proxy_count == 1
    assert summary.unnecessary_handover_count == 2
    assert summary.failed_handover_proxy_count == 1
    assert summary.qos_violation_proxy_count == 1
    assert summary.load_balance_regression_count == 1
    assert summary.avg_serving_load == 5 / 3
    assert summary.avg_handover_target_load == 2.0


def test_metrics_roll_up_cost_by_complexity_bucket():
    summary = summarize_policy_decisions(
        "test-policy",
        [
            decision(
                0,
                "cell-a",
                debug={
                    "candidate_complexity": {
                        "viable_candidate_count": 1,
                        "complexity_bucket": "sparse",
                    }
                },
            ),
            decision(
                1,
                "cell-a",
                target="cell-b",
                serving_rsrp=-112.0,
                target_rsrp=-116.0,
                debug={
                    "candidate_complexity": {
                        "viable_candidate_count": 3,
                        "complexity_bucket": "high",
                    },
                    "qos_compliance": {"passed": False},
                },
            ),
        ],
        low_quality_rsrp_floor_dbm=-110.0,
    )

    assert summary.complexity_bucket_counts == {"sparse": 1, "high": 1}
    assert summary.complexity_bucket_costs["high"] > summary.complexity_bucket_costs["sparse"]
    assert summary.complexity_high_composite_cost == summary.complexity_bucket_costs["high"]
    assert summary.complexity_sparse_composite_cost == summary.complexity_bucket_costs["sparse"]
    assert summary.complexity_moderate_composite_cost == 0.0
    assert summary.composite_cost == sum(summary.complexity_bucket_costs.values())


def test_metric_v2_scores_sinr_and_only_over_budget_latency():
    summary = summarize_policy_decisions(
        "test-policy",
        [
            decision(
                0,
                "cell-a",
                debug={"cell_sinrs": {"cell-a": -10.0, "cell-b": -8.0}},
            ),
            PolicyDecisionRecord(
                **{
                    **decision(
                        1,
                        "cell-a",
                        target="cell-b",
                        debug={"cell_sinrs": {"cell-a": -10.0, "cell-b": -8.0}},
                    ).to_dict(),
                    "decision_latency_ms": 20.0,
                }
            ),
        ],
        low_quality_sinr_floor_db=-5.0,
        decision_latency_budget_ms=10.0,
    )

    assert summary.composite_cost_version == "v2_rsrp_sinr_latency_budget"
    assert summary.low_sinr_step_count == 2
    assert summary.poor_handover_target_sinr_count == 1
    assert summary.latency_budget_violation_count == 1
    assert summary.avg_serving_sinr_db == -10.0
    assert summary.avg_handover_target_sinr_db == -8.0


def test_metric_v3_normalizes_rates_and_uses_environment_bucket():
    summary = summarize_policy_decisions(
        "test-policy",
        [
            decision(
                0,
                "cell-a",
                debug={
                    "candidate_complexity": {
                        "viable_candidate_count": 1,
                        "complexity_bucket": "sparse",
                        "environment_complexity_bucket": "high",
                    },
                    "cell_sinrs": {"cell-a": -10.0, "cell-b": 2.0},
                    "qos_compliance": {"passed": False},
                },
            ),
            decision(
                1,
                "cell-a",
                target="cell-b",
                debug={
                    "candidate_complexity": {
                        "viable_candidate_count": 1,
                        "complexity_bucket": "sparse",
                        "environment_complexity_bucket": "high",
                    },
                    "cell_sinrs": {"cell-a": -10.0, "cell-b": 2.0},
                },
            ),
        ],
        metric_version="v3_physical_qos_cost",
    )
    assert summary.composite_cost_version == "v3_physical_qos_cost"
    assert summary.complexity_bucket_counts == {"high": 2}
    assert summary.observation_time_ue_minutes > 0
    assert summary.handovers_per_ue_minute > 0
    assert summary.sinr_outage_fraction == 1.0
    assert summary.composite_cost_sensitivity["safety_heavy"] >= summary.composite_cost
