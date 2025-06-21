import sys, os
from datetime import datetime, timedelta

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)

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
    monkeypatch.setattr(eng, 'datetime', FakeDT)

def test_rule_based_handover(monkeypatch):
    base = datetime(2025,1,1)
    times = [base, base + timedelta(seconds=1.1)]
    patch_time(monkeypatch, times)

    nsm = NetworkStateManager()
    nsm.antenna_list = {'A': DummyAntenna(-80), 'B': DummyAntenna(-76)}
    nsm.ue_states = {'u1': {'position': (0,0,0), 'connected_to': 'A'}}

    eng = HandoverEngine(nsm, use_ml=False, a3_hysteresis_db=3.0, a3_ttt_s=1.0)
    assert eng.decide_and_apply('u1') is None
    ev = eng.decide_and_apply('u1')
    assert ev and nsm.ue_states['u1']['connected_to']=='B'

def test_rule_based_handover_already_connected(monkeypatch):
    base = datetime(2025,1,1)
    times = [base, base + timedelta(seconds=1.1)]
    patch_time(monkeypatch, times)

    nsm = NetworkStateManager()
    # UE is already connected to the best antenna ('B')
    nsm.antenna_list = {'A': DummyAntenna(-80), 'B': DummyAntenna(-70)}
    nsm.ue_states = {'u1': {'position': (0,0,0), 'connected_to': 'B'}}

    eng = HandoverEngine(nsm, use_ml=False, a3_hysteresis_db=3.0, a3_ttt_s=1.0)
    assert eng.decide_and_apply('u1') is None

def test_rule_based_handover_no_eligible_antennas(monkeypatch):
    base = datetime(2025,1,1)
    times = [base, base + timedelta(seconds=1.1)]
    patch_time(monkeypatch, times)

    nsm = NetworkStateManager()
    # Only one antenna, so no eligible neighbors
    nsm.antenna_list = {'A': DummyAntenna(-80)}
    nsm.ue_states = {'u1': {'position': (0,0,0), 'connected_to': 'A'}}

    eng = HandoverEngine(nsm, use_ml=False, a3_hysteresis_db=3.0, a3_ttt_s=1.0)
    assert eng.decide_and_apply('u1') is None

def test_rule_based_handover_invalid_ue(monkeypatch):
    base = datetime(2025,1,1)
    times = [base, base + timedelta(seconds=1.1)]
    patch_time(monkeypatch, times)

    nsm = NetworkStateManager()
    nsm.antenna_list = {'A': DummyAntenna(-80), 'B': DummyAntenna(-76)}
    nsm.ue_states = {'u1': {'position': (0,0,0), 'connected_to': 'A'}}

    eng = HandoverEngine(nsm, use_ml=False, a3_hysteresis_db=3.0, a3_ttt_s=1.0)
    # 'u2' does not exist
    assert eng.decide_and_apply('u2') is None

def test_ml_handover(monkeypatch):
    class DummyModel:
        def __init__(self, *args, **kwargs):
            pass
        def extract_features(self, d):
            return {}
        def predict(self, f):
            return {'antenna_id': 'B', 'confidence': 1.0}
    monkeypatch.setattr('backend.app.app.handover.engine.AntennaSelector', DummyModel)

    nsm = NetworkStateManager()
    nsm.antenna_list = {'A': DummyAntenna(-80), 'B': DummyAntenna(-76)}
    nsm.ue_states = {'u1': {'position': (0,0,0), 'connected_to': 'A', 'speed':0.0}}

    eng = HandoverEngine(nsm, use_ml=True)
    ev = eng.decide_and_apply('u1')
    assert ev and ev['to']=='B'
