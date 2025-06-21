# 5G Network Optimization Using NEF Emulator and Machine Learning: Progress Summary

## Project Overview

We've been developing a 3GPP-compliant 5G network optimization system that uses machine learning to dynamically select optimal antennas based on UE mobility patterns. This enterprise-grade system follows a microservices architecture, integrating the open-source NEF emulator with custom machine learning components.

## Architecture Evolution

### Initial Architecture (Day 1)

We began with a conceptual architecture consisting of these core components:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                       5G Network Optimization System                     │
│                                                                         │
│  ┌─────────────┐      ┌─────────────┐      ┌─────────────────────────┐  │
│  │             │      │             │      │                         │  │
│  │    NEF      │<─────┤     ML      │<─────┤  Visualization Portal   │  │
│  │  Emulator   │─────>│   Service   │─────>│                         │  │
│  │             │      │             │      │                         │  │
│  └─────────────┘      └─────────────┘      └─────────────────────────┘  │
│         │                    │                        │                 │
│         ▼                    ▼                        ▼                 │
│  ┌─────────────┐      ┌─────────────┐      ┌─────────────────────────┐  │
│  │             │      │             │      │                         │  │
│  │  Network    │      │   Model     │      │     Monitoring Stack    │  │
│  │ Simulation  │      │  Storage    │      │  (Prometheus+Grafana)   │  │
│  │             │      │             │      │                         │  │
│  └─────────────┘      └─────────────┘      └─────────────────────────┘  │
│                                                                         │
│                      ┌─────────────────────────────┐                    │
│                      │                             │                    │
│                      │     Local Database Stack    │                    │
│                      │     (PostgreSQL + Redis)    │                    │
│                      │                             │                    │
│                      └─────────────────────────────┘                    │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### Refined Architecture (Day 2-3)

After analyzing the NEF emulator's codebase and considering integration challenges, we refined the architecture to:

1. Keep the NEF emulator mostly unchanged
2. Implement 3GPP mobility models as a standalone module
3. Create adapters to convert between our models and NEF formats
4. Build a separate ML service with well-defined interfaces

