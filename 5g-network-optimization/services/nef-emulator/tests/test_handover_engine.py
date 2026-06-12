from datetime import datetime, timedelta

import logging
import requests
import pytest
from backend.app.app.handover.engine import HandoverEngine
from backend.app.app.network.state_manager import NetworkStateManager
from backend.app.app.monitoring import metrics

# Import shared fixtures from conftest (#59, #96)
from tests.conftest import DummyAntenna, patch_handover_time


@pytest.mark.asyncio
async def test_websocket_auth_requires_token():
    from backend.app.app.api.websocket_auth import require_websocket_user

    class DummyWebSocket:
        query_params = {}

        def __init__(self):
            self.closed = None

        async def close(self, code):
            self.closed = code

    websocket = DummyWebSocket()

    assert await require_websocket_user(websocket) is False
    assert websocket.closed == 1008


def test_rule_based_handover(monkeypatch):
    base = datetime(2025, 1, 1)
    times = [base, base + timedelta(seconds=1.1)]
    patch_handover_time(monkeypatch, times)

    nsm = NetworkStateManager()
    nsm.antenna_list = {"A": DummyAntenna(-80), "B": DummyAntenna(-76)}
    nsm.ue_states = {"u1": {"position": (0, 0, 0), "connected_to": "A"}}

    eng = HandoverEngine(nsm, use_ml=False, a3_hysteresis_db=3.0, a3_ttt_s=1.0)
    assert eng.decide_and_apply("u1") is None
    ev = eng.decide_and_apply("u1")
    assert ev and nsm.ue_states["u1"]["connected_to"] == "B"


def test_rule_based_handover_already_connected(monkeypatch):
    base = datetime(2025, 1, 1)
    times = [base, base + timedelta(seconds=1.1)]
    patch_handover_time(monkeypatch, times)

    nsm = NetworkStateManager()
    # UE is already connected to the best antenna ('B')
    nsm.antenna_list = {"A": DummyAntenna(-80), "B": DummyAntenna(-70)}
    nsm.ue_states = {"u1": {"position": (0, 0, 0), "connected_to": "B"}}

    eng = HandoverEngine(nsm, use_ml=False, a3_hysteresis_db=3.0, a3_ttt_s=1.0)
    assert eng.decide_and_apply("u1") is None


def test_rule_based_handover_no_eligible_antennas(monkeypatch):
    base = datetime(2025, 1, 1)
    times = [base, base + timedelta(seconds=1.1)]
    patch_handover_time(monkeypatch, times)

    nsm = NetworkStateManager()
    # Only one antenna, so no eligible neighbors
    nsm.antenna_list = {"A": DummyAntenna(-80)}
    nsm.ue_states = {"u1": {"position": (0, 0, 0), "connected_to": "A"}}

    eng = HandoverEngine(nsm, use_ml=False, a3_hysteresis_db=3.0, a3_ttt_s=1.0)
    assert eng.decide_and_apply("u1") is None


def test_rule_based_handover_invalid_ue(monkeypatch):
    base = datetime(2025, 1, 1)
    times = [base, base + timedelta(seconds=1.1)]
    patch_handover_time(monkeypatch, times)

    nsm = NetworkStateManager()
    nsm.antenna_list = {"A": DummyAntenna(-80), "B": DummyAntenna(-76)}
    nsm.ue_states = {"u1": {"position": (0, 0, 0), "connected_to": "A"}}

    eng = HandoverEngine(nsm, use_ml=False, a3_hysteresis_db=3.0, a3_ttt_s=1.0)
    with pytest.raises(KeyError):
        eng.decide_and_apply("u2")


def test_ml_handover(monkeypatch):
    class DummyResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "predicted_antenna": "B",
                "confidence": 0.77,
                "anti_pingpong_applied": True,
                "suppression_reason": "too_recent",
                "raw_ml_prediction": "B",
            }

    def fake_post(url, json=None, timeout=None):
        return DummyResp()

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setenv("ML_SERVICE_URL", "http://ml")

    nsm = NetworkStateManager()
    nsm.antenna_list = {"A": DummyAntenna(-80), "B": DummyAntenna(-76)}
    nsm.ue_states = {"u1": {"position": (0, 0, 0), "connected_to": "A", "speed": 0.0}}

    eng = HandoverEngine(nsm, use_ml=True, confidence_threshold=0.0)
    ev = eng.decide_and_apply("u1")
    assert ev and ev["to"] == "B"


