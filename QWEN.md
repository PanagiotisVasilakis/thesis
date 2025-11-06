# Thesis Project Context: 5G Network Optimization with ML-based Handover

## Project Overview

This is a comprehensive 5G network optimization thesis project that demonstrates how machine learning significantly improves handover decisions in complex multi-antenna environments compared to traditional 3GPP A3 rule-based approaches. The system implements a Network Exposure Function (NEF) emulator integrated with an ML-powered antenna selection service to handle edge cases that challenge conventional handover mechanisms.

### Architecture

The system follows a microservices architecture:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                   5G Network Optimization System                        │
│                                                                         │
│  ┌─────────────────────┐            ┌──────────────────────────────┐    │
│  │                     │            │                              │    │
│  │   NEF Emulator      │◄───────────┤    ML Service                │    │
│  │   (Original)        │            │    - Antenna Selection       │    │
│  │                     │────────────┤    - Performance Metrics     │    │
│  │                     │            │    - Decision Engine         │    │
│  └─────────────────────┘            └──────────────────────────────┘    │
│           │                                        │                    │
│           ▼                                        ▼                    │
│  ┌─────────────────────┐            ┌──────────────────────────────┐    │
│  │                     │            │                              │    │
│  │   3GPP Mobility     │────────────┤    Monitoring & Evaluation   │    │
│  │   Models            │            │    - Prometheus              │    │
│  │                     │            │    - Grafana                 │    │
│  └─────────────────────┘            └──────────────────────────────┘    │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### Key Components

1. **NEF Emulator** (FastAPI-based):
   - 3GPP-compliant Network Exposure Function
   - Supports 8+ mobility models (Linear, L-Shaped, Random Waypoint, Manhattan Grid, etc.)
   - Implements A3 event rule for fallback scenarios
   - PostgreSQL + MongoDB for network state management

2. **ML Service** (Flask-based):
   - LightGBM/LSTM model support for antenna selection
   - QoS-aware prediction with service priority gating
   - Real-time confidence scoring
   - JWT authentication and rate limiting

3. **Monitoring Stack**:
   - Prometheus metrics collection
   - Grafana dashboards for visualization
   - Custom metrics: handover decisions, fallbacks, QoS compliance, prediction confidence

## Building and Running

### Prerequisites
- Python 3.10+
- Docker and Docker Compose
- Git

### Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt
# or use helper script
./scripts/install_deps.sh --skip-if-present

# 2. Start system (ML mode)
ML_HANDOVER_ENABLED=1 docker compose -f 5g-network-optimization/docker-compose.yml up --build

# 3. Start system (A3 rule mode)
ML_HANDOVER_ENABLED=0 docker compose -f 5g-network-optimization/docker-compose.yml up --build

# 4. Access services
# NEF Emulator: http://localhost:8080
# ML Service: http://localhost:5050
# Grafana: http://localhost:3000 (admin/admin)
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `ML_HANDOVER_ENABLED` | Enable ML-driven handovers | `false` |
| `ML_SERVICE_URL` | URL of the ML service | `http://ml-service:5050` |
| `A3_HYSTERESIS_DB` | Hysteresis value in dB for A3 event | `2.0` |
| `A3_TTT_S` | Time-to-trigger in seconds for A3 event | `0.0` |
| `MIN_HANDOVER_INTERVAL_S` | Minimum seconds between handovers | `2.0` |
| `MAX_HANDOVERS_PER_MINUTE` | Maximum handovers in 60-second window | `3` |
| `PINGPONG_WINDOW_S` | Time window for detecting ping-pong returns | `10.0` |
| `CALIBRATE_CONFIDENCE` | Enable ML confidence calibration | `1` (enabled) |

### Testing

```bash
# Run all tests
pytest

# Run tests with coverage
./scripts/run_tests.sh

# Run specific test file
pytest tests/data_generation/test_synthetic_generator.py

# Run integration tests
pytest 5g-network-optimization/services/nef-emulator/tests/integration \
       5g-network-optimization/services/ml-service/tests/integration
```

## Development Conventions

### Code Structure

```
thesis/
├── 5g-network-optimization/           # Main project code
│   ├── services/
│   │   ├── ml-service/               # ML service code
│   │   │   ├── ml_service/
│   │   │   │   ├── app/
│   │   │   │   │   ├── models/       # ML models (LightGBM, LSTM)
│   │   │   │   │   ├── api/          # API endpoints
│   │   │   │   │   └── core/         # Core logic
│   │   │   │   └── tests/            # ML service tests
│   │   └── nef-emulator/             # NEF emulator code
│   │       └── backend/
│   │           └── app/
│   │               ├── app/
│   │               │   ├── handover/ # Handover logic
│   │               │   ├── network/   # Network state management
│   │               │   └── mobility_models/ # Mobility models
│   │               └── tests/         # NEF emulator tests
│   ├── deployment/                   # Kubernetes manifests
│   ├── monitoring/                   # Prometheus/Grafana config
│   └── docker-compose.yml            # Local orchestration
├── scripts/                          # Utility scripts
├── docs/                            # Comprehensive documentation
├── tests/                           # General tests
└── requirements.txt                 # Python dependencies
```

### Testing Strategy

- Unit tests with pytest (90%+ coverage)
- Integration tests for service communication
- End-to-end tests for complete workflows
- Thesis-specific validation tests
- Performance and stress tests

