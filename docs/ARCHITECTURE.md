# System Architecture

**Version:** 2.1 | **Last Updated:** March 2026 | **Author:** Thesis Implementation

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [High-Level Architecture](#high-level-architecture)
3. [O-RAN Architecture Mapping](#o-ran-architecture-mapping)
4. [Service Layer Details](#service-layer-details)
   - [NEF Emulator (RAN Simulator)](#1-nef-emulator-ran-simulator)
   - [ML Service](#2-ml-service)
   - [Kinisis UI](#3-kinisis-ui)
5. [Core Subsystems](#core-subsystems)
   - [Channel Model](#channel-model-subsystem)
   - [Handover Engine](#handover-engine-subsystem)
   - [Metrics & RLF Detection](#metrics--rlf-detection-subsystem)
   - [ML Prediction Pipeline](#ml-prediction-pipeline)
6. [Data Layer](#data-layer)
7. [Scripts & Analysis Framework](#scripts--analysis-framework)
8. [MLOps Pipeline](#mlops-pipeline)
9. [Testing Infrastructure](#testing-infrastructure)
10. [Deployment Architecture](#deployment-architecture)
11. [Data Flows](#data-flows)
12. [Configuration Reference](#configuration-reference)
13. [API Reference](#api-reference)

---

## Executive Summary

This system implements an **ML-assisted handover optimization framework** for 5G networks, designed to compare machine learning approaches against the standard **3GPP A3 event-based handover rule**. The architecture follows O-RAN Alliance principles with appropriate simplifications for research purposes.

### Key Capabilities

| Capability | Implementation |
|------------|----------------|
| **Handover Decision** | ML (LightGBM) vs 3GPP A3 baseline |
| **Channel Modeling** | AR1 shadowing, Rayleigh fading, 3GPP path loss |
| **Ping-Pong Prevention** | 3-layer protection (dwell time, ML features, QoS bias) |
| **Explainability** | SHAP-based model interpretability |
| **Real-time Visualization** | WebSocket-based metrics streaming |
| **Statistical Analysis** | Paired tests, bootstrap CI, Bonferroni correction |

### Validated Results

| Metric | ML Mode | A3 Baseline | Improvement |
|--------|---------|-------------|-------------|
| Ping-Pong Rate | 0% | 40-60% | **100% elimination** |
| Handover Count | Reduced | Baseline | **~75% reduction** |
| Avg Dwell Time | 5.22s | ~1.0s | **422% increase** |
| Coverage Loss | Maintained | Baseline | Equivalent |

---

## High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                                    PRESENTATION LAYER                                     │
│  ┌────────────────────────────────────────────────────────────────────────────────────┐  │
│  │                              Kinisis UI (React 18 + Vite)                           │  │
│  │  ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌───────────┐            │  │
│  │  │  MapPage  │ │ Dashboard │ │ Scenarios │ │  Metrics  │ │  Config   │            │  │
│  │  │ (Leaflet) │ │  (Charts) │ │  (Select) │ │  (Live)   │ │  (Forms)  │            │  │
│  │  └───────────┘ └───────────┘ └───────────┘ └───────────┘ └───────────┘            │  │
│  │  ┌──────────────────────────────────────────────────────────────────────────────┐ │  │
│  │  │  SignalPanel | RealTimeMetrics | RetryModal | AntennaMarkers | UETrajectory  │ │  │
│  │  └──────────────────────────────────────────────────────────────────────────────┘ │  │
│  └────────────────────────────────────────────────────────────────────────────────────┘  │
│                                          │ HTTP/REST + WebSocket                         │
└──────────────────────────────────────────┼───────────────────────────────────────────────┘
                                           ▼
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                                       API LAYER                                           │
│  ┌────────────────────────────────────┐    ┌────────────────────────────────────────┐   │
│  │    NEF Emulator / RAN Simulator     │    │           ML Service                    │   │
│  │         (FastAPI - Port 8080)       │    │       (Flask - Port 5050)               │   │
│  │  ┌──────────────────────────────┐  │    │  ┌──────────────────────────────────┐  │   │
│  │  │ REST Endpoints:              │  │    │  │ REST Endpoints:                  │  │   │
│  │  │  • /api/v1/ue/*              │  │◄──►│  │  • POST /predict                 │  │   │
│  │  │  • /api/v1/cells/*           │  │    │  │  • POST /predict/batch           │  │   │
│  │  │  • /api/v1/handover/*        │  │    │  │  • GET  /health                  │  │   │
│  │  │  • /api/v1/scenarios/*       │  │    │  │  • GET  /metrics                 │  │   │
│  │  │  • /api/v1/experiments/*     │  │    │  │  • POST /feedback                │  │   │
│  │  │  • WS /ws/metrics            │  │    │  │  • GET  /model/info              │  │   │
│  │  └──────────────────────────────┘  │    │  └──────────────────────────────────┘  │   │
│  └────────────────────────────────────┘    └────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────────────────────┘
                                           │
                                           ▼
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                                   BUSINESS LOGIC LAYER                                    │
│                                                                                           │
│  ┌─────────────────────────────────────────────────────────────────────────────────────┐ │
│  │                              HANDOVER ENGINE (engine.py)                             │ │
│  │  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐                   │ │
│  │  │    ML Mode       │  │    A3 Mode       │  │   Hybrid Mode    │                   │ │
│  │  │  (LightGBM)      │  │  (3GPP TS 38.331)│  │  (ML + fallback) │                   │ │
│  │  └────────┬─────────┘  └────────┬─────────┘  └────────┬─────────┘                   │ │
│  │           └─────────────────────┴─────────────────────┘                              │ │
│  │                                     │                                                 │ │
│  │  ┌──────────────────────────────────┴──────────────────────────────────┐             │ │
│  │  │   Per-UE TTT Timers  │  Ping-Pong Prevention  │  QoS-Aware Boost   │             │ │
│  │  └──────────────────────────────────────────────────────────────────────┘             │ │
│  └─────────────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                           │
│  ┌────────────────────────────┐  ┌────────────────────────────┐                          │
│  │      A3EventRule           │  │    NetworkStateManager      │                          │
│  │  ┌──────────────────────┐  │  │  ┌──────────────────────┐  │                          │
│  │  │ • Hysteresis (2dB)   │  │  │  │ • UE State Tracking  │  │                          │
│  │  │ • TTT Support        │  │  │  │ • Feature Extraction │  │                          │
│  │  │ • RSRP/RSRQ events   │  │  │  │ • Signal Calculation │  │                          │
│  │  │ • 3GPP Compliance    │  │  │  │ • Cell Management    │  │                          │
│  │  └──────────────────────┘  │  │  └──────────────────────┘  │                          │
│  └────────────────────────────┘  └────────────────────────────┘                          │
│                                                                                           │
│  ┌─────────────────────────────────────────────────────────────────────────────────────┐ │
│  │                            CHANNEL MODEL (rf_models/)                                │ │
│  │  ┌───────────────────────┐ ┌───────────────────────┐ ┌───────────────────────────┐  │ │
│  │  │    Path Loss Models   │ │  AR1 Shadowing Model  │ │  Rayleigh Fading Model    │  │ │
│  │  │  • ABG (3GPP 38.901)  │ │  • σ_SF = 4-8 dB      │ │  • Doppler-aware          │  │ │
│  │  │  • CI (Close-In)      │ │  • d_corr = 37m       │ │  • Coherence time         │  │ │
│  │  │  • UMa/UMi variants   │ │  • Spatial correlation│ │  • Division-by-0 safe     │  │ │
│  │  └───────────────────────┘ └───────────────────────┘ └───────────────────────────┘  │ │
│  └─────────────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                           │
│  ┌─────────────────────────────────────────────────────────────────────────────────────┐ │
│  │                          METRICS & RLF DETECTION (metrics/)                          │ │
│  │  ┌───────────────────────┐ ┌───────────────────────┐ ┌───────────────────────────┐  │ │
│  │  │    RLF Detector       │ │ Throughput Calculator │ │  Interruption Tracker     │  │ │
│  │  │  • T310 timer (1s)    │ │  • Shannon capacity   │ │  • Queue-based tracking   │  │ │
│  │  │  • >= comparison      │ │  • RLF zone degrade   │ │  • Overlap handling       │  │ │
│  │  │  • HO exception       │ │  • Piecewise model    │ │  • 50ms interruption      │  │ │
│  │  └───────────────────────┘ └───────────────────────┘ └───────────────────────────┘  │ │
│  └─────────────────────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────────────────┘
                                           │
                                           ▼
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                                       ML/AI LAYER                                         │
│  ┌─────────────────────────────────────────────────────────────────────────────────────┐ │
│  │                           LightGBM Handover Model                                    │ │
│  │  ┌────────────────────────────────────────────────────────────────────────────────┐ │ │
│  │  │  INPUT FEATURES (12):                                                          │ │ │
│  │  │  ┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐               │ │ │
│  │  │  │ Signal Features  │ │ Distance Features│ │ Mobility Features│               │ │ │
│  │  │  │ • rsrp_serving   │ │ • dist_serving   │ │ • velocity       │               │ │ │
│  │  │  │ • rsrp_neighbor  │ │ • dist_neighbor  │ │ • heading        │               │ │ │
│  │  │  │ • rsrp_diff      │ │ • dist_diff      │ │ • time_since_ho  │               │ │ │
│  │  │  │ • sinr_serving   │ └──────────────────┘ │ • ho_count_1min  │               │ │ │
│  │  │  │ • sinr_neighbor  │                      └──────────────────┘               │ │ │
│  │  │  │ • sinr_diff      │                                                          │ │ │
│  │  │  └──────────────────┘                                                          │ │ │
│  │  └────────────────────────────────────────────────────────────────────────────────┘ │ │
│  │  ┌────────────────────────────────────────────────────────────────────────────────┐ │ │
│  │  │  OUTPUT: handover_probability (0.0 - 1.0)                                      │ │ │
│  │  │  THRESHOLD: ML_CONFIDENCE_THRESHOLD (default: 0.5, QoS-adjusted: 0.6)          │ │ │
│  │  │  CALIBRATION: Isotonic regression for improved probability estimates           │ │ │
│  │  └────────────────────────────────────────────────────────────────────────────────┘ │ │
│  └─────────────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                           │
│  ┌────────────────────────────────┐  ┌────────────────────────────────────────────────┐ │
│  │    SHAP Interpretability       │  │         Ping-Pong Prevention Stack             │ │
│  │  ┌──────────────────────────┐  │  │  ┌──────────────────────────────────────────┐  │ │
│  │  │ Modes:                   │  │  │  │ Layer 1: MIN_DWELL_TIME_S = 3.0s         │  │ │
│  │  │ • OFF (batch)            │  │  │  │ Layer 2: ho_count_last_minute feature    │  │ │
│  │  │ • SAMPLED (10%)          │  │  │  │ Layer 3: QoS-aware confidence boost      │  │ │
│  │  │ • ALWAYS (demo)          │  │  │  └──────────────────────────────────────────┘  │ │
│  │  │ TreeExplainer + safety   │  │  └────────────────────────────────────────────────┘ │
│  │  └──────────────────────────┘  │                                                      │
│  └────────────────────────────────┘                                                      │
└──────────────────────────────────────────────────────────────────────────────────────────┘
                                           │
                                           ▼
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                                       DATA LAYER                                          │
│  ┌─────────────────────┐ ┌─────────────────────┐ ┌──────────────────────────────────┐   │
│  │    PostgreSQL       │ │      MongoDB        │ │       Feast Feature Store        │   │
│  │    (Port 5432)      │ │    (Port 27017)     │ │                                  │   │
│  │  ┌───────────────┐  │ │  ┌───────────────┐  │ │  ┌────────────────────────────┐ │   │
│  │  │ • UE Records  │  │ │  │ • Time Series │  │ │  │ feature_repo/              │ │   │
│  │  │ • Cell Config │  │ │  │ • ML Predictions│ │ │  │  • ue_features.py         │ │   │
│  │  │ • Handover Log│  │ │  │ • Raw Signals │  │ │  │  • cell_features.py        │ │   │
│  │  │ • Experiments │  │ │  │ • SHAP Values │  │ │  │ Offline: Parquet files     │ │   │
│  │  │ • Scenarios   │  │ │  │ • Metrics Hist│  │ │  │ Online: Redis/SQLite       │ │   │
│  │  └───────────────┘  │ │  └───────────────┘  │ │  └────────────────────────────┘ │   │
│  └─────────────────────┘ └─────────────────────┘ └──────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────────────────────┘
                                           │
                                           ▼
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                                  INFRASTRUCTURE LAYER                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────────────┐ │
│  │                              Docker Compose Stack                                    │ │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐    │ │
│  │  │nef-emu   │ │ml-service│ │kinisis-ui│ │ postgres │ │ mongodb  │ │  redis   │    │ │
│  │  │  :8080   │ │  :5050   │ │  :3001   │ │  :5432   │ │  :27017  │ │  :6379   │    │ │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘    │ │
│  └─────────────────────────────────────────────────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────────────────────────────────────────────────┐ │
│  │                              Monitoring Stack                                        │ │
│  │  ┌────────────────────────────┐  ┌────────────────────────────────────────────────┐ │ │
│  │  │ Prometheus (Port 9090)     │  │ Grafana (Port 3000)                            │ │ │
│  │  │ • Service metrics          │  │ • Pre-built dashboards                         │ │ │
│  │  │ • Handover counters        │  │ • Real-time visualization                      │ │ │
│  │  │ • Latency histograms       │  │ • Alert management                             │ │ │
│  │  └────────────────────────────┘  └────────────────────────────────────────────────┘ │ │
│  └─────────────────────────────────────────────────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────────────────────────────────────────────────┐ │
│  │                            Kubernetes (Optional)                                     │ │
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐               │ │
│  │  │ Deployments  │ │  Services    │ │ ConfigMaps   │ │   Ingress    │               │ │
│  │  └──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘               │ │
│  └─────────────────────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## O-RAN Architecture Mapping

This implementation maps to O-RAN Alliance reference architecture:

```
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                              O-RAN Reference Mapping                                      │
│                                                                                           │
│   ┌─────────────────────────────────────────────────────────────────────────────────┐   │
│   │                          Service Management & Orchestration                      │   │
│   │                               (SMO - Non-RT RIC)                                 │   │
│   │   ┌────────────────────────────────────────────────────────────────────────┐    │   │
│   │   │  Kinisis UI ──────────────► Dashboard / Orchestration Interface        │    │   │
│   │   │  MLOps Pipeline ──────────► Model Training & Lifecycle Management      │    │   │
│   │   │  Feast Feature Store ─────► R1 Interface (ML Model Support)            │    │   │
│   │   └────────────────────────────────────────────────────────────────────────┘    │   │
│   └─────────────────────────────────────────────────────────────────────────────────┘   │
│                                          │ A1 Interface (Policy)                         │
│                                          ▼                                               │
│   ┌─────────────────────────────────────────────────────────────────────────────────┐   │
│   │                            Near-RT RIC (10ms - 1s)                               │   │
│   │   ┌────────────────────────────────────────────────────────────────────────┐    │   │
│   │   │  ML Service ──────────────► Handover Optimization xApp                 │    │   │
│   │   │  SHAP Explainer ──────────► Model Interpretability Function            │    │   │
│   │   │  QoS Bias Module ─────────► QoS-Aware Decision Modification            │    │   │
│   │   └────────────────────────────────────────────────────────────────────────┘    │   │
│   └─────────────────────────────────────────────────────────────────────────────────┘   │
│                                          │ E2 Interface (simplified as REST/JSON)       │
│                                          ▼                                               │
│   ┌─────────────────────────────────────────────────────────────────────────────────┐   │
│   │                              E2 Node (RAN Simulation)                            │   │
│   │   ┌────────────────────────────────────────────────────────────────────────┐    │   │
│   │   │  NEF Emulator ────────────► gNB-DU/CU Simulation                       │    │   │
│   │   │  Channel Model ───────────► Radio Channel Simulation                   │    │   │
│   │   │  A3 Rule Engine ──────────► 3GPP Baseline Handover                     │    │   │
│   │   │  Handover Engine ─────────► Decision Execution                         │    │   │
│   │   └────────────────────────────────────────────────────────────────────────┘    │   │
│   └─────────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                           │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

### Protocol Simplifications

| Real O-RAN | This Implementation | Rationale |
|------------|---------------------|-----------|
| ASN.1 + SCTP + E2AP | JSON + HTTP REST | Research focus on algorithms, not protocols |
| E2SM-KPM/RC schemas | Custom JSON schemas | Flexibility for rapid experimentation |
| Complex subscription | Request-response / WebSocket | Simpler to implement and debug |
| Formal Service Models | Custom metrics & controls | Thesis-specific requirements |

### Preserved Architectural Principles

- ✅ **Separation of concerns**: RAN simulator ↔ Intelligent controller
- ✅ **Clear interface boundaries**: Well-defined API contracts
- ✅ **Near-RT latency**: <1 second decision loop
- ✅ **Metrics reporting**: Analogous to E2 Indication
- ✅ **Control actions**: Analogous to E2 Control

---

## Service Layer Details

### 1. NEF Emulator (RAN Simulator)

**Location:** `5g-network-optimization/services/nef-emulator/`
**Technology:** FastAPI (Python 3.10+)
**Port:** 8080

#### Directory Structure

```
nef-emulator/
├── backend/app/app/
│   ├── api/                    # REST API routes
│   │   ├── v1/
│   │   │   ├── endpoints/      # API endpoint handlers
│   │   │   │   ├── ue.py       # UE management
│   │   │   │   ├── cells.py    # Cell management
│   │   │   │   ├── handover.py # Handover operations
│   │   │   │   ├── scenarios.py# Scenario management
│   │   │   │   └── experiments.py # Experiment control
│   │   │   └── api.py          # API router aggregation
│   │   └── deps.py             # Dependency injection
│   ├── handover/               # Handover decision logic
│   │   ├── engine.py           # Main HandoverEngine class
│   │   ├── a3_rule.py          # 3GPP A3 event implementation
│   │   └── runtime.py          # Simulation runtime
│   ├── metrics/                # Metrics and RLF detection
│   │   ├── rlf_detector.py     # RLF detection (Fixes #4,5,6,26,27)
│   │   └── __init__.py
│   ├── network/                # Network state management
│   │   └── state_manager.py    # NetworkStateManager
│   ├── mobility_models/        # UE movement patterns
│   ├── simulation/             # Simulation orchestration
│   └── core/                   # Core utilities
├── rf_models/                  # Channel models (Fixes #3,24,25)
│   ├── channel_model.py        # AR1 shadowing + Rayleigh fading
│   └── path_loss.py            # 3GPP path loss models
├── docs/
│   ├── ORAN_TERMINOLOGY.md     # O-RAN mapping (Fix #9,10)
│   └── antenna_and_path_loss.md
└── tests/
```

#### Key Classes

| Class | File | Responsibility |
|-------|------|----------------|
| `HandoverEngine` | `handover/engine.py` | Orchestrates ML/A3 decisions, manages TTT timers |
| `A3EventRule` | `handover/a3_rule.py` | 3GPP TS 38.331 compliant A3 event |
| `NetworkStateManager` | `network/state_manager.py` | UE state, feature extraction |
| `ChannelModel` | `rf_models/channel_model.py` | AR1 shadowing, Rayleigh fading |
| `RLFDetector` | `metrics/rlf_detector.py` | Radio Link Failure detection |
| `ThroughputCalculator` | `metrics/rlf_detector.py` | SINR-to-throughput mapping |
| `HandoverInterruptionTracker` | `metrics/rlf_detector.py` | Queue-based interruption tracking |

#### Handover Modes

```python
class HandoverEngine:
    # Three operational modes
    handover_mode: Literal["ml", "a3", "hybrid"]
    
    # ML mode: Pure ML-based decisions
    # A3 mode: Pure 3GPP A3 rule
    # Hybrid mode: ML with A3 fallback (recommended)
```

---

### 2. ML Service

**Location:** `5g-network-optimization/services/ml-service/`
**Technology:** Flask (Python 3.10+)
**Port:** 5050

#### Directory Structure

```
ml-service/ml_service/app/
├── api/                        # API routes
│   └── routes.py               # Flask routes
├── models/                     # ML models
│   ├── lightgbm_selector.py    # Primary LightGBM model
│   ├── antenna_selector.py     # Base selector interface
│   ├── interpretability.py     # SHAP utilities (Fixes #14,15,28)
│   ├── ping_pong_prevention.py # Anti-ping-pong logic
│   ├── qos_bias.py             # QoS-aware threshold adjustment
│   ├── onnx_selector.py        # ONNX runtime support
│   ├── ensemble_selector.py    # Ensemble methods
│   └── hyperparameter_tuning.py# Hyperparameter optimization
├── data/                       # Data processing
│   └── feature_extractor.py    # Feature engineering
├── config/                     # Configuration
│   ├── feature_specs.py        # Feature definitions
│   └── constants.py            # Model constants
├── optimization/               # Performance optimization
│   ├── warmup.py               # Model warm-up utilities
│   └── fast_scaler.py          # Optimized scaling
├── auth/                       # Authentication
├── qos/                        # QoS management
└── monitoring/                 # Metrics export
```

#### Model Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│                    LightGBM Handover Classifier                     │
├────────────────────────────────────────────────────────────────────┤
│  Hyperparameters:                                                   │
│  ┌────────────────────────────────────────────────────────────┐    │
│  │ • n_estimators: 100 (env: N_ESTIMATORS)                    │    │
│  │ • max_depth: 10                                            │    │
│  │ • num_leaves: 31                                           │    │
│  │ • learning_rate: 0.1                                       │    │
│  │ • feature_fraction: 1.0                                    │    │
│  │ • random_state: 42 (reproducibility)                       │    │
│  └────────────────────────────────────────────────────────────┘    │
├────────────────────────────────────────────────────────────────────┤
│  Confidence Calibration:                                            │
│  ┌────────────────────────────────────────────────────────────┐    │
│  │ • Method: Isotonic regression (or Platt scaling)           │    │
│  │ • Purpose: Improve probability estimate reliability        │    │
│  │ • Config: CALIBRATE_CONFIDENCE=true, CALIBRATION_METHOD    │    │
│  └────────────────────────────────────────────────────────────┘    │
├────────────────────────────────────────────────────────────────────┤
│  Input Features (12):                                               │
│  ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────────┐   │
│  │ Signal (6)      │ │ Distance (3)    │ │ Mobility (3)        │   │
│  │ rsrp_serving    │ │ dist_serving    │ │ velocity            │   │
│  │ rsrp_neighbor   │ │ dist_neighbor   │ │ heading             │   │
│  │ rsrp_diff       │ │ dist_diff       │ │ time_since_last_ho  │   │
│  │ sinr_serving    │ └─────────────────┘ │ ho_count_last_min   │   │
│  │ sinr_neighbor   │                     └─────────────────────┘   │
│  │ sinr_diff       │                                               │
│  └─────────────────┘                                               │
├────────────────────────────────────────────────────────────────────┤
│  Output:                                                            │
│  ┌────────────────────────────────────────────────────────────┐    │
│  │ • handover_probability: float [0.0, 1.0]                   │    │
│  │ • recommended_action: "handover" | "stay"                  │    │
│  │ • confidence: float (calibrated probability)               │    │
│  │ • shap_values: Optional[Dict] (if SHAP enabled)            │    │
│  └────────────────────────────────────────────────────────────┘    │
└────────────────────────────────────────────────────────────────────┘
```

#### SHAP Configuration (Fixes #14, #15, #28)

```python
class SHAPMode(Enum):
    OFF = "off"           # Disabled (fastest, for batch experiments)
    SAMPLED = "sampled"   # Computed for X% of decisions (default 10%)
    ALWAYS = "always"     # Computed for every decision (UI/demo)

@dataclass
class SHAPConfig:
    mode: SHAPMode = SHAPMode.OFF
    sample_rate: float = 0.1
    validate_additivity: bool = False
    additivity_tolerance: float = 0.01
```

---

### 3. Kinisis UI

**Location:** `5g-network-optimization/services/kinisis_ui/`
**Technology:** React 18 + Vite + Leaflet
**Port:** 3001

#### Directory Structure

```
kinisis_ui/
├── src/
│   ├── pages/
│   │   ├── MapPage.jsx         # Interactive map with UE/cell markers
│   │   ├── Dashboard.jsx       # Overview metrics and charts
│   │   ├── Scenarios.jsx       # Scenario selection and config
│   │   ├── Metrics.jsx         # Detailed metrics view
│   │   └── Config.jsx          # System configuration
│   ├── components/
│   │   ├── SignalPanel.jsx     # UE signal quality table
│   │   ├── RealTimeMetrics.jsx # WebSocket metrics display
│   │   ├── RetryModal.jsx      # ML service retry UI
│   │   ├── AntennaMarkers.jsx  # Cell visualization
│   │   ├── UEMarker.jsx        # UE position markers
│   │   └── UETrajectory.jsx    # Movement path visualization
│   ├── services/
│   │   ├── api.js              # REST API client
│   │   └── websocket.js        # WebSocket connection
│   └── hooks/
│       └── useWebSocket.js     # WebSocket React hook
├── public/
└── vite.config.js
```

---

## Core Subsystems

### Channel Model Subsystem

**Location:** `nef-emulator/rf_models/channel_model.py`

Implements thesis Fixes #3, #24, #25:

```
┌───────────────────────────────────────────────────────────────────────────────┐
│                            Channel Model Pipeline                              │
│                                                                                │
│   UE Position ──► Path Loss ──► Shadowing ──► Fading ──► Total Loss ──► RSRP │
│       │              │             │            │                             │
│       │              ▼             ▼            ▼                             │
│       │         ┌─────────┐  ┌─────────┐  ┌─────────┐                        │
│       │         │3GPP ABG │  │  AR1    │  │Rayleigh │                        │
│       │         │ PL(d,f) │  │  σ=4dB  │  │ Doppler │                        │
│       │         │ α,β,γ   │  │ d_c=37m │  │ aware   │                        │
│       │         └─────────┘  └─────────┘  └─────────┘                        │
│       │                                                                       │
│  ┌────┴────────────────────────────────────────────────────────────────────┐ │
│  │ Fix #3: RSRP = TX_power - path_loss - shadowing - fading_loss           │ │
│  │         (All components properly signed)                                 │ │
│  └──────────────────────────────────────────────────────────────────────────┘ │
│                                                                                │
│  ┌──────────────────────────────────────────────────────────────────────────┐ │
│  │ Fix #24: Doppler Division-by-Zero Protection                             │ │
│  │ if velocity < 0.1 m/s:                                                   │ │
│  │     coherence_time = 10.0s  # Stationary UE                              │ │
│  │ else:                                                                    │ │
│  │     f_d = (velocity * f_c) / c  # Doppler frequency                      │ │
│  │     coherence_time = 0.423 / f_d                                         │ │
│  └──────────────────────────────────────────────────────────────────────────┘ │
│                                                                                │
│  ┌──────────────────────────────────────────────────────────────────────────┐ │
│  │ Fix #25: Shadowing Initial Seeding                                       │ │
│  │ if first_call:                                                           │ │
│  │     shadowing = N(0, σ_SF)  # Draw from target distribution              │ │
│  │ else:                                                                    │ │
│  │     ρ = exp(-distance_moved / d_corr)  # AR1 correlation                 │ │
│  │     shadowing = ρ * prev_shadowing + √(1-ρ²) * N(0, σ_SF)               │ │
│  └──────────────────────────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────────────────────────┘
```

### Handover Engine Subsystem

**Location:** `nef-emulator/backend/app/app/handover/engine.py`

```
┌───────────────────────────────────────────────────────────────────────────────┐
│                          Handover Decision Flow                                │
│                                                                                │
│   evaluate_handover(ue_id) ─────────────────────────────────────────────────► │
│          │                                                                     │
│          ▼                                                                     │
│   ┌──────────────────────────────────────────────────────────────────────┐   │
│   │                     Check Ping-Pong Prevention                        │   │
│   │  ┌─────────────────────────────────────────────────────────────────┐ │   │
│   │  │ Layer 1: if time_since_last_ho < MIN_DWELL_TIME_S (3.0s):       │ │   │
│   │  │              return STAY (too soon for another handover)        │ │   │
│   │  └─────────────────────────────────────────────────────────────────┘ │   │
│   └──────────────────────────────────────────────────────────────────────┘   │
│          │                                                                     │
│          ▼                                                                     │
│   ┌──────────────────────────────────────────────────────────────────────┐   │
│   │              Mode Selection: ML / A3 / Hybrid                         │   │
│   │                                                                       │   │
│   │   ML Mode:        A3 Mode:           Hybrid Mode:                     │   │
│   │   ┌─────┐         ┌─────┐            ┌──────────────────────┐         │   │
│   │   │ ML  │         │ A3  │            │ Try ML → Fallback A3 │         │   │
│   │   │ API │         │Rule │            │ if ML unavailable    │         │   │
│   │   └──┬──┘         └──┬──┘            └──────────┬───────────┘         │   │
│   │      │               │                          │                     │   │
│   └──────┴───────────────┴──────────────────────────┴─────────────────────┘   │
│          │                                                                     │
│          ▼                                                                     │
│   ┌──────────────────────────────────────────────────────────────────────┐   │
│   │                   Per-UE TTT Timer Management                         │   │
│   │  _ttt_timers: Dict[ue_id, Dict[target_cell, start_time]]             │   │
│   │                                                                       │   │
│   │  if A3_satisfied and target not in timers:                           │   │
│   │      start_timer(ue_id, target_cell)                                 │   │
│   │  if timer_expired(TTT_S):                                            │   │
│   │      execute_handover()                                              │   │
│   │  if A3_not_satisfied:                                                │   │
│   │      clear_timer(ue_id, target_cell)                                 │   │
│   └──────────────────────────────────────────────────────────────────────┘   │
│          │                                                                     │
│          ▼                                                                     │
│   ┌──────────────────────────────────────────────────────────────────────┐   │
│   │               QoS-Aware Threshold Adjustment (Layer 3)                │   │
│   │  if current_cell_qos_good:                                           │   │
│   │      effective_threshold = ML_CONFIDENCE_THRESHOLD * 1.2             │   │
│   │      # Harder to trigger handover from good cell                     │   │
│   └──────────────────────────────────────────────────────────────────────┘   │
│          │                                                                     │
│          ▼                                                                     │
│   HANDOVER / STAY Decision ◄─────────────────────────────────────────────────│
│                                                                                │
└───────────────────────────────────────────────────────────────────────────────┘
```

### Metrics & RLF Detection Subsystem

**Location:** `nef-emulator/backend/app/app/metrics/rlf_detector.py`

Implements thesis Fixes #4, #5, #6, #26, #27:

```
┌───────────────────────────────────────────────────────────────────────────────┐
│                           RLF Detection Pipeline                               │
│                                                                                │
│   SINR Input ────────────────────────────────────────────────────────────────►│
│        │                                                                       │
│        ▼                                                                       │
│   ┌─────────────────────────────────────────────────────────────────────────┐ │
│   │ Fix #26: Handover Interruption Exception                                │ │
│   │ if ue.in_handover_interruption:                                         │ │
│   │     clear_rlf_timer(ue_id)  # Don't count normal HO as RLF              │ │
│   │     return False                                                         │ │
│   └─────────────────────────────────────────────────────────────────────────┘ │
│        │                                                                       │
│        ▼                                                                       │
│   ┌─────────────────────────────────────────────────────────────────────────┐ │
│   │ Fix #4: Timer Precision (>= comparison)                                 │ │
│   │ if SINR < -6.0 dB:                                                      │ │
│   │     if timer not started:                                               │ │
│   │         start_timer(current_time)                                       │ │
│   │     elif (current_time - timer_start) >= 1.0s:  # Fix: >= not >         │ │
│   │         declare_rlf()                                                   │ │
│   │ else:                                                                   │ │
│   │     clear_timer()  # Signal recovered                                   │ │
│   └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                                │
└───────────────────────────────────────────────────────────────────────────────┘

┌───────────────────────────────────────────────────────────────────────────────┐
│                     Throughput Calculation (Fix #5)                            │
│                                                                                │
│   SINR ──────────────────────────────────────────────────────────────────────►│
│     │                                                                          │
│     ├─── SINR < -10 dB ────► Throughput = 0 (No connection)                   │
│     │                                                                          │
│     ├─── -10 ≤ SINR < -6 ──► Throughput = BW × 0.5 bits/Hz (RLF zone)        │
│     │                        (Graceful degradation, not cliff)                │
│     │                                                                          │
│     └─── SINR ≥ -6 dB ─────► Shannon capacity: BW × log2(1 + SINR_linear)    │
│                                                                                │
└───────────────────────────────────────────────────────────────────────────────┘

┌───────────────────────────────────────────────────────────────────────────────┐
│               Handover Interruption Tracking (Fixes #6, #27)                   │
│                                                                                │
│   ┌─────────────────────────────────────────────────────────────────────────┐ │
│   │ Fix #27: Queue-based tracking (not single timestamp)                    │ │
│   │                                                                          │ │
│   │ interruptions: Deque[HandoverInterruption]                              │ │
│   │                                                                          │ │
│   │ When handover executes:                                                 │ │
│   │     interruptions.append(HandoverInterruption(                          │ │
│   │         start_time=current_time,                                        │ │
│   │         end_time=current_time + 50ms                                    │ │
│   │     ))                                                                  │ │
│   │                                                                          │ │
│   │ Fix #6: Check if ANY interruption covers current time                   │ │
│   │ is_interrupted = any(                                                   │ │
│   │     intr.start <= current_time < intr.end                              │ │
│   │     for intr in interruptions                                          │ │
│   │ )                                                                       │ │
│   └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                                │
└───────────────────────────────────────────────────────────────────────────────┘
```

### ML Prediction Pipeline

```
┌───────────────────────────────────────────────────────────────────────────────┐
│                         ML Service Prediction Pipeline                         │
│                                                                                │
│   HTTP POST /predict ────────────────────────────────────────────────────────►│
│        │                                                                       │
│        ▼                                                                       │
│   ┌──────────────────────────────────────────────────────────────────────┐   │
│   │                     Feature Extraction                                │   │
│   │  Raw UE State ──► Feature Transformer ──► 12-Feature Vector          │   │
│   │                                                                       │   │
│   │  Signal:    [rsrp_s, rsrp_n, Δrsrp, sinr_s, sinr_n, Δsinr]          │   │
│   │  Distance:  [dist_s, dist_n, Δdist]                                  │   │
│   │  Mobility:  [velocity, heading, time_since_ho, ho_count_1min]        │   │
│   └──────────────────────────────────────────────────────────────────────┘   │
│        │                                                                       │
│        ▼                                                                       │
│   ┌──────────────────────────────────────────────────────────────────────┐   │
│   │                     Feature Scaling                                   │   │
│   │  StandardScaler (fitted during training)                             │   │
│   │  X_scaled = (X - μ) / σ                                              │   │
│   └──────────────────────────────────────────────────────────────────────┘   │
│        │                                                                       │
│        ▼                                                                       │
│   ┌──────────────────────────────────────────────────────────────────────┐   │
│   │                     LightGBM Prediction                               │   │
│   │  probability = model.predict_proba(X_scaled)[0, 1]                   │   │
│   └──────────────────────────────────────────────────────────────────────┘   │
│        │                                                                       │
│        ▼                                                                       │
│   ┌──────────────────────────────────────────────────────────────────────┐   │
│   │                 Confidence Calibration (Optional)                     │   │
│   │  if calibrated_model:                                                │   │
│   │      calibrated_prob = calibrated_model.predict_proba(X_scaled)[0,1] │   │
│   └──────────────────────────────────────────────────────────────────────┘   │
│        │                                                                       │
│        ▼                                                                       │
│   ┌──────────────────────────────────────────────────────────────────────┐   │
│   │              SHAP Explanation (if mode != OFF)                        │   │
│   │  Fix #14: Robust extraction handles format variants                  │   │
│   │  Fix #15: Mode-based computation (OFF/SAMPLED/ALWAYS)                │   │
│   └──────────────────────────────────────────────────────────────────────┘   │
│        │                                                                       │
│        ▼                                                                       │
│   Response: {probability, recommendation, confidence, shap_values?} ◄────────│
│                                                                                │
└───────────────────────────────────────────────────────────────────────────────┘
```

---

## Data Layer

### Database Schema Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              PostgreSQL                                      │
│                                                                              │
│  ┌────────────────────┐  ┌────────────────────┐  ┌────────────────────────┐ │
│  │      ue_table      │  │    cell_table      │  │   handover_log         │ │
│  ├────────────────────┤  ├────────────────────┤  ├────────────────────────┤ │
│  │ ue_id (PK)         │  │ cell_id (PK)       │  │ id (PK)                │ │
│  │ position_x         │  │ position_x         │  │ ue_id (FK)             │ │
│  │ position_y         │  │ position_y         │  │ source_cell (FK)       │ │
│  │ position_z         │  │ tx_power_dbm       │  │ target_cell (FK)       │ │
│  │ velocity           │  │ frequency_ghz      │  │ timestamp              │ │
│  │ heading            │  │ cell_radius_m      │  │ trigger_reason         │ │
│  │ serving_cell (FK)  │  │ antenna_height_m   │  │ rsrp_before            │ │
│  │ created_at         │  │ created_at         │  │ rsrp_after             │ │
│  │ updated_at         │  └────────────────────┘  │ ml_confidence          │ │
│  └────────────────────┘                          │ was_ping_pong          │ │
│                                                  └────────────────────────┘ │
│  ┌────────────────────┐  ┌────────────────────┐                             │
│  │  experiment_table  │  │   scenario_table   │                             │
│  ├────────────────────┤  ├────────────────────┤                             │
│  │ id (PK)            │  │ id (PK)            │                             │
│  │ name               │  │ name               │                             │
│  │ scenario_id (FK)   │  │ description        │                             │
│  │ algorithm          │  │ duration_s         │                             │
│  │ seed               │  │ ue_count           │                             │
│  │ started_at         │  │ cell_count         │                             │
│  │ completed_at       │  │ config_json        │                             │
│  │ results_json       │  └────────────────────┘                             │
│  └────────────────────┘                                                      │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                               MongoDB                                        │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ Collection: metrics_timeseries                                         │ │
│  │ {                                                                      │ │
│  │   "timestamp": ISODate,                                                │ │
│  │   "ue_id": string,                                                     │ │
│  │   "cell_id": string,                                                   │ │
│  │   "rsrp": float,                                                       │ │
│  │   "rsrq": float,                                                       │ │
│  │   "sinr": float,                                                       │ │
│  │   "throughput_mbps": float                                             │ │
│  │ }                                                                      │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ Collection: ml_predictions                                             │ │
│  │ {                                                                      │ │
│  │   "timestamp": ISODate,                                                │ │
│  │   "ue_id": string,                                                     │ │
│  │   "features": {...},                                                   │ │
│  │   "probability": float,                                                │ │
│  │   "decision": string,                                                  │ │
│  │   "shap_values": {...}  // Optional                                    │ │
│  │ }                                                                      │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Feast Feature Store

**Location:** `mlops/feast_repo/`

```
feast_repo/
├── feature_store.yaml          # Feast configuration
├── feature_repo.py             # Feature definitions
├── constants.py                # Feature constants
└── data/
    └── *.parquet               # Offline feature data
```

---

## Scripts & Analysis Framework

**Location:** `scripts/`

```
scripts/
├── core/
│   └── reproducibility.py      # Fix #1: Seed propagation
├── validation/
│   ├── distance_units.py       # Fix #2: Unit validation
│   └── a3_baseline_criteria.py # Fix #7: A3 acceptance criteria
├── analysis/
│   ├── statistical_analysis.py # Fixes #16,17,18,19
│   └── sample_collector.py     # Fix #8: Sample collection
├── experiments/
│   └── experimental_config.py  # Fixes #11,12,13
├── visualization/
│   ├── publication_plots.py    # Fix #20: Publication standards
│   └── shap_validation.py      # Fixes #14,28,29
├── benchmarking/
│   └── performance_benchmark.py# Fix #22: Performance protocol
├── scenarios/
│   ├── highway_handover.py
│   └── smart_city_downtown.py
├── data_generation/
│   └── synthetic_generator.py
└── run_enhanced_experiment.py  # Main experiment runner
```

### Statistical Analysis (Fixes #16-19)

```python
# Fix #16: Paired t-test (not independent)
from scipy.stats import ttest_rel, wilcoxon

# Fix #17: Cohen's d_z for paired data
def calculate_cohens_d_z(differences):
    return np.mean(differences) / np.std(differences, ddof=1)

# Fix #18: Bonferroni correction
def apply_bonferroni(p_value, n_comparisons):
    return min(p_value * n_comparisons, 1.0)

# Fix #19: Bootstrap CI (maintains pairing)
def bootstrap_ci(a3_values, ml_values, n_iterations=10000):
    # Resample PAIRS, not independently
    ...
```

### Experimental Configuration (Fixes #11-13)

```python
# Fix #11: Tier-based experiment matrix
# Tier 1: 40 runs (2 scenarios × 2 algorithms × 10 seeds)
# Tier 2: Extended sensitivity analysis
# Tier 3: Full 270 combinations (future work)

# Fix #12: Seed selection strategy
class SeedStrategy(Enum):
    SEQUENTIAL = "sequential"  # 1, 2, 3, ...
    PRIMES = "primes"          # 2, 3, 5, 7, 11, ...
    HASH_BASED = "hash"        # Deterministic from metadata

# Fix #13: Realistic runtime estimation
# Per-run: 8-10 minutes average
# Tier 1 (40 runs): 6-8 hours
```

---

## MLOps Pipeline

**Location:** `mlops/`

```
mlops/
├── data_pipeline/
│   └── nef_collector.py        # Collect training data from NEF
├── feast_repo/
│   ├── feature_store.yaml      # Feast config
│   └── feature_repo.py         # Feature definitions
└── feature_store/
    └── feature_repo/           # Feature repository
```

### Training Data Pipeline

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Training Data Pipeline                               │
│                                                                              │
│  NEF Simulator ──► Data Collector ──► Feature Engineering ──► Feast Store  │
│       │                 │                    │                    │         │
│       ▼                 ▼                    ▼                    ▼         │
│  ┌─────────┐      ┌──────────┐        ┌───────────┐       ┌───────────┐    │
│  │Raw UE   │      │ MongoDB  │        │ Transform │       │ Parquet   │    │
│  │States   │      │ Storage  │        │ Pipeline  │       │ Files     │    │
│  └─────────┘      └──────────┘        └───────────┘       └───────────┘    │
│                                                                              │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ Feature Engineering:                                                  │  │
│  │  • Compute RSRP/SINR differences                                     │  │
│  │  • Calculate distances to cells                                      │  │
│  │  • Derive velocity from position history                             │  │
│  │  • Count recent handovers (ping-pong indicator)                      │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Testing Infrastructure

**Location:** `tests/`

```
tests/
├── conftest.py                 # Pytest configuration (portable paths)
├── core/
│   └── test_reproducibility.py # Fix #1 tests
├── validation/
│   └── test_distance_units.py  # Fix #2 tests
├── metrics/
│   └── test_rlf_detector.py    # Fixes #4,5,6,26,27 tests
├── rf_model_tests/
│   └── test_channel_model.py   # Fixes #3,24,25 tests
├── analysis/
│   ├── test_sample_collector.py     # Fix #8 tests
│   └── test_statistical_analysis.py # Fixes #16-19 tests
├── integration/
│   ├── test_handover_coverage_loss.py
│   ├── test_multi_antenna_scenarios.py
│   └── test_thesis_claims.py   # Validate thesis claims
└── ml_system/
    └── test_shap_validation.py # Fixes #14,28,29 tests
```

### Test Categories

| Category | Purpose | Key Tests |
|----------|---------|-----------|
| **Unit Tests** | Component isolation | Channel model, RLF detector |
| **Integration Tests** | Service interaction | Handover flow, API contracts |
| **Validation Tests** | Thesis fix verification | All 29 fixes covered |
| **ML System Tests** | Model behavior | SHAP, predictions, calibration |
| **Thesis Claims Tests** | Result validation | Ping-pong elimination, improvements |

---

## Deployment Architecture

### Docker Compose (Development/Testing)

```yaml
# docker-compose.yml structure
services:
  nef-emulator:
    build: ./services/nef-emulator
    ports: ["8080:8080"]
    depends_on: [postgres, mongodb]
    
  ml-service:
    build: ./services/ml-service
    ports: ["5050:5050"]
    environment:
      - ML_CONFIDENCE_THRESHOLD=0.5
      - SHAP_MODE=off
    
  kinisis-ui:
    build: ./services/kinisis_ui
    ports: ["3001:3001"]
    depends_on: [nef-emulator]
    
  postgres:
    image: postgres:14-alpine
    ports: ["5432:5432"]
    
  mongodb:
    image: mongo:6
    ports: ["27017:27017"]
    
  prometheus:
    image: prom/prometheus
    ports: ["9090:9090"]
    
  grafana:
    image: grafana/grafana
    ports: ["3000:3000"]
```

### Kubernetes (Production)

**Location:** `deployment/kubernetes/`

```
kubernetes/
├── deployments/
│   ├── nef-emulator.yaml
│   ├── ml-service.yaml
│   └── kinisis-ui.yaml
├── services/
│   ├── nef-emulator-svc.yaml
│   ├── ml-service-svc.yaml
│   └── kinisis-ui-svc.yaml
├── configmaps/
│   └── app-config.yaml
└── ingress/
    └── ingress.yaml
```

---

## Data Flows

### Real-Time Metrics Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Real-Time Metrics WebSocket Flow                      │
│                                                                              │
│  Kinisis UI ◄───── WebSocket ─────► NEF Emulator ◄───► Simulation Loop     │
│      │                │                   │                  │              │
│      │                │                   │                  │              │
│      ▼                ▼                   ▼                  ▼              │
│  ┌─────────┐    ┌──────────┐       ┌───────────┐      ┌───────────┐        │
│  │ Render  │    │  Parse   │       │  Collect  │      │  Channel  │        │
│  │ Charts  │    │  JSON    │       │  Metrics  │      │  Update   │        │
│  │ & Map   │    │ Messages │       │  100ms    │      │  100ms    │        │
│  └─────────┘    └──────────┘       └───────────┘      └───────────┘        │
│                                                                              │
│  Message Format:                                                             │
│  {                                                                          │
│    "type": "metrics",                                                       │
│    "timestamp": "2026-01-21T12:00:00Z",                                     │
│    "ues": [                                                                 │
│      {"ue_id": "ue001", "rsrp": -85.2, "sinr": 12.5, "cell": "cell_1"},   │
│      ...                                                                    │
│    ],                                                                       │
│    "handovers_total": 15,                                                   │
│    "pingpong_count": 0                                                      │
│  }                                                                          │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Handover Decision Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Handover Decision Sequence                           │
│                                                                              │
│  ┌───────────┐  1. evaluate   ┌───────────────┐  2. features  ┌──────────┐ │
│  │Simulation │ ─────────────► │ Handover      │ ────────────► │   ML     │ │
│  │   Loop    │                │   Engine      │               │ Service  │ │
│  └───────────┘                └───────────────┘               └──────────┘ │
│                                      │                              │       │
│                                      │ 3. A3 check                  │       │
│                                      ▼                              │       │
│                               ┌───────────────┐                     │       │
│                               │  A3EventRule  │                     │       │
│                               │  (baseline)   │                     │       │
│                               └───────────────┘                     │       │
│                                      │                              │       │
│                                      ▼                              │       │
│                               ┌───────────────┐  4. probability    │       │
│                               │   Decision    │ ◄─────────────────┘       │
│                               │    Merger     │                           │
│                               └───────────────┘                           │
│                                      │                                    │
│                                      │ 5. execute if approved             │
│                                      ▼                                    │
│                               ┌───────────────┐                           │
│                               │   Execute     │                           │
│                               │   Handover    │                           │
│                               └───────────────┘                           │
│                                      │                                    │
│                                      │ 6. record metrics                  │
│                                      ▼                                    │
│                               ┌───────────────┐                           │
│                               │   Metrics     │                           │
│                               │   Database    │                           │
│                               └───────────────┘                           │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Configuration Reference

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| **NEF Emulator** | | |
| `A3_HYSTERESIS_DB` | 2.0 | A3 hysteresis margin in dB |
| `A3_TTT_S` | 0.0 | Time-to-Trigger (0 = per-UE) |
| `MIN_DWELL_TIME_S` | 3.0 | Minimum time in cell |
| `ML_HANDOVER_ENABLED` | true | Enable ML mode |
| `ML_SERVICE_URL` | http://ml-service:5050 | ML service endpoint |
| `ML_CONFIDENCE_THRESHOLD` | 0.5 | Decision threshold |
| **ML Service** | | |
| `N_ESTIMATORS` | 100 | LightGBM trees |
| `CALIBRATE_CONFIDENCE` | true | Enable calibration |
| `SHAP_ENABLED` | false | Enable SHAP |
| `SHAP_MODE` | off | off/sampled/always |
| `SHAP_SAMPLE_RATE` | 0.1 | Sampling rate |
| **Reproducibility** | | |
| `EXPERIMENT_SEED` | 42 | Random seed |

### Configuration Files

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Service orchestration |
| `requirements.lock` | Locked Python dependencies (Fix #21) |
| `feature_store.yaml` | Feast configuration |
| `prometheus.yml` | Metrics collection |
| `grafana/dashboards/*.json` | Pre-built dashboards |

---

## API Reference

### NEF Emulator API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/ue/` | GET | List all UEs |
| `/api/v1/ue/{ue_id}` | GET | Get UE details |
| `/api/v1/ue/{ue_id}/state` | GET | Get UE signal state |
| `/api/v1/cells/` | GET | List all cells |
| `/api/v1/cells/{cell_id}` | GET | Get cell details |
| `/api/v1/handover/trigger` | POST | Trigger handover |
| `/api/v1/handover/evaluate` | POST | Evaluate decision |
| `/api/v1/scenarios/` | GET | List scenarios |
| `/api/v1/scenarios/{id}/start` | POST | Start scenario |
| `/api/v1/experiments/start` | POST | Start experiment |
| `/api/v1/experiments/stop` | POST | Stop experiment |
| `/ws/metrics` | WS | Real-time metrics |

### ML Service API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/predict` | POST | Get handover prediction |
| `/predict/batch` | POST | Batch predictions |
| `/health` | GET | Health check |
| `/metrics` | GET | Model metrics |
| `/model/info` | GET | Model information |
| `/feedback` | POST | Submit feedback |

---

## Document History

| Version | Date | Changes |
|---------|------|---------|
| 2.1 | March 2026 | Consolidated from SYSTEM_ARCHITECTURE_FULL.md; removed duplicate quick-start |
| 2.0 | January 2026 | Complete rewrite with all 29 thesis fixes documented |
| 1.0 | December 2025 | Initial architecture documentation |

---

*This document provides the complete technical architecture of the 5G Network Optimization thesis implementation. For O-RAN terminology clarification, see [ORAN_TERMINOLOGY.md](../5g-network-optimization/services/nef-emulator/docs/ORAN_TERMINOLOGY.md). For operations and deployment, see [MANUAL.md](./MANUAL.md). For thesis methodology and reproducibility, see [THESIS.md](./THESIS.md).*