def test_engine_mode_env(monkeypatch):
    """Environment variable should control ML mode when use_ml is None."""

    monkeypatch.setenv("ML_HANDOVER_ENABLED", "1")
    nsm = NetworkStateManager()
    eng = HandoverEngine(nsm)
    assert eng.use_ml is True

    monkeypatch.setenv("ML_HANDOVER_ENABLED", "0")
    eng = HandoverEngine(nsm)
    assert eng.use_ml is False
    monkeypatch.delenv("ML_HANDOVER_ENABLED", raising=False)


def test_engine_mode_auto_based_on_antennas():
    """When not specified, engine uses ML if enough antennas are present."""

    nsm = NetworkStateManager()
    # 3 antennas -> ML enabled by default
    nsm.antenna_list = {chr(65 + i): DummyAntenna(-80 + i) for i in range(3)}
    eng = HandoverEngine(nsm, use_ml=None, min_antennas_ml=3)
    assert eng.use_ml is True

    # Fewer antennas -> rule based
    nsm2 = NetworkStateManager()
    nsm2.antenna_list = {"A": DummyAntenna(-80)}
    eng2 = HandoverEngine(nsm2, use_ml=None, min_antennas_ml=3)
    assert eng2.use_ml is False


def test_engine_mode_explicit_overrides_env(monkeypatch):
    """Explicit use_ml parameter should override environment variable."""

    monkeypatch.setenv("ML_HANDOVER_ENABLED", "0")
    nsm = NetworkStateManager()
    eng = HandoverEngine(nsm, use_ml=True)
    assert eng.use_ml is True
    monkeypatch.delenv("ML_HANDOVER_ENABLED", raising=False)


def test_engine_auto_switch_runtime(monkeypatch):
    """Engine should switch modes automatically when antenna count changes."""

    nsm = NetworkStateManager()
    # Start with a single antenna -> rule mode
    nsm.antenna_list = {"A": DummyAntenna(-80)}
    eng = HandoverEngine(nsm, use_ml=None, min_antennas_ml=3)
    assert eng.use_ml is False

    # Add antennas so threshold is met
    nsm.antenna_list["B"] = DummyAntenna(-70)
    nsm.antenna_list["C"] = DummyAntenna(-75)
    eng._update_mode()
    assert eng.use_ml is True

    # Remove antennas so threshold is no longer met
    del nsm.antenna_list["B"]
    del nsm.antenna_list["C"]
    eng._update_mode()
    assert eng.use_ml is False


def test_decide_with_features_pure_ml_does_not_fallback(monkeypatch):
    nsm = NetworkStateManager()
    nsm.antenna_list = {"A": DummyAntenna(-80), "B": DummyAntenna(-70)}
    eng = HandoverEngine(nsm, use_ml=True)
    eng.handover_mode = "ml"

    monkeypatch.setattr(eng, "_select_ml_with_features", lambda ue_id, fv: None)

    def fail_rule(*args, **kwargs):
        raise AssertionError("pure ML mode must not call A3 fallback")

    monkeypatch.setattr(eng, "_select_rule_with_features", fail_rule)

    assert eng.decide_with_features("u1", {"connected_to": "A"}) is None


def test_decide_with_features_hybrid_records_fallback(monkeypatch):
    nsm = NetworkStateManager()
    nsm.antenna_list = {"A": DummyAntenna(-80), "B": DummyAntenna(-70)}
    eng = HandoverEngine(nsm, use_ml=True)
    eng.handover_mode = "hybrid"
    eng._last_ml_error_reason = "ml_http_5xx"

    monkeypatch.setattr(eng, "_select_ml_with_features", lambda ue_id, fv: None)
    monkeypatch.setattr(eng, "_select_rule_with_features", lambda ue_id, fv: "B")

    decision = eng.decide_with_features("u1", {"connected_to": "A"})

    assert decision == {
        "antenna_id": "B",
        "source": "a3_fallback",
        "fallback_to_a3": True,
        "fallback_reason": "ml_http_5xx",
    }


