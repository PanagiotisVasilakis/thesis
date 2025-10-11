# 5G Network Optimization Thesis - Project Context

## Project Overview

This is an enterprise-grade research project focused on optimizing 5G handover decisions using a 3GPP-compliant Network Exposure Function (NEF) emulator and a machine learning service. The system follows a microservices architecture where:

- **NEF Emulator**: Manages network events, implements 3GPP A3 handover rules, and tracks UE mobility patterns
- **ML Service**: Predicts the best antenna based on UE mobility patterns using advanced machine learning models
- **Monitoring Stack**: Includes Prometheus and Grafana for metrics collection and visualization

The project aims to improve handover decisions in 5G networks through both rule-based approaches (A3 events) and sophisticated machine learning-driven predictions.

## Detailed Architecture

### Core System Components

1. **Network State Manager** (`services/nef-emulator/backend/app/app/network/state_manager.py`)
   - **Purpose**: Centralized management of UEs, antennas, connections, and handover history
   - **Key Features**:
     - Maintains real-time state of all UEs and antennas
     - Stores UE positions, speeds, connected antennas, and trajectory history
     - Calculates RF metrics (RSRP, SINR, RSRQ) for each UE-antenna pair
     - Computes neighbor rankings based on signal strength
     - Tracks antenna loads for load balancing
     - Manages handover history for analytics and ML training
     - Provides feature vectors for ML model input

2. **Handover Engine** (`services/nef-emulator/backend/app/app/handover/engine.py`)
   - **Purpose**: Central decision-making component for handover operations
   - **Key Features**:
     - Supports both ML-based and A3 rule-based handover decisions
     - Automatically switches between ML and rule-based modes based on antenna count
     - Handles confidence thresholding with fallback to A3 rules
     - Manages communication with ML service via HTTP
     - Supports local ML model execution within NEF container
     - Implements thread-safe decision making

3. **A3 Event Rule** (`services/nef-emulator/backend/app/app/handover/a3_rule.py`)
   - **Purpose**: Implements 3GPP-compliant A3 handover rule with hysteresis and time-to-trigger
   - **Key Features**:
     - Configurable hysteresis (in dB) and time-to-trigger (in seconds)
     - Implements proper 3GPP TR 38.901 Event A3 logic
     - Maintains timing state for time-to-trigger enforcement
     - Thread-safe implementation suitable for concurrent operations

4. **ML Service Core** (`services/ml-service/ml_service/app/`)
   - **Purpose**: Advanced machine learning service for antenna selection
   - **Key Features**:
     - REST API with authentication and rate limiting
     - Multiple model support (LightGBM, LSTM, Ensemble, Online Learning)
     - Feature engineering with configurable transforms
     - Hyperparameter tuning capabilities
     - Model persistence and versioning
     - Real-time prediction with async support
     - Feedback collection and model retraining
     - Prometheus metrics and monitoring

5. **Mobility Models** (`services/nef-emulator/backend/app/app/mobility_models/`)
   - **Purpose**: Implements various 3GPP-compliant mobility models for simulating UE movement
   - **Available Models**:
     - **LinearMobilityModel**: Straight-line movement between two points (TR 38.901 §7.6.3.2)
     - **LShapedMobilityModel**: L-shaped path with 90-degree turn (TR 38.901 §7.6.3.2)
     - **RandomWaypointModel**: Random destination movement with pauses (TR 38.901 §7.6.3.3)
     - **ManhattanGridModel**: Movement along grid streets with probabilistic turns (TR 38.901 §7.6.3.4)
     - **UrbanGridModel**: Flexible urban grid movement with configurable turn probabilities
     - **RandomDirectionalModel**: Continuous movement with random direction changes
     - **ReferencePointGroupModel**: Group mobility with center and offset patterns (TR 38.901 §7.6.3.5)

6. **Feature Engineering System** (`services/ml-service/ml_service/app/features/`)
   - **Purpose**: Advanced feature extraction and transformation pipeline
   - **Key Features**:
     - Configurable features via YAML configuration
     - Built-in transforms (float, int, math.sqrt, etc.)
     - Custom transform registration capability
     - Feature caching for performance optimization
     - Range validation for feature values

### 3GPP Standards Compliance

The system implements key 3GPP standards:

1. **TR 38.901**: 3D channel model implementation with:
   - Multiple mobility models aligned with section 7.6
   - Proper kinematic equations for UE movement
   - Accurate RSRP, SINR, and RSRQ calculations

2. **A3 Event Rule**: Section 5.2.4.3 of 3GPP TS 36.331
   - Hysteresis parameter (A3_OFFSET) implementation
   - Time-to-trigger (TTT) enforcement
   - Proper neighbor cell evaluation logic

