from scripts.policy_comparison.tune_sparse_authority_replay_params import (
    _balanced_sample,
    _evaluate_config,
    _iter_configs,
    build_parser,
)


def test_sparse_authority_default_grid_covers_modes_and_thresholds():
    args = build_parser().parse_args(
        [
            "--calibration-trace",
            "calibration_seed51/trace.jsonl",
            "--tuned-a3-config",
            "tuned_a3_config.json",
            "--segment-artifact",
            "segment_controller.joblib",
            "--output-dir",
            "out",
        ]
    )

    configs = list(_iter_configs(args))

    assert len(configs) == 450
    assert {config["high_complexity_threshold"] for config in configs} == {3, 4}
    assert {config["sparse_authority_mode"] for config in configs} == {
        "tuned_a3",
        "quality_gated_a3",
        "stay_unless_weak",
    }


def test_balanced_sample_preserves_each_threshold_and_mode_group():
    configs = [
        (
            index,
            {
                "high_complexity_threshold": threshold,
                "sparse_authority_mode": mode,
            },
        )
        for index, (threshold, mode) in enumerate(
            [
                (threshold, mode)
                for threshold in (3, 4)
                for mode in ("tuned_a3", "quality_gated_a3", "stay_unless_weak")
                for _ in range(10)
            ],
            start=1,
        )
    ]

    sampled = _balanced_sample(configs, max_count=18)

    assert len(sampled) == 18
    assert {
        (item[1]["high_complexity_threshold"], item[1]["sparse_authority_mode"])
        for item in sampled
    } == {
        (threshold, mode)
        for threshold in (3, 4)
        for mode in ("tuned_a3", "quality_gated_a3", "stay_unless_weak")
    }


def seed_result(*, adaptive_cost: float, ml_cost: float) -> dict:
    return {
        "ok": True,
        "adaptive_high_cost": 10.0,
        "tuned_high_cost": 100.0,
        "high_improvement_fraction": 0.9,
        "adaptive_overall_cost": adaptive_cost,
        "ml_overall_cost": ml_cost,
        "tuned_overall_cost": 200.0,
        "adaptive_ping_pong": 0,
        "tuned_ping_pong": 1,
        "adaptive_unnecessary": 0,
        "tuned_unnecessary": 2,
        "adaptive_failed": 0,
        "adaptive_qos": 0,
        "tuned_qos": 0,
        "adaptive_rlf": 0,
        "tuned_rlf": 0,
        "adaptive_low_sinr": 0,
        "ml_low_sinr": 0,
        "tuned_low_sinr": 0,
        "adaptive_poor_target_sinr": 0,
        "ml_poor_target_sinr": 0,
        "adaptive_latency_budget_violations": 0,
        "ml_latency_budget_violations": 0,
        "adaptive_handovers": 1,
        "adaptive_sparse_suppressions": 5,
        "adaptive_sparse_handovers": 1,
    }


def test_calibration_gate_rejects_adaptive_that_loses_to_ml_only():
    evaluation = _evaluate_config(
        [
            seed_result(adaptive_cost=20.0, ml_cost=15.0),
            seed_result(adaptive_cost=14.0, ml_cost=15.0),
        ]
    )

    assert evaluation["pass"] is False
    assert evaluation["constraints"]["adaptive_beats_ml_every_seed"] is False


def test_calibration_gate_accepts_only_all_seed_ml_improvement():
    evaluation = _evaluate_config(
        [
            seed_result(adaptive_cost=14.0, ml_cost=15.0),
            seed_result(adaptive_cost=13.0, ml_cost=15.0),
        ]
    )

    assert evaluation["pass"] is True
    assert evaluation["constraints"]["adaptive_beats_ml_every_seed"] is True
