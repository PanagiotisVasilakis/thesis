"""Tests for enhanced experiment runner safety helpers."""

import json
import os

import pytest

from scripts.run_enhanced_experiment import (
    DOCKER_COMPOSE_CMD,
    LIVE_TUNED_A3_CONTAINER_CONFIG,
    apply_decision_log_metric_fallback,
    build_policy_run_plan,
    collect_decision_log_metrics,
    compose_file_args,
    compose_env_for_policy,
    ensure_clean_output_dir,
    load_env_file,
    normalize_runtime_env,
    parse_policy_list,
    run_experiment,
    stage_tuned_a3_config_for_live_run,
    validate_policy_requirements,
    wait_for_ml_model_ready,
    write_tuned_a3_compose_override,
)


def test_ensure_clean_output_dir_creates_missing_directory(tmp_path):
    output_dir = tmp_path / "fresh_run"

    assert ensure_clean_output_dir(output_dir) is True
    assert output_dir.is_dir()


def test_ensure_clean_output_dir_rejects_nonempty_directory(tmp_path, capsys):
    output_dir = tmp_path / "existing_run"
    output_dir.mkdir()
    (output_dir / "old_metrics.json").write_text("{}", encoding="utf-8")

    assert ensure_clean_output_dir(output_dir) is False

    captured = capsys.readouterr()
    assert "already exists and is not empty" in captured.out


def test_enhanced_runner_uses_docker_compose_plugin():
    assert DOCKER_COMPOSE_CMD == ["docker", "compose"]


def test_collect_decision_log_metrics_parses_handover_decisions(tmp_path):
    log_path = tmp_path / "ml_docker.log"
    first = {
        "outcome": "applied",
        "ml_confidence": 0.8,
        "ml_response": {"anti_pingpong_applied": True},
        "qos_compliance": {"checked": True, "passed": True},
    }
    second = {
        "outcome": "no_handover",
        "ml_confidence": 0.6,
        "qos_compliance": {"checked": True, "passed": False},
    }
    log_path.write_text(
        "\n".join(
            [
                "nef-1 | HANDOVER_DECISION: " + json.dumps(first),
                "nef-1 | HANDOVER_APPLIED: " + json.dumps(first),
                "nef-1 | HANDOVER_DECISION: " + json.dumps(second),
            ]
        ),
        encoding="utf-8",
    )

    metrics = collect_decision_log_metrics(log_path)

    assert metrics["total_handovers"] == 1.0
    assert metrics["skipped_handovers"] == 1.0
    assert metrics["pingpong_suppressions"] == 1.0
    assert metrics["qos_compliance_ok"] == 1.0
    assert metrics["qos_compliance_failed"] == 1.0
    assert metrics["avg_confidence"] == pytest.approx(0.7)


def test_decision_log_metric_fallback_resolves_missing_prometheus_series():
    metrics, warnings = apply_decision_log_metric_fallback(
        {
            "total_handovers": None,
            "avg_confidence": None,
            "qos_compliance_ok": 2.0,
        },
        [
            "Prometheus query returned no series for total_handovers",
            "Prometheus query returned no series for avg_confidence",
            "Prometheus query returned no series for qos_compliance_failed",
        ],
        {"total_handovers": 3.0, "avg_confidence": 0.5},
    )

    assert metrics["total_handovers"] == 3.0
    assert metrics["avg_confidence"] == 0.5
    assert metrics["qos_compliance_ok"] == 2.0
    assert warnings == ["Prometheus query returned no series for qos_compliance_failed"]


def test_final_run_model_ready_requires_complete_artifact_metadata(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"ready": True, "metadata": {"artifact_complete": False}}

    monkeypatch.setenv("THESIS_FINAL_RUN", "1")
    monkeypatch.setenv("ML_URL", "http://ml.local")
    monkeypatch.setattr("scripts.run_enhanced_experiment.time.sleep", lambda *_: None)
    monkeypatch.setattr(
        "requests.get",
        lambda *args, **kwargs: Response(),
    )

    assert wait_for_ml_model_ready(max_attempts=1) is False


def test_final_run_model_ready_accepts_complete_artifact_metadata(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"ready": True, "metadata": {"artifact_complete": True}}

    monkeypatch.setenv("THESIS_FINAL_RUN", "1")
    monkeypatch.setenv("ML_URL", "http://ml.local")
    monkeypatch.setattr(
        "requests.get",
        lambda *args, **kwargs: Response(),
    )

    assert wait_for_ml_model_ready(max_attempts=1) is True