### Documentation

Comprehensive documentation is available in the `docs/` directory:
- `QUICK_START.md`: Essential commands
- `COMPLETE_DEPLOYMENT_GUIDE.md`: Full setup guide
- `THESIS_ABSTRACT.md`: Research overview
- `RESULTS_GENERATION_CHECKLIST.md`: Experiment workflow
- `PING_PONG_PREVENTION.md`: Feature documentation
- `QOS_INTEGRATION_PLAN.md`: QoS enhancement roadmap

### Key Features Implemented

✅ 3GPP-compliant NEF emulator  
✅ 8 mobility models (3GPP TR 38.901)  
✅ ML-based antenna selection (LightGBM, LSTM, Ensemble)  
✅ QoS-aware predictions with confidence gating  
✅ Automatic fallback to A3 rule  
✅ Real-time monitoring (Prometheus + Grafana)  
✅ Synthetic QoS dataset generator  
✅ Live data collection from NEF  
✅ Feature store integration (Feast)  
✅ JWT authentication & rate limiting  
✅ Circuit breakers & retry logic  
✅ Data drift detection & auto-retraining  
✅ Comprehensive test suite (90%+ coverage)  
✅ Docker Compose & Kubernetes deployment  
✅ Visualization APIs (coverage maps, trajectories)  
✅ Ping-pong prevention with 70-85% reduction  
✅ Automated ML vs A3 comparison tool  

### Core Hypothesis and Results

The thesis demonstrates that machine learning provides significant advantages over traditional rule-based handover mechanisms in complex 5G scenarios:

- **Ping-pong reduction**: ML reduces handover oscillations by 70-85% compared to A3 rules
- **Multi-antenna optimization**: ML handles complex scenarios with 3+ overlapping antennas better than A3 rules
- **QoS compliance**: ML maintains service-specific requirements (URLLC, eMBB, mMTC) with higher success rates
- **Adaptive behavior**: ML learns from network performance feedback and adapts decisions over time

### Research Contributions

1. **Open-Source NEF Emulator**: Full 3GPP-compliant implementation for research
2. **ML-Native Handover Architecture**: Design patterns for integrating ML into 5G core
3. **QoS-Aware Prediction Framework**: Novel confidence gating based on service priorities
4. **Comprehensive Test Suite**: Validation methodology for 5G ML systems
5. **Synthetic Data Generator**: 3GPP-aligned QoS dataset creation tool
6. **Production-Ready Deployment**: Docker/Kubernetes manifests for real-world usage
7. **Ping-pong Prevention**: Three-layer mechanism for reducing handover oscillations

### Synthetic QoS Dataset Generator

The thesis includes a dependency-free synthetic generator that creates reproducible datasets for experimentation with enhanced Mobile Broadband (eMBB), Ultra-Reliable Low-Latency Communications (URLLC), massive Machine-Type Communications (mMTC), and a fall-back `default` profile.

**CSV schema**:
- `request_id`: Stable identifier (e.g., `req_000000`)
- `service_type`: One of `embb`, `urllc`, `mmtc`, or `default`
- `latency_ms`: Round-trip latency in milliseconds
- `reliability_pct`: Probability of successful delivery (e.g., `99.995`)
- `throughput_mbps`: Expected throughput in megabits per second
- `priority`: Integer priority bucket aligned with 5G QoS classes

## Usage for Thesis Work

### Running Experiments

```bash
# Generate synthetic QoS dataset
python scripts/data_generation/synthetic_generator.py \
  --records 10000 \
  --profile balanced \
  --output output/qos_data.csv \
  --seed 42

# Run ML vs A3 comparison
./scripts/run_comparison.sh 10

# Generate visualization assets
python scripts/generate_presentation_assets.py
```

### Key Thesis Claims

1. **ML reduces ping-pong handovers by 70-85%** compared to traditional A3 rules
2. **ML handles multi-antenna edge cases significantly better** than A3 rules
3. **ML maintains higher QoS compliance rates** for URLLC, eMBB, and mMTC services
4. **ML achieves better load balancing** across antennas
5. **System demonstrates graceful fallback** to A3 rules when ML is uncertain
6. **Auto-activation of ML** occurs when 3+ antennas exist, handling complexity automatically

### Demonstration Points for Defense

1. **Show ML auto-activation**: Start with 2 antennas (A3 mode), add 3rd antenna (ML mode activates)
2. **Show ping-pong prevention**: Run A3 mode vs ML mode and show suppression metrics
3. **Show QoS compliance**: Send URLLC request vs eMBB request, demonstrate different thresholds
4. **Show metrics dashboards**: Grafana showing real-time handover decisions
5. **Show graceful fallback**: Trigger low-confidence prediction, observe fallback to A3

### Monitoring and Metrics

The system provides comprehensive monitoring through Prometheus:

```promql
# Ping-pong prevention metrics
ml_pingpong_suppressions_total

# Handover interval metrics
ml_handover_interval_seconds

# ML vs A3 handover decisions
nef_handover_decisions_total{outcome="applied"}

# ML fallbacks (graceful degradation)
nef_handover_fallback_total

# QoS compliance
nef_handover_compliance_total

# Prediction confidence
ml_prediction_confidence_avg

# Model performance
ml_prediction_latency_seconds
```

This project represents a production-ready implementation suitable for thesis defense, academic publications, and further research extension.