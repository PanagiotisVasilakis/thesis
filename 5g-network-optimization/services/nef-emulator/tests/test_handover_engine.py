from datetime import datetime, timedelta

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
    class DummyModel:
        def __init__(self, *args, **kwargs):
            pass

        def extract_features(self, d):
            return {}

        def predict(self, f):
            return {"antenna_id": "B", "confidence": 1.0}

    monkeypatch.setattr("backend.app.app.handover.engine.AntennaSelector", DummyModel)

    nsm = NetworkStateManager()
    nsm.antenna_list = {"A": DummyAntenna(-80), "B": DummyAntenna(-76)}
    nsm.ue_states = {"u1": {"position": (0, 0, 0), "connected_to": "A", "speed": 0.0}}

    eng = HandoverEngine(nsm, use_ml=True)
    ev = eng.decide_and_apply("u1")
    assert ev and ev["to"] == "B"


def test_engine_mode_env(monkeypatch):
    """Environment variable should control ML mode when use_ml is None."""

    class DummyModel:
        def __init__(self, *a, **k):
            pass

        def extract_features(self, d):
            return {}

        def predict(self, f):
            return {"antenna_id": "A", "confidence": 1.0}

    monkeypatch.setattr("backend.app.app.handover.engine.AntennaSelector", DummyModel)

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

    class DummyModel:
        def __init__(self, *a, **k):
            pass

        def extract_features(self, d):
            return {}

        def predict(self, f):
            return {"antenna_id": "A", "confidence": 1.0}

    import backend.app.app.handover.engine as eng_mod

    eng_mod.AntennaSelector = DummyModel

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

    class DummyModel:
        def __init__(self, *a, **k):
            pass

        def extract_features(self, d):
            return {}

        def predict(self, f):
            return {"antenna_id": "A", "confidence": 1.0}

    monkeypatch.setattr("backend.app.app.handover.engine.AntennaSelector", DummyModel)

    monkeypatch.setenv("ML_HANDOVER_ENABLED", "0")
    nsm = NetworkStateManager()
    eng = HandoverEngine(nsm, use_ml=True)
    assert eng.use_ml is True
    monkeypatch.delenv("ML_HANDOVER_ENABLED", raising=False)


def test_engine_auto_switch_runtime(monkeypatch):
    """Engine should switch modes automatically when antenna count changes."""

    class DummyModel:
        def __init__(self, *a, **k):
            pass

        def extract_features(self, d):
            return {}

        def predict(self, f):
            return {"antenna_id": "B", "confidence": 1.0}

    monkeypatch.setattr("backend.app.app.handover.engine.AntennaSelector", DummyModel)

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

    class DummyModel:
        def __init__(self, *a, **k):
            pass

        def extract_features(self, data):
            assert data["ue_id"] == "u1"
            return {"feat": 1}

        def predict(self, feats):
            assert feats == {"feat": 1}
            return {"antenna_id": "B", "confidence": 1.0}

    monkeypatch.setattr("backend.app.app.handover.engine.AntennaSelector", DummyModel)

    sm = DummyStateMgr()
    eng = HandoverEngine(sm, use_ml=True)
    assert eng._select_ml("u1") == "B"


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

    class DummyModel:
        def __init__(self, *a, **k):
            pass

        def extract_features(self, d):
            return {}

        def predict(self, f):
            return {"antenna_id": "A", "confidence": 1.0}

    monkeypatch.setattr("backend.app.app.handover.engine.AntennaSelector", DummyModel)

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
