# tests/test_a3_rule.py

from datetime import datetime, timedelta

import pytest
from backend.app.app.network.state_manager import NetworkStateManager
from backend.app.app.handover.engine import HandoverEngine


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


def test_a3_handover_trigger(monkeypatch):
    base = datetime(2025, 1, 1)
    times = [base, base + timedelta(seconds=0.5),
             base + timedelta(seconds=1.1), base + timedelta(seconds=1.1)]
    patch_time(monkeypatch, times)

    n = NetworkStateManager()
    n.antenna_list = {'A': DummyAntenna(-80), 'B': DummyAntenna(-76)}
    n.ue_states = {'u1': {'position': (0, 0, 0), 'connected_to': 'A'}}

    eng = HandoverEngine(n, use_ml=False, a3_hysteresis_db=3.0, a3_ttt_s=1.0)

    # first call starts timer
    assert eng.decide_and_apply('u1') is None
    # before ttt expiry
    assert eng.decide_and_apply('u1') is None
    # after ttt -> handover occurs
    ev = eng.decide_and_apply('u1')
    assert ev and ev['from'] == 'A' and ev['to'] == 'B'


def test_a3_timer_reset(monkeypatch):
    base = datetime(2025, 1, 1)
    times = [base, base + timedelta(seconds=0.5),
             base + timedelta(seconds=1.0),
             base + timedelta(seconds=2.2),
             base + timedelta(seconds=2.2)]
    patch_time(monkeypatch, times)

    n = NetworkStateManager()
    antB = DummyAntenna(-76)
    n.antenna_list = {'A': DummyAntenna(-80), 'B': antB}
    n.ue_states = {'u1': {'position': (0, 0, 0), 'connected_to': 'A'}}

    eng = HandoverEngine(n, use_ml=False, a3_hysteresis_db=3.0, a3_ttt_s=1.0)

    # start timer with diff=4
    assert eng.decide_and_apply('u1') is None
    # drop below hysteresis -> timer reset
    antB._rsrp = -82
    assert eng.decide_and_apply('u1') is None
    # difference > H again -> start new timer
    antB._rsrp = -76
    assert eng.decide_and_apply('u1') is None
    # after ttt from restart -> should handover
    ev = eng.decide_and_apply('u1')
    assert ev and n.ue_states['u1']['connected_to'] == 'B'
