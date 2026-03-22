# Thesis: Machine Learning for Intelligent Handover Decisions in 5G Networks

**Technical Architecture, Experimental Validation & Reproducibility**

## 📚 Table of Contents
1. [System Architecture](#system-architecture)
2. [Core Algorithms](#core-algorithms)
3. [QoS & MLOps Architecture](#qos--mlops-architecture)
4. [Experimental Methodology](#experimental-methodology)
5. [Validation Results](#validation-results)
6. [Thesis Claims Verification](#thesis-claims-verification)
7. [Reproducibility Guide](#reproducibility-guide)
8. [Troubleshooting Experiments](#troubleshooting-experiments)

---

## System Architecture

The solution implements a microservices-based architecture designed to seamlessly integrate machine learning into a standard 3GPP network flow.

### High-Level Design
```
┌──────────────────────────────────────────────────────────────┐
│                    5G Optimization System                    │
│                                                              │
│  ┌─────────────────┐           ┌───────────────────────┐    │
│  │  NEF Emulator   │           │    ML Service         │    │
│  │  - 3GPP APIs    │◄─────────►│    - LightGBM Model   │    │
│  │  - Mobility     │  Feature  │    - LSTM Support     │    │
│  │  - A3 Fallback  │  Exchange │    - QoS Awareness    │    │
│  └─────────────────┘           └───────────────────────┘    │
│         │                                 │                 │
│         ▼                                 ▼                 │
│  ┌──────────────────────────────────────────────────────┐    │
│  │         Prometheus/Grafana Monitoring               │    │
│  └──────────────────────────────────────────────────────┘    │
```

### Components
1.  **NEF Emulator (FastAPI)**: Acts as the network control plane. It manages UE state, simulates mobility (Linear, Manhattan Grid, etc.), and enforces the fallback A3 handover rules when ML is unavailable or uncertain.
2.  **ML Service (Flask)**: The intelligence layer. It hosts the LightGBM/LSTM models, receives feature vectors (RSRP, SINR, Speed, Trajectory), and returns antenna predictions with confidence scores.
3.  **Monitoring Stack**: Prometheus collects real-time metrics (handover counts, ping-pong events, latency), visualized in Grafana.

For full architectural details (data flows, API reference, database schemas), see [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Core Algorithms

### 1. Hybrid Decision Logic (ML + A3)
The system does not replace standard protocols but enhances them.

*   **Trigger**: Handovers are evaluated when a UE moves or signal quality changes.
*   **Threshold Check**: If `<3` antennas are visible, the system defaults to **A3 Rule** (standard RSRP comparison).
*   **ML Activation**: If `≥3` antennas are visible, **ML Prediction** is triggered.
*   **Confidence Gating**:
    *   If ML Confidence > `Threshold` (e.g., 0.5 or QoS-dependent), the ML decision is applied.
    *   If ML Confidence is low, the system falls back to the **A3 Rule**.

### 2. Ping-Pong Prevention (The 3-Layer Defense)
To prevent rapid oscillations between cells (Ping-Pong effect), the ML service implements a three-layer filter:

1.  **Minimum Interval**: Hard block on handovers if the last one was `< MIN_HANDOVER_INTERVAL_S` (default 2s).
2.  **Rate Limiting**: Blocks attempts if `> MAX_HANDOVERS_PER_MINUTE` (default 3) have occurred.
3.  **History Awareness**: If the target cell was visited recently (within `PINGPONG_WINDOW_S`), the required confidence is boosted (e.g., to 0.95) to prevent "returning" unless necessary.

### 3. Multi-Antenna Load Balancing
In scenarios with overlapping coverage (3-10 antennas), the ML model considers **cell load** alongside signal strength.
*   **A3 Behavior**: Always chooses the strongest signal, potentially overloading a single cell.
*   **ML Behavior**: Can choose a slightly weaker signal (e.g., -75dBm vs -74dBm) if the stronger cell is heavily loaded, optimizing global network performance.

---

## QoS & MLOps Architecture

### QoS-Aware Prediction
Different 5G slices have different risk tolerances. The system dynamically adjusts confidence thresholds based on the requested service:

| Service | Priority | Min Confidence | Rationale |
|---------|----------|----------------|-----------|
| **URLLC** | 9-10 | **0.95** | Critical reliability; avoid risky handovers. |
| **eMBB** | 6-9 | **0.75** | High throughput; moderate risk acceptable. |
| **mMTC** | 2-4 | **0.60** | Connectivity focus; aggressive handover ok. |

### Synthetic Data Generation
To train the model, we use a 3GPP-aligned synthetic generator (`scripts/data_generation/synthetic_generator.py`) that produces realistic traffic profiles:
*   **Distributions**: Triangular distributions for Latency, Reliability, and Throughput.
*   **Profiles**: `urllc-heavy`, `embb-heavy`, `balanced`.
*   **Output**: CSV/JSON datasets compatible with the training pipeline.

Service parameter envelopes align with 3GPP TS 22.261 and TR 38.913 for eMBB/URLLC and 3GPP TS 22.104 for mMTC, while the priority ranges mirror the conversational/mission-critical 5QI groupings from 3GPP TS 23.501 Annex E.

#### CSV Schema

| Column | Description |
| --- | --- |
| `request_id` | Stable identifier (`req_000000`), ensuring deterministic joins. |
| `service_type` | One of `embb`, `urllc`, `mmtc`, or `default`. |
| `latency_ms` | Round-trip latency from a triangular distribution. |
| `reliability_pct` | Probability of successful delivery (e.g., `99.995`). |
| `throughput_mbps` | Expected user-plane throughput in Mbps. |
| `priority` | Integer priority bucket aligned with 5QI scheduling tiers. |

#### CLI Usage

```bash
# Balanced CSV dataset
python scripts/data_generation/synthetic_generator.py \
  --records 10000 --profile balanced --output output/samples.csv --format csv --seed 42

# URLLC-heavy JSON dataset
python scripts/data_generation/synthetic_generator.py \
  --records 5000 --profile urllc-heavy --embb-weight 0.5 --urllc-weight 1.0 \
  --mmtc-weight 0.2 --format json --output output/urllc_bias.json
```

### Model Performance (LightGBM)
*   **Top Features**: `acceleration`, `signal_trend`, `rsrp_stddev`, `heading_change_rate`.
*   **Accuracy**: ~99% on validation sets (after calibration).
*   **Latency**: P95 prediction time < 30ms (suitable for real-time control).

---

## Experimental Methodology

The thesis results are derived from a fully automated, reproducible experiment pipeline: `scripts/run_thesis_experiment.sh`.

### The Protocol
1.  **Phase 0**: Pre-flight checks (Docker, dependencies).
2.  **Phase 1 (ML Mode)**:
    *   Spin up stack with `ML_HANDOVER_ENABLED=1`.
    *   Initialize topology (1 gNB, 4 cells, 3 UEs).
    *   Run for 10 minutes.
    *   Collect metrics (Ping-pongs, Dwell time, QoS compliance).
3.  **Phase 2 (A3 Mode)**:
    *   Restart stack with `ML_HANDOVER_ENABLED=0`.
    *   Run identical topology/mobility for 10 minutes.
    *   Collect baseline metrics.
4.  **Phase 3**: Generate comparison report and visualizations.

### Experiment Tiers

| Tier | Scope | Duration |
|------|-------|----------|
| **Tier 1** | 40 runs (2 scenarios × 2 algorithms × 10 seeds) | 6-8 hours |
| **Tier 2** | Extended sensitivity analysis | ~20 hours |
| **Tier 3** | Full 270 combinations (future work) | ~40 hours |

### Seed Strategy

```python
class SeedStrategy(Enum):
    SEQUENTIAL = "sequential"  # 1, 2, 3, ...
    PRIMES = "primes"          # 2, 3, 5, 7, 11, ...
    HASH_BASED = "hash"        # Deterministic from metadata
```

---

## Validation Results

Results from the final reference experiment (`fixed_system_final`):

| Metric | A3 Mode (Baseline) | ML Mode (System) | Improvement |
|--------|-------------------|------------------|-------------|
| **Ping-Pong Rate** | 37.5% | **0.0%** | **100% Reduction** |
| **Median Dwell Time** | 25.6s | **133.7s** | **422% Increase** |
| **Total Handovers** | 24 | 6 | **75% Reduction** |
| **QoS Compliance** | N/A | 100% | **Perfect** |

**Interpretation**: The ML system drastically stabilizes the network. By predicting user trajectories, it avoids unnecessary handovers to transiently strong cells (Ping-Pong), keeping UEs connected to optimal cells for longer periods.

### Statistical Validation (Tier 1 Expected Ranges)

| Metric | ML Mean ± SD | A3 Mean ± SD | p-value |
|--------|-------------|--------------|---------|
| Handover Count | 15.2 ± 3.1 | 23.8 ± 5.2 | < 0.001 |
| Ping-Pong Rate | 2.1% ± 1.0% | 8.5% ± 2.3% | < 0.001 |
| RLF Count | 0.3 ± 0.5 | 1.2 ± 0.9 | < 0.01 |
| Mean Throughput | 45.2 ± 4.1 Mbps | 42.1 ± 5.3 Mbps | < 0.05 |

Statistical methods: paired t-test (not independent), Cohen's d_z for effect size, Bonferroni correction for multiple comparisons, and bootstrap CI maintaining pairing.

---

## Thesis Claims Verification

We implemented an automated test suite (`tests/thesis/test_ml_vs_a3_claims.py`) that programmatically validates every claim made in the thesis.

### Validated Claims
1.  ✅ **ML Reduces Ping-Pong**: Test simulates rapid signal oscillation; ML suppresses 75%+ of swaps.
2.  ✅ **QoS Compliance**: Test verifies higher confidence is enforced for URLLC slices.
3.  ✅ **Load Balancing**: Test forces 10 UEs into a multi-cell overlap; ML distributes them across available antennas.
4.  ✅ **Scalability**: Stress tests with 10 antennas confirm <50ms latency.
5.  ✅ **Auto-Activation**: Test confirms ML engages exactly when antenna count ≥ 3.

To run these proofs:
```bash
pytest -v -m thesis tests/thesis/test_ml_vs_a3_claims.py
```

---

## Reproducibility Guide

### Environment Setup

| Requirement | Version |
|-------------|---------|
| **OS** | Ubuntu 22.04 LTS |
| **Python** | 3.10.x (3.10.12 recommended) |
| **Memory** | 16 GB RAM minimum |
| **Storage** | 20 GB free space |
| **Docker** | 24.0+ |

```bash
# Create virtual environment
python3.10 -m venv thesis_venv
source thesis_venv/bin/activate

# Install locked dependencies
pip install --upgrade pip==24.0
pip install -r requirements.lock
```

### Dependency Locking

Scientific reproducibility requires identical execution environments. These packages directly affect results:

| Package | Locked Version | Impact |
|---------|---------------|--------|
| `numpy` | 1.26.4 | Random seeds, array operations |
| `scipy` | 1.12.0 | Statistical tests |
| `scikit-learn` | 1.5.2 | Train/test splits |
| `lightgbm` | 4.3.0 | Model predictions |
| `matplotlib` | 3.8.2 | Figure generation |
| `shap` | 0.44.1 | Feature importance |

Verify installation: `python scripts/verify_dependencies.py`

**DO NOT** update dependencies without running the full experiment matrix and comparing results.

### Git Version Control

#### Tagging Protocol

```bash
# Ensure clean working directory
git status  # Should show "nothing to commit"

# Create annotated tag for submission
HASH=$(python scripts/compute_experiment_hash.py)
git tag -a v1.0.0-submission -m "Thesis submission: $HASH"
git push origin v1.0.0-submission
```

#### Reproducing from Tag

```bash
git clone https://github.com/username/thesis.git
cd thesis
git checkout v1.0.0-submission
```

#### Experiment Hash

Every experiment run generates a hash combining git SHA, `requirements.lock` hash, configuration, and random seed:

```python
from scripts.reproducibility import compute_experiment_hash

hash_value = compute_experiment_hash({
    "scenario": "highway", "algorithm": "ml", "seed": 2
})
# Output: "exp_highway_ml_2_abc123def456"
```

### Running Experiments

```bash
# Quick validation (1 minute)
python scripts/run_enhanced_experiment.py \
    --scenario highway --algorithm ml --seed 2 --duration 60 \
    --output-dir thesis_results/validation

# Tier 1 matrix (6-7 hours)
python scripts/experiments/experimental_config.py
python scripts/run_experiment_matrix.py \
    --matrix thesis_results/experiment_matrix_tier1.json \
    --parallel 1 --output-dir thesis_results/tier1

# Statistical analysis
python scripts/analysis/statistical_analysis.py \
    --ml-results thesis_results/tier1/ml_*.json \
    --a3-results thesis_results/tier1/a3_*.json \
    --output thesis_results/statistical_summary.json
```

---

## Troubleshooting Experiments

### Different Random Results
**Symptom**: Results don't match expected ranges.
```bash
python -c "import numpy; print(numpy.__version__)"  # Must be 1.26.4
python scripts/run_enhanced_experiment.py --verify-reproducibility
```

### Memory Errors
```bash
export ML_BATCH_SIZE=32
python scripts/run_experiment_matrix.py --parallel 1
```

### SHAP Computation Timeout
```bash
export SHAP_MODE=off      # Disable for batch experiments
# or
export SHAP_MODE=sampled
export SHAP_SAMPLE_RATE=0.1
```

### Docker Network Issues
```bash
docker-compose down -v
docker network prune
docker-compose up -d
```

---

*Document Version: 2.0 — Last Updated: March 2026*
*Merged from THESIS.md + REPRODUCIBILITY.md*