3. **NEF (Network Exposure Function)**: 3GPP TS 29.591
   - Northbound APIs for network event exposure
   - Proper API structure and authentication
   - Event subscription and notification mechanisms

### ML Model Architecture

The ML service supports multiple advanced model types:

1. **LightGBMSelector** (`services/ml-service/ml_service/app/models/lightgbm_selector.py`)
   - **Purpose**: Gradient boosting model for antenna selection
   - **Features**:
     - Configurable hyperparameters (n_estimators, max_depth, num_leaves, learning_rate)
     - Stratified train/validation split with early stopping
     - Feature importance tracking
     - Hyperparameter tuning with RandomizedSearchCV

2. **LSTMSelector** (`services/ml-service/ml_service/app/models/lstm_selector.py`)
   - **Purpose**: Deep learning model for sequential pattern recognition
   - **Features**:
     - Recurrent neural network architecture
     - Sequential pattern recognition for mobility prediction
     - Configurable units and epochs
     - TensorFlow/Keras integration

3. **EnsembleSelector** (`services/ml-service/ml_service/app/models/ensemble_selector.py`)
   - **Purpose**: Combines multiple models for improved accuracy
   - **Features**:
     - Aggregates predictions from multiple models
     - Robust to individual model failures
     - Weighted voting mechanism
     - Supports both LightGBM and LSTM models

4. **OnlineHandoverModel** (`services/ml-service/ml_service/app/models/online_handover_model.py`)
   - **Purpose**: Incremental learning model for real-time adaptation
   - **Features**:
     - SGD-based incremental updates
     - Drift detection for model retraining
     - Feedback-driven learning
     - Real-time model updates

### Advanced ML Capabilities

1. **Hyperparameter Tuning System** (`services/ml-service/ml_service/app/utils/tuning.py`)
   - **Purpose**: Automated optimization of model parameters
   - **Features**:
     - RandomizedSearchCV for LightGBM optimization
     - Configurable parameter distributions
     - Cross-validation with configurable folds
     - Performance metrics tracking

2. **Feature Configuration** (`services/ml-service/ml_service/app/config/features.yaml`)
   - **Purpose**: Flexible feature engineering pipeline
   - **Features**:
     - 23+ configurable features including:
       - Geographic coordinates (latitude, longitude, altitude)
       - Movement metrics (speed, velocity, acceleration)
       - Direction vectors (direction_x, direction_y)
       - RF metrics (RSRP, SINR, RSRQ for all neighbors)
       - Mobility patterns (heading_change_rate, path_curvature)
       - Network metrics (cell_load, handover_count)
       - Signal characteristics (signal_trend, std deviations)

3. **Model Management System** (`services/ml-service/ml_service/app/initialization/model_init.py`)
   - **Purpose**: Thread-safe model lifecycle management
   - **Features**:
     - Hot-swapping of model versions
     - Background initialization with placeholder models
     - Thread-safe operations with locking
     - Model versioning and discovery
     - Feedback buffer for drift detection
     - Automatic retraining triggers

4. **Data Drift Monitoring** (`services/ml-service/ml_service/app/monitoring/metrics.py`)
   - **Purpose**: Real-time monitoring of model performance and data distribution changes
   - **Features**:
     - Rolling window analysis for feature distributions
     - Configurable drift thresholds per feature
     - Automated alerts for significant changes
     - Memory-efficient sampling with bounds
     - Integration with Prometheus metrics

### Monitoring and Observability

1. **Prometheus Metrics** (`services/ml-service/ml_service/app/monitoring/metrics.py`)
   - **Prediction Metrics**:
     - `ml_prediction_requests_total` - request count by status
     - `ml_prediction_latency_seconds` - latency histogram
     - `ml_antenna_predictions_total` - selection count by antenna
     - `ml_prediction_confidence_avg` - confidence tracking
   - **Training Metrics**:
     - `ml_model_training_duration_seconds` - training time histogram
     - `ml_model_training_samples` - sample count tracking
     - `ml_model_training_accuracy` - accuracy tracking
     - `ml_feature_importance` - importance scores
   - **System Metrics**:
     - `ml_data_drift_score` - data distribution changes
     - `ml_prediction_error_rate` - error rate tracking
     - `ml_cpu_usage_percent` - system resource usage
     - `ml_memory_usage_bytes` - memory consumption

2. **Resource Management** (`services/ml-service/ml_service/app/utils/resource_manager.py`)
   - **Purpose**: Efficient resource allocation and cleanup
   - **Features**:
     - Automatic resource registration and tracking
     - Cleanup method invocation on deregistration
     - Memory and compute resource monitoring
     - Component lifecycle management

