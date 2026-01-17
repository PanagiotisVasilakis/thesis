# tests/test_a3_rule.py

from datetime import datetime, timedelta

import pytest
from backend.app.app.network.state_manager import NetworkStateManager
from backend.app.app.handover.engine import HandoverEngine
from backend.app.app.handover.a3_rule import A3EventRule

# Import shared fixtures from conftest
from tests.conftest import DummyAntenna, patch_handover_time


def test_a3_handover_trigger(monkeypatch):
    base = datetime(2025, 1, 1)
    times = [base, base + timedelta(seconds=0.5),
             base + timedelta(seconds=1.1), base + timedelta(seconds=1.1)]
    patch_handover_time(monkeypatch, times)

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
    patch_handover_time(monkeypatch, times)

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


def test_a3_rule_negative_hysteresis():
    with pytest.raises(ValueError):
        A3EventRule(hysteresis_db=-1.0)


def test_a3_rule_negative_ttt():
    with pytest.raises(ValueError):
        A3EventRule(ttt_seconds=-0.5)

def test_a3_rule_new_interface():
    """Test the new A3 rule interface with enhanced features."""
    from datetime import datetime
    
    # Test basic initialization with new parameters
    rule = A3EventRule(hysteresis_db=3.0, ttt_seconds=1.0, event_type="rsrp_based")
    now = datetime(2025, 1, 1)
    
    # Test with dict inputs (new interface)
    serving_metrics = {"rsrp": -80, "rsrq": -10}
    target_metrics = {"rsrp": -75, "rsrq": -9}
    
    # Should not trigger initially (timer starts)
    result = rule.check(serving_metrics, target_metrics, now)
    assert result is False
    
    # Test with mixed criteria
    rule_mixed = A3EventRule(hysteresis_db=3.0, ttt_seconds=0.0, event_type="mixed", rsrq_threshold=-12)
    result_mixed = rule_mixed.check(serving_metrics, target_metrics, now)
    assert result_mixed is True  # Should trigger immediately due to 0 TTT and meeting criteria
