# 5G Network Optimization Using NEF Emulator and Machine Learning

## Project Overview
This project aims to optimize 5G handover decisions using a 3GPP-compliant Network Exposure Function (NEF) emulator and a dedicated machine learning service. The system follows a microservices architecture where the NEF emulator manages network events and the ML service predicts the best antenna based on UE mobility patterns.

## System Architecture
```
┌─────────────────────────────────────────────────────────────────────────┐
│                   5G Network Optimization System                        │
│                                                                         │
│  ┌─────────────────────┐            ┌──────────────────────────────┐    │
│  │                     │            │                              │    │
│  │   NEF Emulator      │<───────────┤    ML Service                │    │
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
For detailed setup instructions, see the READMEs in [`services/nef-emulator`](services/nef-emulator/README.md) and [`services/ml-service`](services/ml-service/README.md).

## Environment Variables
The NEF emulator's `NetworkStateManager` supports several configuration options. Set these variables in your shell or through `docker-compose`:

| Variable | Description | Default |
|----------|-------------|---------|
| `SIMPLE_MODE` | Apply the A3 handover rule before executing any decision (`true`/`false`) | `false` |
| `ML_HANDOVER_ENABLED` | Enable ML-driven handovers. When `false` only the A3 rule is used | `false` |
| `A3_HYSTERESIS_DB` | Hysteresis value in dB for the A3 event rule | `2.0` |
| `A3_TTT_S` | Time-to-trigger in seconds for the A3 event rule | `0.0` |
| `NEF_API_URL` | Base URL of the NEF emulator used by the ML service | `http://localhost:8080` |

## Running the System
Both services run via `docker-compose`. Use the environment variables above to switch between rule-based and ML-based modes.

### Simple A3 Mode
```bash
ML_HANDOVER_ENABLED=0 SIMPLE_MODE=true docker-compose up --build
```

### ML Mode
```bash
ML_HANDOVER_ENABLED=1 docker-compose up --build
```

### Example API Calls
Trigger a handover:
```bash
curl -X POST "http://localhost:8080/api/v1/ml/handover?ue_id=u1"
```

Get a direct prediction from the ML service:
```bash
curl -X POST http://localhost:5050/api/predict \
     -H 'Content-Type: application/json' \
     -d '{"ue_id":"u1","latitude":100,"longitude":50,"connected_to":"antenna_1","rf_metrics":{"antenna_1":{"rsrp":-80,"sinr":15},"antenna_2":{"rsrp":-90,"sinr":10}}}'
```

## Testing
First install the dependencies using the repository root `requirements.txt`. Some packages (e.g. `tables`) require system libraries such as `libhdf5-dev` on Ubuntu.
```bash
sudo apt-get update && sudo apt-get install -y libhdf5-dev
pip install -r requirements.txt
```

### Extended Integration Tests
Start the containers and run the full integration suite:
```bash
ML_HANDOVER_ENABLED=1 docker-compose up --build
pip install -r requirements.txt
pytest services/nef-emulator/tests/integration \
       services/ml-service/tests/integration
```