### Communication Protocols

1. **NEF-ML Service Interface**:
   - **Protocol**: HTTP/HTTPS with JSON payloads
   - **Endpoints**:
     - `/api/v1/ml/handover` - Trigger handover decision
     - `/api/v1/ml/state/{ue_id}` - Get feature vector
     - `/api/predict` (ML service) - Antenna prediction requests
   - **Data Format**: Standardized JSON with UE state and RF metrics
   - **Authentication**: Optional JWT-based authentication

2. **Northbound NEF APIs** (under `/nef` path):
   - **Monitoring Events API** (`/3gpp-monitoring-event/v1`)
   - **QoS Session API** (`/3gpp-as-session-with-qos/v1`)

## Repository Structure

```
/home/pvs/thesis/
├── 5g-network-optimization/          # Main project code and configuration
│   ├── deployment/                   # Kubernetes manifests  
│   ├── leftover_docks/               # Documentation
│   ├── monitoring/                   # Prometheus and Grafana config
│   ├── output/                       # Generated visualizations
│   ├── services/                     # Service source code
│   │   ├── ml-service/               # ML service implementation
│   │   │   ├── ml_service/           # Core ML service package
│   │   │   │   ├── app/              # Main application components
│   │   │   │   │   ├── api/          # API routes and endpoints
│   │   │   │   │   ├── auth/         # Authentication mechanisms
│   │   │   │   │   ├── clients/      # NEF client implementations
│   │   │   │   │   ├── config/       # Configuration files
│   │   │   │   │   ├── core/         # Core utilities
│   │   │   │   │   ├── data/         # Data handling utilities
│   │   │   │   │   ├── features/     # Feature engineering
│   │   │   │   │   ├── initialization/ # Model initialization
│   │   │   │   │   ├── models/       # ML model implementations
│   │   │   │   │   ├── monitoring/   # Prometheus metrics
│   │   │   │   │   ├── scripts/      # Utility scripts
│   │   │   │   │   ├── security/     # Security implementations
│   │   │   │   │   ├── services/     # Service implementations
│   │   │   │   │   ├── state/        # State management
│   │   │   │   │   ├── utils/        # Utility functions
│   │   │   │   │   ├── visualization/ # Visualization components
│   │   │   └── nef-emulator/         # NEF emulator implementation
│   │   │       ├── backend/          # FastAPI backend
│   │   │       │   ├── app/          # Main application components
│   │   │       │   │   ├── api/      # API routes
│   │   │       │   │   ├── core/     # Core utilities
│   │   │       │   │   ├── handover/ # Handover logic
│   │   │       │   │   ├── mobility_models/ # Mobility implementations
│   │   │       │   │   ├── network/   # Network state management
│   │   │       │   │   ├── monitoring/ # Metrics
│   │   │       │   │   ├── schemas/   # Data schemas
│   │   │       │   │   └── ...       # Other components
│   └── docker-compose.yml            # Docker orchestration
├── docs/                            # Documentation files
├── mlops/                           # MLOps related files
├── output/                          # Generated plots and visualizations
├── presentation_assets/             # Pre-rendered graphs for reports
├── scripts/                         # Utility scripts
├── tests/                           # Test files
├── requirements.txt                 # Python dependencies
├── README.md                        # Main project documentation
└── pytest.ini                       # Pytest configuration
```

## Technology Stack

- **Backend Frameworks**: FastAPI (NEF emulator), Flask (ML service)
- **Machine Learning**: LightGBM, TensorFlow/Keras, scikit-learn
- **Deep Learning**: LSTM neural networks for pattern recognition
- **Containerization**: Docker, Docker Compose
- **Monitoring**: Prometheus, Grafana
- **Languages**: Python
- **Testing**: Pytest, coverage tools
- **Performance**: Async operations for high throughput
- **Security**: JWT authentication, rate limiting, thread-safe operations

## Environment Variables

Key configuration options:

- `ML_HANDOVER_ENABLED`: Enable ML-driven handovers (true/false)
- `ML_SERVICE_URL`: URL of the ML service
- `A3_HYSTERESIS_DB`: Hysteresis value for A3 event rule (default: 2.0)
- `A3_TTT_S`: Time-to-trigger for A3 event rule (default: 0.0)
- `NEF_API_URL`: Base URL of the NEF emulator
- `ML_LOCAL`: Install ML service in NEF emulator container (0/1)
- `LIGHTGBM_TUNE`: Enable hyperparameter tuning for LightGBM (0/1)
- `LOG_LEVEL`: Logging verbosity level (DEBUG/INFO/WARNING/ERROR)
- `LOG_FILE`: Optional path for rotating log file
- `FEATURE_CONFIG_PATH`: Path to custom feature configuration
- `MODEL_PATH`: Path for ML model persistence
- `MODEL_TYPE`: Type of ML model to use (lightgbm/lstm/ensemble/online)

