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
    # UE at ground level 100 m east of antenna
    return (100.0, 0.0, 1.5)

def test_macrocell_pathloss_increases_with_distance(ue_position):
    ant = MacroCellModel("macro1", (0,0,20), 2.6e9, tx_power_dbm=46)
    pl100 = ant.path_loss_db(ue_position)
    pl200 = ant.path_loss_db((200,0,1.5))
    assert pl200 > pl100, "Macrocell path‑loss should increase with distance"

def test_microcell_pathloss_values_are_sensible(ue_position):
    ant = MicroCellModel("micro1", (0,0,10), 3.5e9, tx_power_dbm=30)
    pl = ant.path_loss_db(ue_position)
    # Urban micro NLOS at 100 m and 3.5 GHz is around 188 dB (per 3GPP TR36.814)
    assert 170 < pl < 210, f"Microcell path‑loss {pl:.1f} dB is outside expected range"

def test_picocell_fspl_matches_reference(ue_position):
    ant = PicoCellModel("pico1", (0,0,5), 3.5e9, tx_power_dbm=20)
    pl = ant.path_loss_db(ue_position)
    # FSPL(100 m, 3500 MHz) ≈ 20·log10(0.1) + 20·log10(3500) + 32.45
    expected = 20*math.log10(0.1) + 20*math.log10(3500) + 32.45
    assert abs(pl - expected) < 0.5, f"Pico FSPL {pl:.2f} vs expected {expected:.2f}"

if __name__ == "__main__":
    sys.exit(pytest.main([__file__]))
