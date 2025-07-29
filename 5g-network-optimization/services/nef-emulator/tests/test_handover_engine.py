from datetime import datetime, timedelta

import logging
import requests
import pytest
from backend.app.app.handover.engine import HandoverEngine
from backend.app.app.network.state_manager import NetworkStateManager


class DummyAntenna:
    def __init__(self, rsrp):
        self._rsrp = rsrp

    def rsrp_dbm(self, pos):
        return self._rsrp


def patch_time(monkeypatch, times):
    import backend.app.app.handover.engine as eng

    it = iter(times)

    class FakeDT(datetime):
        @classmethod
        def utcnow(cls):
            return next(it)

    monkeypatch.setattr(eng, "datetime", FakeDT)


def test_rule_based_handover(monkeypatch):
    base = datetime(2025, 1, 1)
    times = [base, base + timedelta(seconds=1.1)]
    patch_time(monkeypatch, times)

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
    patch_time(monkeypatch, times)

    nsm = NetworkStateManager()
    # UE is already connected to the best antenna ('B')
    nsm.antenna_list = {"A": DummyAntenna(-80), "B": DummyAntenna(-70)}
    nsm.ue_states = {"u1": {"position": (0, 0, 0), "connected_to": "B"}}

    eng = HandoverEngine(nsm, use_ml=False, a3_hysteresis_db=3.0, a3_ttt_s=1.0)
    assert eng.decide_and_apply("u1") is None


def test_rule_based_handover_no_eligible_antennas(monkeypatch):
    base = datetime(2025, 1, 1)
    times = [base, base + timedelta(seconds=1.1)]
    patch_time(monkeypatch, times)

    nsm = NetworkStateManager()
    # Only one antenna, so no eligible neighbors
    nsm.antenna_list = {"A": DummyAntenna(-80)}
    nsm.ue_states = {"u1": {"position": (0, 0, 0), "connected_to": "A"}}

    eng = HandoverEngine(nsm, use_ml=False, a3_hysteresis_db=3.0, a3_ttt_s=1.0)
    assert eng.decide_and_apply("u1") is None


def test_rule_based_handover_invalid_ue(monkeypatch):
    base = datetime(2025, 1, 1)
    times = [base, base + timedelta(seconds=1.1)]
    patch_time(monkeypatch, times)

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
            return {"predicted_antenna": "B"}

    def fake_post(url, json=None, timeout=None):
        return DummyResp()

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setenv("ML_SERVICE_URL", "http://ml")

    nsm = NetworkStateManager()
    nsm.antenna_list = {"A": DummyAntenna(-80), "B": DummyAntenna(-76)}
    nsm.ue_states = {
        "u1": {"position": (0, 0, 0), "connected_to": "A", "speed": 0.0}}

    eng = HandoverEngine(nsm, use_ml=True)
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


def test_select_ml(monkeypatch):
    """_select_ml returns predicted antenna based on features."""
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

        def get_feature_vector(self, ue_id):
            assert ue_id == "u1"
            return self.fv

    class DummyResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"predicted_antenna": "B"}

    monkeypatch.setattr("requests.post", lambda *a, **k: DummyResp())
    monkeypatch.setenv("ML_SERVICE_URL", "http://ml")

    sm = DummyStateMgr()
    eng = HandoverEngine(sm, use_ml=True)
    assert eng._select_ml("u1") == "B"


def test_select_ml_local(monkeypatch):
    """_select_ml should use local model when enabled."""
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
                aid: DummyAntenna(-80) for aid in fv["neighbor_rsrp_dbm"]}

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
    eng = HandoverEngine(
        sm, use_ml=True, use_local_ml=True, ml_model_path="foo")
    assert eng._select_ml("u1") == "B"
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
    eng = HandoverEngine(
        sm, use_ml=True, use_local_ml=True, ml_model_path="foo")
    caplog.set_level(logging.WARNING)
    assert eng._select_ml("u1") is None
    assert any("Local ML prediction failed" in rec.getMessage() for rec in caplog.records)


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