def test_load_env_file_adds_missing_values_without_overriding_shell(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "# comment",
                "EXISTING=from_file",
                "NEF_HOST=localhost",
                "PROJECT_NAME=5G Network Optimization",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("EXISTING", "from_shell")
    monkeypatch.delenv("NEF_HOST", raising=False)
    monkeypatch.delenv("PROJECT_NAME", raising=False)

    load_env_file(env_file)

    assert os.environ["EXISTING"] == "from_shell"
    assert os.environ["NEF_HOST"] == "localhost"
    assert os.environ["PROJECT_NAME"] == "5G Network Optimization"


def test_normalize_runtime_env_sets_documented_local_urls(monkeypatch):
    for name in [
        "NEF_SCHEME",
        "NEF_HOST",
        "NEF_PORT",
        "NEF_URL",
        "ML_BASE_URL",
        "ML_URL",
        "PROMETHEUS_URL",
        "NGINX_HTTP",
        "NEF_USERNAME",
        "NEF_PASSWORD",
        "FIRST_SUPERUSER",
        "FIRST_SUPERUSER_PASSWORD",
    ]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NEF_PASSWORD", "change-me")
    monkeypatch.setenv("FIRST_SUPERUSER", "admin@example.com")
    monkeypatch.setenv("FIRST_SUPERUSER_PASSWORD", "real-local-password")

    normalize_runtime_env()

    assert os.environ["NEF_URL"] == "http://localhost:8080"
    assert os.environ["ML_URL"] == "http://localhost:5050"
    assert os.environ["PROMETHEUS_URL"] == "http://localhost:9090"
    assert os.environ["NEF_USERNAME"] == "admin@example.com"
    assert os.environ["NEF_PASSWORD"] == "real-local-password"


def test_normalize_runtime_env_rejects_stale_superuser_password(monkeypatch):
    for name in [
        "NEF_SCHEME",
        "NEF_HOST",
        "NEF_PORT",
        "NEF_URL",
        "ML_BASE_URL",
        "ML_URL",
        "PROMETHEUS_URL",
        "NEF_USERNAME",
        "NEF_PASSWORD",
        "FIRST_SUPERUSER",
        "FIRST_SUPERUSER_PASSWORD",
    ]:
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setenv("NEF_USERNAME", "admin@example.com")
    monkeypatch.setenv("NEF_PASSWORD", "stale-password")
    monkeypatch.setenv("FIRST_SUPERUSER", "admin@example.com")
    monkeypatch.setenv("FIRST_SUPERUSER_PASSWORD", "seeded-password")

    with pytest.raises(ValueError, match="NEF_PASSWORD differs"):
        normalize_runtime_env()


def test_parse_policy_list_defaults_and_explicit_values():
    assert parse_policy_list(None) == ["ml", "a3"]
    assert parse_policy_list(None, skip_a3=True) == ["ml"]
    assert parse_policy_list("ml,fixed_a3_baseline,tuned_a3_baseline") == [
        "ml",
        "fixed_a3_baseline",
        "tuned_a3_baseline",
    ]


def test_parse_policy_list_rejects_unknown_or_duplicate():
    with pytest.raises(ValueError, match="unsupported policy"):
        parse_policy_list("ml,unknown")

    with pytest.raises(ValueError, match="duplicate policies"):
        parse_policy_list("ml,ml")


def test_validate_policy_requirements_requires_real_tuned_config(monkeypatch):
    monkeypatch.delenv("TUNED_A3_CONFIG_PATH", raising=False)

    with pytest.raises(ValueError, match="tuned_a3_baseline requires"):
        validate_policy_requirements(["tuned_a3_baseline"])


def test_validate_policy_requirements_accepts_selected_parameters(tmp_path):
    config = tmp_path / "tuned.json"
    config.write_text(
        """
        {
          "selected_parameters": {
            "a3_offset_db": 0.0,
            "hysteresis_db": 2.0,
            "time_to_trigger_s": 1.0,
            "cooldown_s": 2.0
          }
        }
        """,
        encoding="utf-8",
    )

    assert validate_policy_requirements(
        ["fixed_a3_baseline", "tuned_a3_baseline"],
        tuned_a3_config=config,
    ) == config.resolve()


def test_build_policy_run_plan_marks_ml_requirement(tmp_path):
    config = tmp_path / "tuned.json"
    config.write_text(
        '{"selected_parameters":{"a3_offset_db":0,"hysteresis_db":1,'
        '"time_to_trigger_s":0,"cooldown_s":0}}',
        encoding="utf-8",
    )

    plan = build_policy_run_plan(
        scenario_name="highway",
        duration_minutes=10,
        seed=123,
        policies=["ml", "fixed_a3_baseline", "tuned_a3_baseline"],
        tuned_a3_config=config,
    )

    assert [entry.policy for entry in plan] == [
        "ml",
        "fixed_a3_baseline",
        "tuned_a3_baseline",
    ]
    assert plan[0].requires_ml_service is True
    assert plan[1].requires_ml_service is False
    assert plan[2].tuned_a3_config == str(config.resolve())


def test_compose_env_for_policy_keeps_baseline_out_of_ml_profile(monkeypatch):
    monkeypatch.setenv("COMPOSE_PROFILES", "ml")
    env = compose_env_for_policy("fixed_a3_baseline")

    assert env["COMPOSE_PROFILES"] == ""
    assert env["ML_HANDOVER_ENABLED"] == "0"


def test_compose_env_for_tuned_a3_uses_container_config_path(tmp_path):
    host_config = tmp_path / "tuned_a3_config.json"
    host_config.write_text("{}", encoding="utf-8")

    env = compose_env_for_policy("tuned_a3_baseline", tuned_a3_config=host_config)

    assert env["TUNED_A3_CONFIG_PATH"] == LIVE_TUNED_A3_CONTAINER_CONFIG
    assert str(host_config) not in env["TUNED_A3_CONFIG_PATH"]


def test_stage_tuned_a3_config_records_output_copy(tmp_path):
    source = tmp_path / "source_tuned.json"
    source.write_text(
        '{"selected_parameters":{"a3_offset_db":0,"hysteresis_db":1,'
        '"time_to_trigger_s":1,"cooldown_s":2},'
        '"evaluated_configuration_scores":[{"score":1}],'
        '"calibration":{"scenario":"highway"}}',
        encoding="utf-8",
    )
    plan = build_policy_run_plan(
        scenario_name="highway",
        duration_minutes=1,
        seed=42,
        policies=["ml", "tuned_a3_baseline"],
        tuned_a3_config=source,
    )

    staged = stage_tuned_a3_config_for_live_run(tmp_path / "run", plan)

    tuned_entry = [entry for entry in staged if entry.policy == "tuned_a3_baseline"][0]
    staged_path = tmp_path / "run" / "config" / "tuned_a3_config.json"
    assert tuned_entry.tuned_a3_config == str(staged_path.resolve())
    assert staged_path.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")


def test_write_tuned_a3_compose_override_mounts_staged_config(tmp_path):
    host_config = tmp_path / "run" / "config" / "tuned_a3_config.json"
    host_config.parent.mkdir(parents=True)
    host_config.write_text("{}", encoding="utf-8")

    override = write_tuned_a3_compose_override(tmp_path / "run", host_config)

    text = override.read_text(encoding="utf-8")
    assert "nef-emulator:" in text
    assert f"TUNED_A3_CONFIG_PATH={LIVE_TUNED_A3_CONTAINER_CONFIG}" in text
    assert str(host_config.resolve()) in text
    assert LIVE_TUNED_A3_CONTAINER_CONFIG in text


def test_compose_file_args_preserves_order(tmp_path):
    first = tmp_path / "docker-compose.yml"
    second = tmp_path / "override.yml"

    assert compose_file_args([first, second]) == [
        "-f",
        str(first),
        "-f",
        str(second),
    ]


def test_plan_only_writes_live_policy_plan(tmp_path, monkeypatch):
    monkeypatch.setenv("NEF_URL", "http://localhost:8080")
    monkeypatch.setenv("NEF_USERNAME", "admin@example.com")
    monkeypatch.setenv("NEF_PASSWORD", "real-local-password")

    output_dir = tmp_path / "plan_only"
    success = run_experiment(
        scenario_name="highway",
        duration_minutes=1,
        output_dir=output_dir,
        policies=["ml", "fixed_a3_baseline"],
        seed=77,
        plan_only=True,
    )

    assert success is True
    assert (output_dir / "live_experiment_plan.json").is_file()
    assert '"policy": "fixed_a3_baseline"' in (
        output_dir / "live_experiment_plan.json"
    ).read_text(encoding="utf-8")
