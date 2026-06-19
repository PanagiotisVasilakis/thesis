from scripts.policy_comparison.tune_segment_controller_replay_params import (
    _iter_configs,
    _stratified_sample,
    build_parser,
    normalize_entry_threshold_offset,
)


def test_entry_threshold_offsets_follow_written_percentage_point_grid():
    assert normalize_entry_threshold_offset(-5.0) == -0.05
    assert normalize_entry_threshold_offset(0.10) == 0.10


def test_default_segment_replay_tuner_grid_matches_plan():
    parser = build_parser()
    args = parser.parse_args(
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
    raw_offsets = {config["entry_threshold_offset_raw"] for config in configs}
    offsets = {round(config["entry_threshold_offset"], 2) for config in configs}
    thresholds = {round(config["entry_threshold"], 2) for config in configs}

    assert len(configs) == 207360
    assert raw_offsets == {-10.0, -5.0, 0.0, 5.0}
    assert offsets == {-0.10, -0.05, 0.0, 0.05}
    assert thresholds == {0.40, 0.45, 0.50, 0.55}
    assert {config["post_exit_a3_guard_s"] for config in configs} == {
        0.0,
        10.0,
        20.0,
        30.0,
    }
    assert {config["post_exit_a3_extra_margin_db"] for config in configs} == {
        0.0,
        3.0,
        6.0,
        9.0,
    }
    assert {config["high_reject_hold_s"] for config in configs} == {
        0.0,
        6.0,
        12.0,
        20.0,
    }


def test_staged_sampling_keeps_bounded_subset_and_last_config():
    configs = [(index, {"value": index}) for index in range(1, 101)]

    sampled = _stratified_sample(configs, max_count=10)

    assert len(sampled) == 10
    assert sampled[-1] == configs[-1]
