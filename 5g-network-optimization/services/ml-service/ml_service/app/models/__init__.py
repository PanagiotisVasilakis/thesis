"""Model classes for the ML service.

Production Model Selection
==========================
For real-world 5G network deployments, use the following guidelines:

**Production (Validated):**
- ``AntennaSelector``: Primary model. LightGBM-based with ping-pong prevention,
  QoS-aware predictions, and geographic validation. Validated with 100% ping-pong
  elimination and 422% dwell time improvement in controlled experiments.

**Specialized (Production-Ready):**
- ``LightGBMSelector``: Standalone LightGBM implementation. Use when you need
  direct access to LightGBM without the full AntennaSelector feature set.

**Experimental (For Research/Benchmarking):**
- ``LSTMSelector``: LSTM-based sequence model for trajectory-aware predictions.
  Higher latency (~50-100ms) than LightGBM (~5-15ms). Use for research comparison.
- ``EnsembleSelector``: Combines multiple model predictions. Higher latency.
- ``OnlineHandoverModel``: Experimental online learning approach. Not validated
  in production scenarios.

Latency Considerations
======================
For URLLC services (< 10ms latency requirements):
- ``AntennaSelector``: ~5-15ms prediction latency ✓
- ``LSTMSelector``: ~50-100ms - NOT suitable for URLLC
- ``EnsembleSelector``: ~20-50ms - marginal for URLLC

For eMBB/mMTC (relaxed latency):
- All models are suitable

Real-World Deployment
=====================
1. Start with ``AntennaSelector`` - it handles 99% of use cases
2. Configure via environment variables (ML_HANDOVER_ENABLED, etc.)
3. Monitor via Prometheus metrics (ml_prediction_latency_seconds)
4. Fall back to A3 rule when confidence is low (automatic)
"""

from .antenna_selector import AntennaSelector, DEFAULT_TEST_FEATURES
from .lightgbm_selector import LightGBMSelector
from .lstm_selector import LSTMSelector
from .ensemble_selector import EnsembleSelector
from .online_handover_model import OnlineHandoverModel
from .base_model_mixin import BaseModelMixin

__all__ = [
    # Production model
    "AntennaSelector",
    # Specialized models
    "LightGBMSelector",
    # Experimental models
    "LSTMSelector",
    "EnsembleSelector",
    "OnlineHandoverModel",
    # Utilities
    "DEFAULT_TEST_FEATURES",
    "BaseModelMixin",
]