## Building and Running

### Prerequisites

1. Install Python dependencies:

```bash
pip install -r requirements.txt
# or use helper script
scripts/install_deps.sh --skip-if-present
```

### Running Locally

```bash
# Start all services with Docker Compose
docker-compose -f 5g-network-optimization/docker-compose.yml up --build
```

### Running in Different Modes

```bash
# Simple A3 Mode (Rule-based)
ML_HANDOVER_ENABLED=0 docker-compose -f 5g-network-optimization/docker-compose.yml up --build

# ML Mode
ML_HANDOVER_ENABLED=1 docker-compose -f 5g-network-optimization/docker-compose.yml up --build

# Single Container Mode (ML service inside NEF emulator)
ML_LOCAL=1 docker-compose -f 5g-network-optimization/docker-compose.yml up --build

# ML with Hyperparameter Tuning
LIGHTGBM_TUNE=1 docker-compose -f 5g-network-optimization/docker-compose.yml up --build
```

## Testing

### Quick Test Setup

```bash
./scripts/setup_tests.sh
```

### Running Tests

```bash
pytest
# or run with coverage
./scripts/run_tests.sh
```

### Integration Tests

```bash
ML_HANDOVER_ENABLED=1 docker-compose -f 5g-network-optimization/docker-compose.yml up --build
pytest 5g-network-optimization/services/nef-emulator/tests/integration \
       5g-network-optimization/services/ml-service/tests/integration
```

## Key Features

1. **Multiple Mobility Models**: Implements several 3GPP-compliant mobility models including Linear, L-shaped, Random Waypoint, Random Directional, Manhattan Grid, Urban Grid, and Reference Point Group mobility.

2. **A3 Handover Rule**: Implements the 3GPP A3 event rule for rule-based handover decisions.

3. **Advanced ML-Based Handover**: Uses sophisticated machine learning models (LightGBM, LSTM, Ensemble, Online Learning) to predict optimal antenna selection based on UE mobility patterns.

4. **Altitude Input Support**: The antenna selector includes altitude as a feature for more accurate predictions, especially useful for multi-story buildings or drone scenarios.

5. **Feature Configuration**: Customizable feature transforms loaded from YAML configuration files with validation.

6. **Monitoring & Visualization**: Built-in Prometheus metrics and Grafana dashboards for performance monitoring.

7. **Hyperparameter Tuning**: Automated optimization of ML model parameters for improved performance.

8. **Model Versioning**: Support for multiple model versions with hot-swapping capability.

9. **Data Drift Detection**: Real-time monitoring of feature distribution changes.

10. **Online Learning**: Incremental model updates based on feedback.

## API Endpoints

### NEF Emulator (port 8080)

- `POST /api/v1/ml/handover?ue_id=u1` - Trigger a handover decision
- `GET /api/v1/ml/state/{ue_id}` - Get ML feature vector for UE
- `GET /metrics` - Prometheus metrics
- `POST /nef/3gpp-monitoring-event/v1/...` - Northbound NEF APIs

### ML Service (port 5050)

- `POST /api/predict` - Get antenna prediction
- `POST /api/train` - Train model with new data
- `GET /api/nef-status` - Check NEF emulator connectivity
- `GET /metrics` - Prometheus metrics
- `POST /api/feedback` - Send handover outcome feedback
- `POST /api/collect-data` - Collect training data from NEF

## Development Conventions

- Python code follows standard conventions with type hints
- Dependencies managed via requirements.txt
- Tests written with pytest framework
- Logging configured via environment variables
- Docker-based deployment for consistency
- Code formatting with black and linting with flake8
- Thread-safe implementations for concurrent operations
- Comprehensive error handling and resource management

## Output and Visualization

Generated outputs are organized in subfolders of `output/`:

- `output/coverage/` – Antenna coverage maps
- `output/trajectory/` – UE movement trajectories  
- `output/mobility/` – Mobility model examples
- `presentation_assets/` – Pre-rendered graphs for reports

## MLOps and ML Pipeline

The system includes comprehensive ML pipeline components:

- Training data collection mechanisms with synthetic data generation
- Multiple ML model types with hyperparameter tuning support
- Model persistence using joblib with metadata tracking
- Feature engineering with configurable transforms and validation
- Online learning and model retraining based on feedback
- Drift detection and automated retraining triggers
- Model versioning and hot-swapping capabilities
- Real-time metrics and monitoring
