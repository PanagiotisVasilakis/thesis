# services/nef-emulator/rf_models/__init__.py

"""RF Models package for 3GPP TR 38.901 path-loss, shadowing, and fading models.

This package contains:
- Path loss models (ABG, Close-In)
- Fast fading with Doppler effects
- AR1 spatially-correlated shadowing (Fix #25)
- Channel model with proper sign conventions (Fix #3)
- Doppler division-by-zero protection (Fix #24)
"""

from .path_loss import ABGPathLossModel, CloseInPathLossModel, FastFading
from .channel_model import ChannelModel, ChannelModelManager, ChannelState

__all__ = [
    "ABGPathLossModel",
    "CloseInPathLossModel",
    "FastFading",
    "ChannelModel",
    "ChannelModelManager",
    "ChannelState",
]