def test_decide_with_features_hybrid_low_confidence_fallback(monkeypatch):
    nsm = NetworkStateManager()
    nsm.antenna_list = {"A": DummyAntenna(-80), "B": DummyAntenna(-70)}
    eng = HandoverEngine(nsm, use_ml=True, confidence_threshold=0.8)
    eng.handover_mode = "hybrid"

    monkeypatch.setattr(
        eng,
        "_select_ml_with_features",
        lambda ue_id, fv: {"antenna_id": "C", "confidence": 0.2, "source": "ml_remote"},
    )
    monkeypatch.setattr(eng, "_select_rule_with_features", lambda ue_id, fv: "B")

    decision = eng.decide_with_features("u1", {"connected_to": "A"})

    assert decision["antenna_id"] == "B"
    assert decision["source"] == "a3_fallback"
    assert decision["fallback_to_a3"] is True
    assert decision["fallback_reason"] == "low_confidence"
    assert decision["ml_prediction"] == "C"


def test_fixed_a3_baseline_mode_uses_baseline_service(monkeypatch):
    """Live fixed baseline mode should delegate to handover-baseline-service."""

    def fail_internal_a3(*args, **kwargs):
        raise AssertionError("fixed_a3_baseline must not call NEF internal A3")

    base = datetime(2025, 1, 1)
    times = iter([base, base + timedelta(seconds=1.1)])

    nsm = NetworkStateManager()
    nsm.antenna_list = {"A": DummyAntenna(-80), "B": DummyAntenna(-75)}
    nsm.ue_states = {"u1": {"position": (0, 0, 0), "connected_to": "A"}}

    eng = HandoverEngine(nsm, use_ml=False, clock=lambda: next(times))
    eng.handover_mode = "fixed_a3_baseline"
    eng._auto = False
    monkeypatch.setattr(eng, "_select_rule_with_features", fail_internal_a3)

    features = {
        "ue_id": "u1",
        "connected_to": "A",
        "neighbor_rsrp_dbm": {"A": -80.0, "B": -75.0},
        "neighbor_rsrqs": {"A": -10.0, "B": -9.0},
        "neighbor_sinrs": {"A": 5.0, "B": 8.0},
    }

    assert eng.evaluate_and_apply_handover("u1", features=features) is None
    result = eng.evaluate_and_apply_handover("u1", features=features)

    assert result and result["to"] == "B"
    assert nsm.ue_states["u1"]["connected_to"] == "B"


def test_tuned_a3_baseline_mode_requires_real_config(monkeypatch):
    monkeypatch.delenv("TUNED_A3_CONFIG_PATH", raising=False)

    nsm = NetworkStateManager()
    nsm.antenna_list = {"A": DummyAntenna(-80), "B": DummyAntenna(-75)}
    nsm.ue_states = {"u1": {"position": (0, 0, 0), "connected_to": "A"}}

    eng = HandoverEngine(nsm, use_ml=False)
    eng.handover_mode = "tuned_a3_baseline"
    eng._auto = False

    with pytest.raises(RuntimeError, match="TUNED_A3_CONFIG_PATH"):
        eng.evaluate_and_apply_handover(
            "u1",
            features={
                "ue_id": "u1",
                "connected_to": "A",
                "neighbor_rsrp_dbm": {"A": -80.0, "B": -75.0},
            },
        )


