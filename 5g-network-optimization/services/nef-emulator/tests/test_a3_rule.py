# tests/test_a3_rule.py

from datetime import datetime, timedelta
import types


import pytest
from backend.app.app.network.state_manager import NetworkStateManager

class DummyAntenna:
    def __init__(self, rsrp):
        self._rsrp = rsrp
    def rsrp_dbm(self, pos):
        return self._rsrp

def patch_time(monkeypatch, times):
    import backend.app.app.network.state_manager as sm
    it = iter(times)
    class FakeDT(datetime):
        @classmethod
        def utcnow(cls):
            return next(it)
    monkeypatch.setattr(sm, 'datetime', FakeDT)


def test_a3_handover_trigger(monkeypatch):
    base = datetime(2025,1,1)
    times = [base, base + timedelta(seconds=0.5),
             base + timedelta(seconds=1.1), base + timedelta(seconds=1.1)]
    patch_time(monkeypatch, times)

    n = NetworkStateManager(simple_mode=True, a3_hysteresis_db=3.0, a3_ttt_s=1.0)
    n.antenna_list = {'A': DummyAntenna(-80), 'B': DummyAntenna(-76)}
    n.ue_states = {'u1': {'position': (0,0,0), 'connected_to': 'A'}}

    # first call starts timer
    assert n.apply_handover_decision('u1', 'B') is None
    # before ttt expiry
    assert n.apply_handover_decision('u1', 'B') is None
    # after ttt -> handover occurs
    ev = n.apply_handover_decision('u1', 'B')
    assert ev and ev['from']=='A' and ev['to']=='B'


def test_a3_timer_reset(monkeypatch):
    base = datetime(2025,1,1)
    times = [base, base + timedelta(seconds=0.5),
             base + timedelta(seconds=1.0),
             base + timedelta(seconds=2.2),
             base + timedelta(seconds=2.2)]
    patch_time(monkeypatch, times)

    n = NetworkStateManager(simple_mode=True, a3_hysteresis_db=3.0, a3_ttt_s=1.0)
    antB = DummyAntenna(-76)
    n.antenna_list = {'A': DummyAntenna(-80), 'B': antB}
    n.ue_states = {'u1': {'position': (0,0,0), 'connected_to': 'A'}}

    # start timer with diff=4
    assert n.apply_handover_decision('u1', 'B') is None
    # drop below hysteresis -> timer reset
    antB._rsrp = -82
    assert n.apply_handover_decision('u1', 'B') is None
    # difference > H again -> start new timer
    antB._rsrp = -76
    assert n.apply_handover_decision('u1', 'B') is None
    # after ttt from restart -> should handover
    ev = n.apply_handover_decision('u1', 'B')
    assert ev and n.ue_states['u1']['connected_to']=='B'