```
┌─────────────────────────────────────────────────────────────────────────┐
│                   5G Network Optimization System (Refined)               │
│                                                                         │
│  ┌─────────────────────┐            ┌──────────────────────────────┐    │
│  │                     │            │                              │    │
│  │   NEF Emulator      │<───────────┤    ML Service                │    │
│  │   (Original)        │            │    - Antenna Selection       │    │
│  │                     │────────────┤    - Performance Metrics     │    │
│  │                     │            │    - Decision Engine         │    │
│  └─────────────────────┘            └──────────────────────────────┘    │
│           │                                        │                    │
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

## Implementation Progress

### Day 1: Project Planning & Architecture Design

1. **Analysis of Requirements**
   * Reviewed thesis objective: 5G network optimization using ML
   * Analyzed NEF emulator capabilities and structure
   * Defined key system components and interactions
2. **Architecture Design**
   * Created initial system architecture diagram
   * Defined component interactions and data flows
   * Established enterprise-grade standards to follow (3GPP compliance)
3. **Technical Stack Selection**
   * Selected Docker for containerization
   * Chose ML frameworks (scikit-learn initially, with expansion to RL)
   * Selected monitoring tools (Prometheus, Grafana)

### Day 2: Initial Setup & NEF Emulator Analysis

1. **Project Repository Setup**
   * Created project directory structure
   * Set up git repository
   * Created initial configuration files
2. **NEF Emulator Analysis**
   * Cloned the medianetlab/NEF_emulator repository
   * Analyzed codebase structure and interfaces
   * Identified key integration points:
     * UE movement system in `ue_movement.py`
     * Cell/antenna management in `Cell.py`
     * RF models in `5g_nr_radio.py`
3. **Integration Strategy Development**
   * Determined challenges with direct NEF modification
   * Developed alternative integration approach using adapters

### Day 3: 3GPP Mobility Models Implementation

1. **Mobility Models Development**
   * Created base `MobilityModel` class
   * Implemented `LinearMobilityModel` following 3GPP TR 38.901
   * Implemented `LShapedMobilityModel` for 90-degree turn scenarios
2. **Testing Infrastructure**
   * Created test scripts for mobility models
   * Implemented visualization capabilities
   * Verified model output against expected behavior
3. **NEF Integration Approach**
   * Developed `nef_adapter.py` for format conversion
   * Created workflow for generating NEF-compatible path points
   * Generated test paths in JSON format

### Day 4: ML Service Foundation

1. **ML Service Structure**
   * Created service directory structure
   * Set up Flask application framework
   * Defined API endpoints for ML functionality
2. **Antenna Selection Model**
   * Implemented `AntennaSelector` class
   * Created feature extraction from UE data
   * Implemented training and prediction functions
3. **Integration Strategy**
   * Developed approach for NEF-ML communication
   * Created data pipelines for model training
   * Set up interfaces for decision feedback

## Current Status

### Completed Components

1. **3GPP Mobility Models**
   * Base mobility model framework
   * Linear mobility implementation
   * L-shaped mobility implementation
   * NEF adapter for format conversion
2. **ML Service Foundation**
   * Service structure and basic API
   * Feature engineering framework
   * Initial antenna selection model
   * NEF integration interface

### Current Project Structure

```
5g-network-optimization/
├── services/
│   ├── nef-emulator/           # Forked NEF emulator
│   │   ├── mobility_models/    # 3GPP mobility models
│   │   │   ├── __init__.py
│   │   │   ├── models.py       # Mobility model implementations
│   │   │   └── nef_adapter.py  # NEF format conversion
│   │   ├── tests/              # Test scripts
│   │   │   ├── mobility_test.py
│   │   │   └── nef_adapter_test.py
│   │   └── backend/            # Original NEF emulator code
│   │
│   └── ml-service/             # ML optimization service
│       ├── app/
│       │   ├── __init__.py
│       │   ├── api/            # API endpoints
│       │   └── models/         # ML models
│       │       └── antenna_selector.py
│       ├── requirements.txt
│       ├── app.py              # Main application
│       └── Dockerfile
│
├── monitoring/                 # Monitoring configuration
│   ├── prometheus/
│   └── grafana/
│
├── docker-compose.yml          # Deployment configuration
└── README.md                   # Project documentation
```

## Environment Variables

The NEF emulator's `NetworkStateManager` can be configured via the following
variables. These may be set in your shell environment or through
`docker-compose`:

| Variable | Description | Default |
|----------|-------------|---------|
| `SIMPLE_MODE` | Apply the A3 handover rule before executing any decision (`true`/`false`) | `false` |
| `ML_HANDOVER_ENABLED` | Enable ML-driven handovers. When `false` only the A3 rule is used | `false` |
| `A3_HYSTERESIS_DB` | Hysteresis value in dB for the A3 event rule | `2.0` |
| `A3_TTT_S` | Time-to-trigger in seconds for the A3 event rule | `0.0` |
| `NEF_API_URL` | Base URL of the NEF emulator used by the ML service | `http://localhost:8080` |

## Running the System

Both the NEF emulator and the ML service are started via `docker-compose`. The
handover logic can run in a simple rule-based mode (3GPP Event A3) or use the ML
model. Control this behavior with the environment variables described above.

### Simple A3 Mode

Disable ML-based decisions and rely solely on the A3 hysteresis/time-to-trigger
rule:

```bash
ML_HANDOVER_ENABLED=0 SIMPLE_MODE=true docker-compose up --build
```

### ML Mode

Use the trained ML model for antenna selection:

```bash
ML_HANDOVER_ENABLED=1 docker-compose up --build
```

### Example API Calls

Trigger a handover (rule-based or ML depending on the mode):

```bash
curl -X POST "http://localhost:8080/api/v1/ml/handover?ue_id=u1"
```

Request a direct prediction from the ML service:

