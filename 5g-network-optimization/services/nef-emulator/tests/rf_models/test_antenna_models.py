# services/nef-emulator/tests/rf_models/test_antenna_models.py

import math
import sys
import os
import pytest

# Ensure nef-emulator root is on the path so 'antenna_models' can be imported
current_dir = os.path.dirname(os.path.abspath(__file__))
repo_root = os.path.abspath(os.path.join(current_dir, "..", ".."))  # services/nef-emulator
sys.path.insert(0, repo_root)

from antenna_models.models import (
    MacroCellModel,
    MicroCellModel,
    PicoCellModel
)

@pytest.fixture
def ue_position():
    # UE at ground level 100 m east of antenna
    return (100.0, 0.0, 1.5)

def test_macrocell_pathloss_increases_with_distance(ue_position):
    ant = MacroCellModel("macro1", (0,0,20), 2.6e9, tx_power_dbm=46)
    pl100 = ant.path_loss_db(ue_position)
    pl200 = ant.path_loss_db((200,0,1.5))
    assert pl200 > pl100, "Macrocell path-loss should increase with distance"

def test_picocell_fspl_matches_reference(ue_position):
    ant = PicoCellModel("pico1", (0,0,5), 3.5e9, tx_power_dbm=20)
    pl = ant.path_loss_db(ue_position)
    # FSPL(100 m, 3500 MHz) ≈ 20·log10(0.1) + 20·log10(3500) + 32.45
    expected = 20*math.log10(0.1) + 20*math.log10(3500) + 32.45
    assert abs(pl - expected) < 0.5, f"Pico FSPL {pl:.2f} vs expected {expected:.2f}"
    
def test_microcell_pathloss_values_are_sensible(ue_position):
    """
    At 100 m, Urban Macro NLOS PL should be between ~60 and ~140 dB per 3GPP benchmarks.
    """
    ant = MacroCellModel("macro1", (0,0,10), 3.5e9, tx_power_dbm=30)
    pl = ant.path_loss_db(ue_position)
    assert 60 < pl < 140, f"Path-loss {pl:.1f} dB outside [60,140]"

def test_sinr_decreases_with_interference(ue_position):
    """Adding an interfering antenna should lower SINR."""
    main = MacroCellModel("macro1", (0,0,10), 3.5e9, 30)
    interferer = MacroCellModel("macro2", (50,0,10), 3.5e9, 30)
    sinr_clean = main.sinr_db(ue_position, [])
    sinr_intf = main.sinr_db(ue_position, [interferer])
    assert sinr_intf < sinr_clean, "SINR did not decrease with interference"

def test_sinr_under_heavy_interference(ue_position):
    """
    Ensure SINR remains finite under heavy interference.
    We accept down to –50 dB, which covers very low-SINR scenarios.
    """
    ant = MacroCellModel("macro1", (0,0,10), 3.5e9, 30)
    interferers = [
        MacroCellModel(f"i{i}", (i*20,0,10), 3.5e9, 30)
        for i in range(1,4)
    ]
    sinr = ant.sinr_db(ue_position, interferers)
    assert -50 < sinr < 50, f"SINR {sinr:.1f} dB outside realistic range (–50 to 50)"

if __name__ == "__main__":
    sys.exit(pytest.main([__file__]))