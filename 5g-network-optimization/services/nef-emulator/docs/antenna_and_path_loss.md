# Antenna Models and Path-Loss Calculations

This document describes how the antenna models provided in `antenna_models/models.py` integrate the path‑loss models defined in `rf_models/path_loss.py`. It also points to the unit tests that reference these models.

## Usage of Path‑Loss Models

`antenna_models/models.py` imports two path‑loss classes:

```python
from rf_models.path_loss import ABGPathLossModel, CloseInPathLossModel
```

Each antenna model encapsulates one of these classes to perform link budget calculations:

- **MacroCellModel** – Instantiates a `CloseInPathLossModel` with environment‑specific parameters. The `path_loss_db()` method converts the antenna‑UE distance to a loss value by calling `calculate_path_loss()` on that instance.
- **MicroCellModel** – Uses `ABGPathLossModel` to model urban micro path loss. The `calculate_path_loss()` method is invoked in the same way, passing the distance and carrier frequency in GHz.
- **PicoCellModel** – Applies `CloseInPathLossModel` with a path‑loss exponent of 2 (free‑space). Again, `calculate_path_loss()` is used in `path_loss_db()`.

Shadow fading can be enabled or disabled through the `include_shadowing` flag, which is forwarded directly to the path‑loss model.

The path‑loss models themselves live in `rf_models/path_loss.py`. They implement well‑known formulas from 3GPP TR 38.901, such as ABG and Close‑In, and optionally add log‑normal shadow fading.

## References in Tests

Two sets of tests exercise the code:

- `tests/rf_models/test_antenna_models.py` instantiates `MacroCellModel`, `MicroCellModel`, and `PicoCellModel` and calls `path_loss_db()` and `sinr_db()` to verify behaviour.
- `tests/rf_models/test_path_loss.py` directly tests `ABGPathLossModel`, `CloseInPathLossModel`, and `FastFading` by running path‑loss computations over varying distances and plotting the results.

Together these tests ensure that the antenna models correctly delegate to the underlying path‑loss functions and that the models themselves follow expected statistical properties.

---

Take your time and aim for quality when extending or using these models—each class is designed with explicit parameters so that realistic scenarios can be modelled and validated through tests.
