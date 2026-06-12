from scripts.policy_comparison.manifest import build_reproducibility_manifest


def test_manifest_records_git_state_without_environment_secrets():
    manifest = build_reproducibility_manifest(
        scenario="highway",
        seed=42,
        duration_s=60.0,
        tick_interval_s=1.0,
        topology_hash="hash",
        policies={
            "fixed_a3_baseline": {"hysteresis_db": 3.0},
            "ml_policy": {"endpoint": "/api/predict-with-qos"},
        },
    )

    payload = manifest.to_dict()

    assert payload["scenario"] == "highway"
    assert payload["seed"] == 42
    assert "policies" in payload
    assert "FIRST_SUPERUSER_PASSWORD" not in str(payload)
