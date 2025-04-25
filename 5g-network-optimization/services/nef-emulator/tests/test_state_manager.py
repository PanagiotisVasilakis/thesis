# services/nef-emulator/tests/test_state_manager.py

import sys, os, math
from datetime import datetime

# enable imports
root = os.path.abspath(os.path.join(__file__, ".."))
sys.path.insert(0, root)

import pytest
from backend.app.app.network.state_manager import NetworkStateManager
from antenna_models.models import MacroCellModel

@pytest.fixture
def nsm():
    n = NetworkStateManager()
    # Create two dummy antennas
    n.antenna_list = {
        'antA': MacroCellModel('antA', (0,0,10), 2.6e9, tx_power_dbm=46),
        'antB': MacroCellModel('antB', (500,0,10), 2.6e9, tx_power_dbm=46)
    }
    # Create a UE at (100,0,1.5) connected to antA
    n.ue_states = {
        'ue1': {
            'position': (100.0, 0.0, 1.5),
            'speed': 5.0,
            'connected_to': 'antA'
        }
    }
    return n

def test_get_feature_vector(nsm):
    fv = nsm.get_feature_vector('ue1')
    assert fv['ue_id'] == 'ue1'
    assert 'latitude' in fv and 'neighbor_rsrs' in fv
    # Check that both antennas are present in neighbor_rsrs
    assert set(fv['neighbor_rsrs'].keys()) == {'antA','antB'}

def test_apply_handover_decision(nsm):
    ev = nsm.apply_handover_decision('ue1', 'antB')
    assert ev['from'] == 'antA' and ev['to'] == 'antB'
    # UE state updated
    assert nsm.ue_states['ue1']['connected_to'] == 'antB'
    # History logged
    assert nsm.handover_history[-1]['ue_id'] == 'ue1'

def test_unknown_ue(nsm):
    with pytest.raises(KeyError):
        nsm.get_feature_vector('no_such_ue')
    with pytest.raises(KeyError):
        nsm.apply_handover_decision('no_such_ue','antA')

def test_unknown_antenna(nsm):
    with pytest.raises(KeyError):
        nsm.apply_handover_decision('ue1','antX')
        
def test_get_position_at_time_interpolation(nsm):
    # Build a simple trajectory for ue1: at t=0s at (0,0,0), at t=10s at (10,0,0)
    from datetime import timedelta
    base = datetime(2025,1,1,12,0,0)
    nsm.ue_states['ue1']['trajectory'] = [
        {'timestamp': base, 'position': (0.0, 0.0, 0.0)},
        {'timestamp': base + timedelta(seconds=10), 'position': (10.0, 0.0, 0.0)}
    ]

    # Before start
    pos0 = nsm.get_position_at_time('ue1', base - timedelta(seconds=5))
    assert pos0 == (0.0, 0.0, 0.0)

    # After end
    pos_end = nsm.get_position_at_time('ue1', base + timedelta(seconds=20))
    assert pos_end == (10.0, 0.0, 0.0)

    # Midpoint at 5s → (5,0,0)
    pos_mid = nsm.get_position_at_time('ue1', base + timedelta(seconds=5))
    assert pytest.approx(pos_mid[0], rel=1e-3) == 5.0
    assert pos_mid[1:] == (0.0, 0.0)

if __name__ == "__main__":
    pytest.main([__file__])