```bash
curl -X POST http://localhost:5050/api/predict \
     -H 'Content-Type: application/json' \
     -d '{"ue_id":"u1","latitude":100,"longitude":50,"connected_to":"antenna_1",\
"rf_metrics":{"antenna_1":{"rsrp":-80,"sinr":15},"antenna_2":{"rsrp":-90,"sinr":10}}}'
```

### Extended Integration Tests

To run the full integration suite for both services:

```bash
pip install -r requirements.txt
pytest services/nef-emulator/tests/integration \
       services/ml-service/tests/integration
```


## Technical Deep Dive: Key Implementations

### 1. 3GPP-Compliant Mobility Models

The core of our mobility models follows the 3GPP TR 38.901 standard, which defines mobility patterns for network testing:

```python
class LinearMobilityModel(MobilityModel):
    """Linear mobility model (3GPP TR 38.901 Section 7.6.3.2)"""
  
    def __init__(self, ue_id, start_position, end_position, speed, start_time=None):
        super().__init__(ue_id, start_time)
        self.start_position = start_position  # (x, y, z) in meters
        self.end_position = end_position  # (x, y, z) in meters
        self.speed = speed  # meters per second
        self.current_position = start_position
  
    def generate_trajectory(self, duration_seconds, time_step=1.0):
        """Generate trajectory points for linear movement"""
        # Calculate direction vector and generate points
        # Implementation details...
```

The models generate detailed trajectory data with position, speed, direction, and timestamps, which are then converted to NEF-compatible formats.

### 2. NEF Integration Approach

Rather than modifying the NEF emulator directly, we developed an adapter that converts our mobility model output to NEF-compatible formats:

```python
def generate_nef_path_points(model_type, **params):
    """Generate path points in NEF emulator format"""
    # Create appropriate mobility model
    # Generate trajectory
    # Convert to NEF format
    nef_points = []
    for point in trajectory:
        nef_point = {
            "latitude": point['position'][0],
            "longitude": point['position'][1],
            "description": f"Point {i} for {ue_id}"
        }
        nef_points.append(nef_point)
  
    return nef_points
```

This approach allows us to use the NEF emulator without modifications while still implementing 3GPP-compliant mobility patterns.

### 3. ML Service Design

The ML service implements a feature extraction and prediction pipeline:

```python
def extract_features(self, data):
    """Extract features from UE data."""
    features = {}
  
    # Location features
    features['latitude'] = data.get('latitude', 0)
    features['longitude'] = data.get('longitude', 0)
  
    # Movement features
    features['speed'] = data.get('speed', 0)
    # Direction vector processing...
  
    # Signal features
    # RSRP, SINR processing...
  
    return features
```

The service is designed to be extensible, starting with a basic RandomForest classifier that can be replaced with more sophisticated algorithms (reinforcement learning) in later phases.

# Understanding the NEF Emulator Structure

Looking at the `nef_structure.txt` file reveals a comprehensive FastAPI-based backend with a well-organized structure. Let me break down the key components that are relevant to our integration:

## Key Components & Integration Points

1. **UE Movement System**
   * `backend/app/app/api/api_v1/endpoints/ue_movement.py` - This is a critical integration point for our mobility models
   * `backend/app/app/models/UE.py` - Contains the data model for UEs
   * `backend/app/app/schemas/UE.py` - Defines the API schemas for UE data
2. **Network Models**
   * `backend/app/app/models/Cell.py` and `gNB.py` - These define the network elements
   * `backend/app/app/tools/5g_nr_radio.py` - Contains radio models we'll need to enhance with our RF calculations
3. **Monitoring Events**
   * `backend/app/app/api/api_v1/endpoints/monitoringevent.py` - Handles network events that we'll extend for ML integration
   * `backend/app/app/tools/monitoring_callbacks.py` - Likely implements callback mechanisms for events
4. **QoS Management**
   * `backend/app/app/api/api_v1/endpoints/qosInformation.py` and `qosMonitoring.py` - We'll need to integrate with these for QoS-aware optimizations
