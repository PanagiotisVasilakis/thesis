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

## Massive MIMO Pattern

`MassiveMIMOPattern` in `antenna_models/patterns.py` models a steerable antenna
array for beamforming studies.  It exposes several parameters:

- **num_elements_horizontal** – elements along the azimuth axis
- **num_elements_vertical** – elements along the elevation axis
- **element_spacing** – spacing between elements in wavelengths
- **carrier_frequency** – carrier frequency in GHz
- **max_gain_dbi** – peak gain of the array

Set the beam with `set_steering_direction(azimuth, elevation)` and use
`calculate_gain()` to obtain the directional gain.

## References in Tests

Two sets of tests exercise the code:

- `tests/rf_models/test_antenna_models.py` instantiates `MacroCellModel`, `MicroCellModel`, and `PicoCellModel` and calls `path_loss_db()` and `sinr_db()` to verify behaviour.
- `tests/rf_models/test_path_loss.py` directly tests `ABGPathLossModel`, `CloseInPathLossModel`, and `FastFading` by running path‑loss computations over varying distances and plotting the results.
- `tests/rf_models/test_massive_mimo_pattern.py` verifies that `MassiveMIMOPattern.calculate_gain()` returns finite gains for a range of azimuth and elevation angles.

Together these tests ensure that the antenna models correctly delegate to the underlying path‑loss functions and that the models themselves follow expected statistical properties.

---

Take your time and aim for quality when extending or using these models—each class is designed with explicit parameters so that realistic scenarios can be modelled and validated through tests.