def test_tuned_a3_baseline_mode_uses_saved_selected_parameters(tmp_path, monkeypatch):
    config_path = tmp_path / "tuned_a3.json"
    config_path.write_text(
        """
        {
          "selected_parameters": {
            "a3_offset_db": 0.0,
            "hysteresis_db": 1.0,
            "time_to_trigger_s": 0.0,
            "cooldown_s": 0.0
          }
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.setenv("TUNED_A3_CONFIG_PATH", str(config_path))

    nsm = NetworkStateManager()
    nsm.antenna_list = {"A": DummyAntenna(-80), "B": DummyAntenna(-78)}
    nsm.ue_states = {"u1": {"position": (0, 0, 0), "connected_to": "A"}}

    eng = HandoverEngine(nsm, use_ml=False)
    eng.handover_mode = "tuned_a3_baseline"
    eng._auto = False

    result = eng.evaluate_and_apply_handover(
        "u1",
        features={
            "ue_id": "u1",
            "connected_to": "A",
            "neighbor_rsrp_dbm": {"A": -80.0, "B": -78.0},
        },
    )

    assert result and result["to"] == "B"


def test_pure_ml_mode_records_qos_compliance_without_a3_fallback(monkeypatch):
    nsm = NetworkStateManager()
    nsm.antenna_list = {"A": DummyAntenna(-80), "B": DummyAntenna(-70)}
    nsm.ue_states = {
        "u1": {
            "position": (0, 0, 0),
            "connected_to": "A",
            "speed": 0.0,
            "observed_qos": {
                "sample_count": 1,
                "latest": {
                    "latency_ms": 20.0,
                    "throughput_mbps": 10.0,
                    "packet_loss_rate": 0.5,
                },
            },
        }
    }

    eng = HandoverEngine(nsm, use_ml=True)
    eng.handover_mode = "ml"

    monkeypatch.setattr(
        eng,
        "_select_ml_with_features",
        lambda ue_id, fv: {
            "antenna_id": "B",
            "confidence": 0.4,
            "source": "ml_remote",
            "qos_compliance": {
                "service_priority_ok": False,
                "required_confidence": 0.7,
                "observed_confidence": 0.4,
                "confidence_ok": False,
                "details": {
                    "service_type": "urllc",
                    "service_priority": 1,
                    "latency_requirement_ms": 10.0,
                    "throughput_requirement_mbps": 5.0,
                    "reliability_pct": 99.0,
                },
                "violations": [{"metric": "confidence"}],
                "metrics": {"latency": {"passed": False}},
            },
        },
    )

    def fail_rule(*args, **kwargs):
        raise AssertionError("pure ML mode must not call A3 fallback")

    monkeypatch.setattr(eng, "_select_rule_with_features", fail_rule)

    recorded_outcomes = []

    class DummyMetric:
        def labels(self, **labels):
            recorded_outcomes.append(labels["outcome"])
            return self

        def inc(self):
            return None

    monkeypatch.setattr(metrics, "HANDOVER_COMPLIANCE", DummyMetric())

    feedback = {}
    monkeypatch.setattr(
        eng,
        "_send_qos_feedback",
        lambda ue_id, decision_log, fv: feedback.setdefault("decision_log", decision_log),
    )

    result = eng.evaluate_and_apply_handover(
        "u1",
        features={
            "ue_id": "u1",
            "connected_to": "A",
            "speed": 0.0,
            "observed_qos": nsm.ue_states["u1"]["observed_qos"],
        },
    )

    assert result and result["to"] == "B"
    assert recorded_outcomes == ["failed"]
    decision_log = feedback["decision_log"]
    assert decision_log["handover_mode"] == "ml"
    assert decision_log["qos_compliance"]["checked"] is True
    assert decision_log["qos_compliance"]["passed"] is False
    assert decision_log["qos_compliance"]["service_type"] == "urllc"
    assert "fallback_to_a3" not in decision_log


def test_trace_capture_mode_does_not_call_policy_or_apply(monkeypatch, caplog):
    nsm = NetworkStateManager()
    nsm.antenna_list = {"A": DummyAntenna(-80), "B": DummyAntenna(-70)}
    nsm.ue_states = {"u1": {"position": (0, 0, 0), "connected_to": "A", "speed": 0.0}}

    eng = HandoverEngine(nsm, use_ml=False)
    eng.handover_mode = "trace_capture"
    eng._auto = False

    def fail_policy(*args, **kwargs):
        raise AssertionError("trace_capture must not call any handover policy")

    monkeypatch.setattr(eng, "_select_ml_with_features", fail_policy)
    monkeypatch.setattr(eng, "_select_rule_with_features", fail_policy)
    monkeypatch.setattr(eng, "_select_baseline_with_features", fail_policy)
    monkeypatch.setattr(nsm, "apply_handover_decision", fail_policy)

    features = {
        "ue_id": "u1",
        "connected_to": "A",
        "speed": 0.0,
        "latitude": 0.0,
        "longitude": 0.0,
        "neighbor_rsrp_dbm": {"A": -80.0, "B": -70.0},
    }

    with caplog.at_level(logging.INFO, logger="HandoverEngine"):
        assert eng.decide_with_features("u1", features) is None
        assert eng.evaluate_and_apply_handover("u1", features=features) is None

    assert nsm.ue_states["u1"]["connected_to"] == "A"
    assert "trace_capture_no_decision" in caplog.text


def test_select_ml(monkeypatch):
    """_select_ml returns predicted antenna based on features."""
    fv = {
        "ue_id": "u1",
        "latitude": 0,
        "longitude": 0,
        "connected_to": "A",
        "neighbor_rsrp_dbm": {"A": -80, "B": -70},
        "neighbor_sinrs": {"A": 10, "B": 15},
        "neighbor_rsrqs": {"A": -5, "B": -8},
        "neighbor_cell_loads": {"A": 1, "B": 3},
        "speed": 0.0,
        "direction": (1.0, 0.0, 0.0),
        "handover_count": 2,
        "time_since_handover": 11.0,
        "service_type": "urllc",
        "service_priority": 9,
        "qos_requirements": {"latency_requirement_ms": 5.0},
        "observed_qos": {
            "latest": {
                "latency_ms": 4.0,
                "jitter_ms": 0.5,
                "throughput_mbps": 50.0,
                "packet_loss_rate": 0.0,
                "timestamp": 123.0,
            }
        },
    }

    class DummyStateMgr:
        def __init__(self):
            self.fv = fv
            self.antenna_list = {
                aid: DummyAntenna(-80) for aid in fv["neighbor_rsrp_dbm"]
            }

        def get_feature_vector(self, ue_id):
            assert ue_id == "u1"
            return self.fv

    class DummyResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "predicted_antenna": "B",
                "confidence": 0.77,
                "anti_pingpong_applied": True,
                "suppression_reason": "too_recent",
            }

    sent = {}

    def fake_post(url, json=None, timeout=None):
        sent["data"] = json
        return DummyResp()

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setenv("ML_SERVICE_URL", "http://ml")

    sm = DummyStateMgr()
    eng = HandoverEngine(sm, use_ml=True)
    pred = eng._select_ml("u1")
    assert pred["antenna_id"] == "B"
    assert pred["confidence"] == 0.77
    assert pred.get("qos_compliance") is None
    assert pred["anti_pingpong_applied"] is True
    assert pred["suppression_reason"] == "too_recent"
    assert pred["raw_ml_prediction"] == "B"
    assert sent["data"]["rf_metrics"] == {
        "A": {"rsrp": -80, "sinr": 10, "rsrq": -5, "cell_load": 1},
        "B": {"rsrp": -70, "sinr": 15, "rsrq": -8, "cell_load": 3},
    }
    assert sent["data"]["service_type"] == "urllc"
    assert sent["data"]["service_priority"] == 9
    assert sent["data"]["handover_count"] == 2
    assert sent["data"]["time_since_handover"] == 11.0
    assert sent["data"]["qos_requirements"] == {"latency_requirement_ms": 5.0}
    assert sent["data"]["observed_qos"] == {
        "latency_ms": 4.0,
        "jitter_ms": 0.5,
        "throughput_mbps": 50.0,
        "packet_loss_rate": 0.0,
    }


def test_complexity_aware_mode_routes_sparse_to_tuned_a3(monkeypatch):
    nsm = NetworkStateManager()
    nsm.antenna_list = {"A": DummyAntenna(-80), "B": DummyAntenna(-75)}
    eng = HandoverEngine(nsm, use_ml=True)
    eng.handover_mode = "complexity_aware_ml_a3"
    eng._auto = False

    def fail_ml(*args, **kwargs):
        raise AssertionError("sparse complexity must not call ML")

    def fake_baseline(ue_id, fv, mode, decision_time):
        assert mode == "tuned_a3_baseline"
        return {"antenna_id": "B", "source": mode, "fallback_to_a3": False}

    monkeypatch.setattr(eng, "_select_ml_with_features", fail_ml)
    monkeypatch.setattr(eng, "_select_baseline_with_features", fake_baseline)

    decision = eng.decide_with_features(
        "u1",
        {
            "connected_to": "A",
            "neighbor_rsrp_dbm": {"A": -80.0, "B": -75.0},
            "neighbor_sinrs": {"B": 8.0},
        },
    )

    assert decision["antenna_id"] == "B"
    assert decision["decision_source"] == "a3_complexity_gate"
    assert decision["delegated_policy"] == "tuned_a3_baseline"
    assert decision["candidate_complexity"]["complexity_bucket"] == "sparse"


def test_complexity_aware_mode_routes_high_complexity_to_ml(monkeypatch):
    nsm = NetworkStateManager()
    nsm.antenna_list = {
        "A": DummyAntenna(-80),
        "B": DummyAntenna(-75),
        "C": DummyAntenna(-76),
        "D": DummyAntenna(-77),
    }
    eng = HandoverEngine(nsm, use_ml=True)
    eng.handover_mode = "complexity_aware_ml_a3"
    eng._auto = False

    def fail_baseline(*args, **kwargs):
        raise AssertionError("high complexity must not call tuned A3")

    monkeypatch.setattr(
        eng,
        "_select_ml_with_features",
        lambda ue_id, fv: {"antenna_id": "C", "confidence": 0.9, "source": "ml_remote"},
    )
    monkeypatch.setattr(eng, "_select_baseline_with_features", fail_baseline)

    decision = eng.decide_with_features(
        "u1",
        {
            "connected_to": "A",
            "neighbor_rsrp_dbm": {
                "A": -80.0,
                "B": -75.0,
                "C": -76.0,
                "D": -77.0,
            },
            "neighbor_sinrs": {"B": 8.0, "C": 9.0, "D": 10.0},
        },
    )

    assert decision["antenna_id"] == "C"
    assert decision["decision_source"] == "ml_high_complexity"
    assert decision["delegated_policy"] == "ml_policy"
    assert decision["fallback_to_a3"] is False
    assert decision["candidate_complexity"]["complexity_bucket"] == "high"


def test_select_ml_local(monkeypatch):
    """_select_ml should use local model when enabled."""
    fv = {
        "ue_id": "u1",
        "latitude": 0,
        "longitude": 0,
        "connected_to": "A",
        "neighbor_rsrp_dbm": {"A": -80, "B": -70},
        "neighbor_sinrs": {"A": 10, "B": 15},
        "neighbor_rsrqs": {"A": -5, "B": -8},
        "speed": 0.0,
    }

    class DummyStateMgr:
        def __init__(self):
            self.fv = fv
            self.antenna_list = {
                aid: DummyAntenna(-80) for aid in fv["neighbor_rsrp_dbm"]
            }

        def get_feature_vector(self, ue_id):
            assert ue_id == "u1"
            return self.fv

    calls = {"post": 0, "load_model": 0}

    def fake_post(*a, **k):
        calls["post"] += 1
        raise AssertionError("HTTP request should not be made")

    class DummyModel:
        def extract_features(self, data, include_neighbors=True):
            calls["load_model"] += 1
            assert data["rf_metrics"] == {
                "A": {"rsrp": -80, "sinr": 10, "rsrq": -5},
                "B": {"rsrp": -70, "sinr": 15, "rsrq": -8},
            }
            return {"x": 1}

        def predict(self, features):
            assert features == {"x": 1}
            return {"antenna_id": "B"}

    monkeypatch.setattr("requests.post", fake_post)

    import types
    import sys

    model_mod = types.ModuleType("ml_service.app.api_lib")
    model_mod.load_model = lambda p=None: DummyModel()
    app_pkg = types.ModuleType("ml_service.app")
    app_pkg.api_lib = model_mod
    ml_pkg = types.ModuleType("ml_service")
    ml_pkg.app = app_pkg

    monkeypatch.setitem(sys.modules, "ml_service", ml_pkg)
    monkeypatch.setitem(sys.modules, "ml_service.app", app_pkg)
    monkeypatch.setitem(sys.modules, "ml_service.app.api_lib", model_mod)

    sm = DummyStateMgr()
    eng = HandoverEngine(sm, use_ml=True, use_local_ml=True, ml_model_path="foo")
    pred = eng._select_ml("u1")
    assert pred["antenna_id"] == "B"
    assert pred["confidence"] is None
    assert pred.get("qos_compliance") is None
    assert calls["post"] == 0


def test_select_ml_http_error_logged(monkeypatch, caplog):
    """_select_ml should log and return None on HTTP failures."""
    fv = {
        "ue_id": "u1",
        "latitude": 0,
        "longitude": 0,
        "connected_to": "A",
        "neighbor_rsrp_dbm": {"A": -80, "B": -70},
        "neighbor_sinrs": {"A": 10, "B": 15},
        "speed": 0.0,
    }

    class DummyStateMgr:
        def __init__(self):
            self.fv = fv
            self.antenna_list = {
                aid: DummyAntenna(-80) for aid in fv["neighbor_rsrp_dbm"]
            }
            self.logger = logging.getLogger("test")

        def get_feature_vector(self, ue_id):
            assert ue_id == "u1"
            return self.fv

    def fake_post(*a, **k):
        raise requests.exceptions.RequestException("boom")

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setenv("ML_SERVICE_URL", "http://ml")

    sm = DummyStateMgr()
    eng = HandoverEngine(sm, use_ml=True)
    caplog.set_level(logging.WARNING)
    assert eng._select_ml("u1") is None
    assert any("Remote ML request failed" in rec.getMessage() for rec in caplog.records)


def test_select_ml_remote_unexpected_error_logged(monkeypatch, caplog):
    """Unexpected errors from the ML service should be logged."""
    fv = {
        "ue_id": "u1",
        "latitude": 0,
        "longitude": 0,
        "connected_to": "A",
        "neighbor_rsrp_dbm": {"A": -80, "B": -70},
        "neighbor_sinrs": {"A": 10, "B": 15},
        "speed": 0.0,
    }

    class DummyStateMgr:
        def __init__(self):
            self.fv = fv
            self.antenna_list = {
                aid: DummyAntenna(-80) for aid in fv["neighbor_rsrp_dbm"]
            }
            self.logger = logging.getLogger("test")

        def get_feature_vector(self, ue_id):
            assert ue_id == "u1"
            return self.fv

    def fake_post(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setenv("ML_SERVICE_URL", "http://ml")

    sm = DummyStateMgr()
    eng = HandoverEngine(sm, use_ml=True)
    caplog.set_level(logging.ERROR)
    assert eng._select_ml("u1") is None
    assert any("Remote ML request failed" in rec.getMessage() for rec in caplog.records)


def test_select_ml_local_error_logged(monkeypatch, caplog):
    """Local model errors should be logged."""
    fv = {
        "ue_id": "u1",
        "latitude": 0,
        "longitude": 0,
        "connected_to": "A",
        "neighbor_rsrp_dbm": {"A": -80, "B": -70},
        "neighbor_sinrs": {"A": 10, "B": 15},
        "speed": 0.0,
    }

    class DummyStateMgr:
        def __init__(self):
            self.fv = fv
            self.antenna_list = {
                aid: DummyAntenna(-80) for aid in fv["neighbor_rsrp_dbm"]
            }
            self.logger = logging.getLogger("test")

        def get_feature_vector(self, ue_id):
            assert ue_id == "u1"
            return self.fv

    def fake_post(*a, **k):
        raise AssertionError("HTTP request should not be made")

    class DummyModel:
        def extract_features(self, data, include_neighbors=True):
            raise ValueError("bad features")

        def predict(self, features):
            return {"antenna_id": "B"}

    monkeypatch.setattr("requests.post", fake_post)

    import types
    import sys

    model_mod = types.ModuleType("ml_service.app.api_lib")
    model_mod.load_model = lambda p=None: DummyModel()
    app_pkg = types.ModuleType("ml_service.app")
    app_pkg.api_lib = model_mod
    ml_pkg = types.ModuleType("ml_service")
    ml_pkg.app = app_pkg

    monkeypatch.setitem(sys.modules, "ml_service", ml_pkg)
    monkeypatch.setitem(sys.modules, "ml_service.app", app_pkg)
    monkeypatch.setitem(sys.modules, "ml_service.app.api_lib", model_mod)

    sm = DummyStateMgr()
    eng = HandoverEngine(sm, use_ml=True, use_local_ml=True, ml_model_path="foo")
    caplog.set_level(logging.WARNING)
    assert eng._select_ml("u1") is None
    assert any(
        "Local ML prediction failed" in rec.getMessage() for rec in caplog.records
    )


def test_select_ml_local_unexpected_error_logged(monkeypatch, caplog):
    """Unexpected errors in local model should be logged."""
    fv = {
        "ue_id": "u1",
        "latitude": 0,
        "longitude": 0,
        "connected_to": "A",
        "neighbor_rsrp_dbm": {"A": -80, "B": -70},
        "neighbor_sinrs": {"A": 10, "B": 15},
        "speed": 0.0,
    }

    class DummyStateMgr:
        def __init__(self):
            self.fv = fv
            self.antenna_list = {
                aid: DummyAntenna(-80) for aid in fv["neighbor_rsrp_dbm"]
            }
            self.logger = logging.getLogger("test")

        def get_feature_vector(self, ue_id):
            assert ue_id == "u1"
            return self.fv

    def fake_post(*a, **k):
        raise AssertionError("HTTP request should not be made")

    class DummyModel:
        def extract_features(self, data, include_neighbors=True):
            return {}

        def predict(self, features):
            raise RuntimeError("fail")

    monkeypatch.setattr("requests.post", fake_post)

    import types
    import sys

    model_mod = types.ModuleType("ml_service.app.api_lib")
    model_mod.load_model = lambda p=None: DummyModel()
    app_pkg = types.ModuleType("ml_service.app")
    app_pkg.api_lib = model_mod
    ml_pkg = types.ModuleType("ml_service")
    ml_pkg.app = app_pkg

    monkeypatch.setitem(sys.modules, "ml_service", ml_pkg)
    monkeypatch.setitem(sys.modules, "ml_service.app", app_pkg)
    monkeypatch.setitem(sys.modules, "ml_service.app.api_lib", model_mod)

    sm = DummyStateMgr()
    eng = HandoverEngine(sm, use_ml=True, use_local_ml=True, ml_model_path="foo")
    caplog.set_level(logging.ERROR)
    assert eng._select_ml("u1") is None
    assert any(
        "Local ML prediction failed" in rec.getMessage() for rec in caplog.records
    )


def test_select_rule(monkeypatch):
    """_select_rule uses rule object to pick the target antenna."""
    fv = {
        "ue_id": "u1",
        "latitude": 0,
        "longitude": 0,
        "connected_to": "A",
        "neighbor_rsrp_dbm": {"A": -80, "B": -70},
        "neighbor_sinrs": {},
    }

    class DummyStateMgr:
        def __init__(self):
            self.fv = fv
            self.antenna_list = {
                aid: DummyAntenna(-80) for aid in fv["neighbor_rsrp_dbm"]
            }

        def get_feature_vector(self, ue_id):
            assert ue_id == "u1"
            return self.fv

    class DummyRule:
        def check(self, serv, targ, now):
            assert serv == -80 and targ == -70
            return True

    sm = DummyStateMgr()
    eng = HandoverEngine(sm, use_ml=False)
    eng.rule = DummyRule()
    assert eng._select_rule("u1") == "B"


def test_env_overrides_auto(monkeypatch):
    """ML_HANDOVER_ENABLED env var should override automatic mode selection."""

    # Env forces ML even though antenna count would disable it
    nsm = NetworkStateManager()
    nsm.antenna_list = {"A": DummyAntenna(-80)}
    monkeypatch.setenv("ML_HANDOVER_ENABLED", "1")
    eng = HandoverEngine(nsm, use_ml=None, min_antennas_ml=3)
    assert eng.use_ml is True

    # Env forces rule mode despite having many antennas
    nsm2 = NetworkStateManager()
    nsm2.antenna_list = {chr(65 + i): DummyAntenna(-80 + i) for i in range(3)}
    monkeypatch.setenv("ML_HANDOVER_ENABLED", "0")
    eng2 = HandoverEngine(nsm2, use_ml=None, min_antennas_ml=3)
    assert eng2.use_ml is False
    monkeypatch.delenv("ML_HANDOVER_ENABLED", raising=False)


def test_decide_and_apply_fallback(monkeypatch):
    """Engine should fall back to rule when confidence is low."""

    class DummyResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"predicted_antenna": "B", "confidence": 0.2}

    monkeypatch.setattr("requests.post", lambda *a, **k: DummyResp())
    monkeypatch.setenv("ML_SERVICE_URL", "http://ml")

    nsm = NetworkStateManager()
    nsm.antenna_list = {"A": DummyAntenna(-80), "B": DummyAntenna(-70)}
    nsm.ue_states = {"u1": {"position": (0, 0, 0), "connected_to": "A", "speed": 0.0}}

    count = {"val": 0}

    class DummyCounter:
        def inc(self):
            count["val"] += 1

    monkeypatch.setattr(metrics, "HANDOVER_FALLBACKS", DummyCounter())

    eng = HandoverEngine(nsm, use_ml=True, confidence_threshold=0.5)
    class DummyRule:
        def check(self, serv, targ, now):
            return True

    eng.rule = DummyRule()
    ev = eng.decide_and_apply("u1")
    assert ev and ev["to"] == "B"
    assert count["val"] == 1
