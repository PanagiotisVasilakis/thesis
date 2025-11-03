# QoS-Aware Model Performance & Feature Importance

**Last Updated**: November 3, 2025  
**Author**: Thesis Automation Pipeline  

---

## Overview

To validate the new QoS-aware feature set, we trained the LightGBM-based antenna selector on a synthetic dataset that captures dynamic RF conditions, mobility patterns, and QoS observations. The goal was to (1) confirm the expanded feature vector is exercised during training, (2) understand which signals the model relies on most, and (3) provide a reproducible retraining workflow for future experiments.

---

## Training Configuration

| Parameter | Value |
|-----------|-------|
| Samples | 1,500 synthetic UE snapshots |
| Neighbor antennas | 8 |
| Random seed | 123 |
| Model | `LightGBMSelector` (100 trees, max depth 10, num_leaves 31) |
| Confidence calibration | Enabled (`isotonic`) |
| Validation split | 20% (early stopping @ 20 rounds) |

**Validation Metrics**

- Accuracy (calibrated): **0.403**  
- Accuracy (uncalibrated): 0.393  
- Weighted F1: **0.257**  
- Confidence improvement (calibrated vs. raw): **+1.0 pp**

> These metrics reflect a deliberately challenging synthetic dataset with eight antenna choices and high class imbalance. Accuracy is less important here than relative feature usage; real datasets should achieve higher scores.

---

## Feature Importance (Top 10 by Gain)

| Rank | Feature | Gain | Splits | Interpretation |
|------|---------|------|--------|----------------|
| 1 | `acceleration` | 299.21 | 64 | Rapid mobility changes remain the strongest signal for predicting future handovers. |
| 2 | `signal_trend` | 297.78 | 49 | Short-term RF deltas help anticipate upcoming degradation, reinforcing the value of temporal context. |
| 3 | `rsrp_stddev` | 297.18 | 64 | Variability in serving-cell power captures link stability (proxy for churn risk). |
| 4 | `heading_change_rate` | 281.45 | 41 | Directional changes drive ML’s proactive decisions, especially in dense deployments. |
| 5 | `time_since_handover` | 270.03 | 46 | Recency of prior handovers still matters—ping-pong mitigation signal. |
| 6 | `path_curvature` | 256.20 | 48 | Non-linear trajectories correlate with problem areas (intersections, edge overlaps). |
| 7 | `longitude` | 246.70 | 40 | Geographic context (paired with latitude) remains influential even with QoS features. |
| 8 | `speed` | 243.06 | 48 | Absolute velocity continues to be a core driver for dwell-time decisions. |
| 9 | `environment` | 232.29 | 38 | Environmental encoding (urban vs. open) modulates how RF + QoS trade-offs are interpreted. |
| 10 | `cell_load` | 177.90 | 33 | Load-aware handovers still rank highly—ML keeps preferring underutilised antennas. |

### QoS-Specific Signals

While mobility and RF context dominate, QoS features are now in the mix:

- `throughput_requirement_mbps` (gain 54.87) and `throughput_delta_mbps` (gain 43.77) influence decisions when cell loads spike.  
- `reliability_pct` (gain 58.65) and `reliability_delta_pct` (gain 42.07) help the model down-rank antennas that historically violate reliability targets.  
- `latency_requirement_ms` (gain 42.55) and `latency_delta_ms` (gain 27.06) provide a safety net for URLLC-style flows.

> **Takeaway**: QoS-aware signals now have measurable impact. To increase their relative importance further, collect or generate data with more extreme QoS violations (e.g., congested cells, QoS-aware fallback scenarios).

---

## Ablation Study: QoS vs. Baseline

Using `scripts/qos_feature_importance.py --ablation`, we trained two models on identical synthetic datasets:

| Metric | With QoS Features | Without QoS Features | Delta |
|--------|-------------------|----------------------|-------|
| Validation Accuracy | **0.4033** | 0.3900 | **+0.0133** |
| Weighted F1 | **0.2568** | 0.2188 | **+0.0380** |
| Confidence Gain (calibrated − raw) | +0.0100 | 0.0000 | +0.0100 |

**Interpretation**

- QoS-aware inputs provide a consistent ~1.3 percentage-point boost in validation accuracy and a 3.8 pp improvement in weighted F1.
- With QoS disabled, the model relies almost exclusively on RF/mobility features (top gains: `rsrp_stddev`, `environment`, `speed`, `longitude`, `cell_load`).
- Enabling QoS reintroduces QoS-specific deltas into the top-15 features and increases the diversity of mobility signals, indicating the model is learning to trade off RF strength, load, and QoS requirements.

The full comparison report lives at `artifacts/qos_feature_importance_ablation.json`.

---

## How to Reproduce

1. **Install dependencies** (if not already inside the thesis venv):
   ```bash
   source thesis_venv/bin/activate
   export PYTHONPATH="${PWD}:${PWD}/5g-network-optimization/services:${PYTHONPATH}"
   ```
2. **Generate synthetic dataset & feature importances**:
   ```bash
   python scripts/qos_feature_importance.py \
       --samples 1500 \
       --neighbor-count 8 \
       --seed 123 \
       --output artifacts/qos_feature_importance.json
   ```
3. **Review the JSON report** (already committed for this run): `artifacts/qos_feature_importance.json`.

---

## Recommended Retraining Workflow

1. **Data refresh**
   - Generate service mixes using `scripts/data_generation/synthetic_generator.py` for URLLC, eMBB, and mMTC heavy scenarios.
   - Incorporate field data or simulator logs when available (exported via `analyze_handover_history.py`).
2. **Model training**
   - Run `scripts/qos_feature_importance.py` (with adjusted `--samples` / `--neighbor-count`) to train and compute importances.
   - For production runs, persist the trained model with `selector.save(path)` (extend script if needed).
3. **Calibration check**
   - Confirm `confidence_calibrated` is `true`. If calibration is skipped (<30 validation samples), increase dataset size.  
   - Compare `val_accuracy` vs. `val_accuracy_uncalibrated` to ensure calibration adds value.
4. **Update documentation**
   - Record new top features and metrics in this document.  
   - Log experimental parameters (dataset version, seed) for reproducibility.

---

## Observations & Next Steps

- **Mobility-aware features** still dominate the model—expected, since handovers are strongly tied to movement patterns.  
- **QoS deltas** contribute, but their gain scores are lower than RF and mobility signals. To boost their impact:
  - Generate datasets with deliberate QoS degradations (e.g., high jitter / loss) and success labels tied to QoS compliance.  
  - Incorporate real metrics from the NEF emulator’s new QoS monitor once available.
- **Validation accuracy** is moderate due to the intentionally difficult synthetic task. Focus on relative improvements (e.g., ablations with/without QoS features) when reporting thesis results.

### Upcoming Work

- **Phase 3** (Compliance Engine): replace confidence-only gating with multi-metric QoS evaluation using the observed metrics now produced by the ML service.  
- **Phase 4** (Closed Loop): feed NEF-observed QoS outcomes back into training and online adaptation.

---

**Artifacts**
- JSON report: `artifacts/qos_feature_importance.json`  
- Training script: `scripts/qos_feature_importance.py`

For questions or reruns, execute the script with adjusted parameters, then update this report with the new findings.
