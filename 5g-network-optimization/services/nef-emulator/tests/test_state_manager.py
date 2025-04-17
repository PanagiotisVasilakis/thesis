# services/nef-emulator/tests/test_state_manager.py

import sys, os, math
from datetime import datetime

# enable imports
root = os.path.abspath(os.path.join(__file__, ".."))
sys.path.insert(0, root)

import pytest
from network.state_manager import NetworkStateManager
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

if __name__ == "__main__":
    pytest.main([__file__])
