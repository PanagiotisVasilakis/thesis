# QoS Architecture

## Purpose & Scope

This page is the canonical reference for how Quality of Service (QoS) data flows through the 5G Network Optimization stack today. It is grounded in the current FastAPI NEF emulator and Flask ML service implementation, and it supersedes older design notes under `docs/qos/`. The sections below describe request and response flows, admission-control levers, configuration surfaces, observability, and verification artifacts so new contributors can reason about QoS behaviour without reading every module first.

## Flow Overview

1. **NEF assembles UE context.** `NetworkStateManager` enriches position, RF metrics, and antenna loads for the UE that triggered a mobility event.
2. **QoS-aware prediction request.** `HandoverEngine` packages that state (plus cached QoS requirements) and calls the ML service’s `/api/predict-with-qos` endpoint. The payload is validated by `PredictionRequestWithQoS` before routing into the model pipeline.

```47:56:5g-network-optimization/services/ml-service/ml_service/app/schemas.py
class PredictionRequestWithQoS(PredictionRequest):
    """Extended prediction request with QoS requirements."""

    model_config = ConfigDict(extra="forbid")
    # Allowed values: 'urllc', 'embb', 'mmtc', 'default'
    service_type: str = "default"
    qos_requirements: Optional[Dict[str, float]] = None
    edge_service_requirements: Optional[Dict[str, Any]] = None
    service_priority: int = Field(5, ge=1, le=10)
```

3. **ML service derives compliance.** The shared API helper extracts features, derives default QoS thresholds, and computes a conservative compliance verdict from model confidence.

```23:58:5g-network-optimization/services/ml-service/ml_service/app/api_lib.py
def predict(ue_data: dict, model: Any | None = None):
    """Return prediction for ``ue_data`` using the provided model."""
    mdl = model or load_model()
    features = mdl.extract_features(ue_data)
    result = mdl.predict(features)
    # If the request carries QoS context, compute a lightweight
    # qos_compliance flag.
    if "qos_compliance" not in result:
        try:
            qos = qos_from_request(ue_data)
            priority = int(qos.get("service_priority", 5))
            required_conf = 0.5 + (min(max(priority, 1), 10) - 1) * (0.45 / 9)
            confidence = float(result.get("confidence", 0.0))
            compliance = {
                "service_priority_ok": confidence >= required_conf,
                "required_confidence": required_conf,
                "observed_confidence": confidence,
                "details": {
                    "service_type": qos.get("service_type"),
                    "service_priority": qos.get("service_priority"),
                    "latency_requirement_ms": qos.get("latency_requirement_ms"),
                    "throughput_requirement_mbps": qos.get("throughput_requirement_mbps"),
                    "reliability_pct": qos.get("reliability_pct"),
                },
            }
            result["qos_compliance"] = compliance
        except Exception:
            result.setdefault("qos_compliance", {"service_priority_ok": True, "details": {}})
    return result, features
```

4. **NEF applies or falls back.** If the ML response passes `qos_compliance`, the NEF applies the suggested antenna. Otherwise it increments fallback counters and evaluates the deterministic A3 rule.

```191:238:5g-network-optimization/services/nef-emulator/backend/app/app/handover/engine.py
    def decide_and_apply(self, ue_id: str):
        """Select the best antenna and apply the handover."""
        self._update_mode()
        if self.use_ml:
            result = self._select_ml(ue_id)
            if result is None:
                target = None
            else:
                target = result.get("antenna_id")
                confidence = result.get("confidence") or 0.0
                qos_comp = result.get("qos_compliance")
                if isinstance(qos_comp, dict):
                    ok = bool(qos_comp.get("service_priority_ok", True))
                    metrics.HANDOVER_COMPLIANCE.labels(outcome="ok" if ok else "failed").inc()
                    if not ok:
                        metrics.HANDOVER_FALLBACKS.inc()
                        target = self._select_rule(ue_id) or self.state_mgr.get_feature_vector(ue_id).get("connected_to")
                elif confidence < self.confidence_threshold:
                    metrics.HANDOVER_FALLBACKS.inc()
                    target = self._select_rule(ue_id)
        else:
            target = self._select_rule(ue_id)
        if not target:
            return None
        return self.state_mgr.apply_handover_decision(ue_id, target)
```

## Admission Control & Prioritization

### Rate limiting and request quotas

`Flask-Limiter` gates every REST handler except health checks. The default (`RATELIMIT_DEFAULT`) is 100 requests per minute and per-route overrides can be set through `RATELIMIT_*` environment variables. Rate limiting is skipped when `app.testing` is `True`.

```24:49:5g-network-optimization/services/ml-service/ml_service/app/rate_limiter.py
limiter = Limiter(key_func=_identity_key, headers_enabled=True)

def init_app(app):
    """Initialize limiter with configuration-aware defaults."""
    app.config.setdefault("RATELIMIT_DEFAULT", "100 per minute")
    app.config.setdefault("RATELIMIT_ENABLED", True)
    app.config.setdefault("RATELIMIT_STORAGE_URI", "memory://")
    app.config.setdefault("RATE_LIMITS", {})
    limiter.enabled = bool(app.config.get("RATELIMIT_ENABLED", True)) and not app.testing
    limiter.init_app(app)
    return limiter

def limit_for(endpoint_key: str) -> Callable[[], str]:
    def _resolver() -> str:
        per_endpoint = current_app.config.get("RATE_LIMITS", {})
        return per_endpoint.get(endpoint_key) or current_app.config.get("RATELIMIT_DEFAULT", "100 per minute")
    return _resolver
```

### Asynchronous model queue

The prediction and training paths share an `AsyncModelManager` with a bounded priority queue (`ASYNC_MODEL_QUEUE_SIZE`, default 1000) and a worker pool controlled by `ASYNC_MODEL_WORKERS`. Each operation is tracked, timed, and cancelled if it exceeds `MODEL_PREDICTION_TIMEOUT` or `MODEL_TRAINING_TIMEOUT`.

```92:158:5g-network-optimization/services/ml-service/ml_service/app/models/async_model_operations.py
class ModelOperationQueue:
    """Thread-safe queue for model operations with prioritization."""

    def __init__(self, max_size: int = 1000):
        self.max_size = max_size
        self._queue = queue.PriorityQueue(maxsize=max_size)
        self._operations: Dict[str, ModelOperation] = {}
        # ... existing code ...

    def submit(self, operation: ModelOperation, priority: int = 5) -> bool:
        if len(self._operations) >= self.max_size:
            logger.warning("Operation queue full, rejecting operation %s", operation.operation_id)
            return False
        # ... existing code ...

class AsyncModelManager:
    def __init__(self, max_workers: int = None, max_queue_size: int = 1000, operation_timeout: float = 300.0):
        if max_workers is None:
            max_workers = env_constants.ASYNC_MODEL_WORKERS
        self.operation_queue = ModelOperationQueue(max_size=max_queue_size)
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="AsyncModel")
        # ... existing code ...
```

### Circuit breakers and retries

Outbound calls from the ML service to the NEF emulator are shielded by synchronous and asynchronous circuit breakers. Login failures trip after three consecutive errors; API calls open the circuit after five failures, enforcing exponential backoff and observability via `/api/v1/circuit-breakers`.

```71:166:5g-network-optimization/services/ml-service/ml_service/app/clients/nef_client.py
        self._login_breaker = CircuitBreaker(
            failure_threshold=3,
            recovery_timeout=30.0,
            expected_exception=requests.exceptions.RequestException,
            name=f"NEF-Login-{base_url}"
        )
        self._api_breaker = CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=60.0,
            expected_exception=requests.exceptions.RequestException,
            name=f"NEF-API-{base_url}"
        )
        circuit_registry.register(self._login_breaker)
        circuit_registry.register(self._api_breaker)

    def login(self) -> bool:
        try:
            return self._login_breaker.call(_do_login)
        except CircuitBreakerError as e:
            raise NEFClientError(f"NEF login service unavailable: {e}") from e
```

### Confidence-gated fallbacks

QoS gating is intentionally conservative. If `qos_compliance.service_priority_ok` is false or the response lacks a compliance block and falls below `ML_CONFIDENCE_THRESHOLD`, the NEF increments `nef_handover_fallback_total` and retries the deterministic A3 rule before returning control to the caller.

## Configurations & Feature Flags

| Scope | Key | Default | Description |
| --- | --- | --- | --- |
| NEF | `ML_HANDOVER_ENABLED` | unset → auto | Forces ML decisions on or off. When unset, ML activates once at least three antennas are registered. |
| NEF | `ML_CONFIDENCE_THRESHOLD` | `0.5` | Minimum confidence used when `qos_compliance` is unavailable. |
| NEF | `ML_SERVICE_URL` | `http://ml-service:5050` (Docker) | Target for `/api/predict-with-qos`. |
| NEF | `A3_HYSTERESIS_DB`, `A3_TTT_S` | `2.0`, `0.0` | Parameters passed to the A3 fallback rule. |
| NEF | `RESOURCE_BLOCKS` | `50` | Influences RSRQ calculations in `NetworkStateManager`. |
| NEF | `NOISE_FLOOR_DBM` | `-100` | Default noise floor for SINR estimation. |
| ML | `NEF_API_URL` | `http://localhost:8080` | Base URL for data collection and health checks. Compose overrides to `http://nef-emulator:80`. |
| ML | `MODEL_TYPE` | `lightgbm` | Controls which selector class `ModelManager` instantiates. |
| ML | `AUTO_RETRAIN`, `RETRAIN_THRESHOLD` | `True`, `0.1` | Enable drift-triggered retraining and set the drift threshold. |
| ML | `ASYNC_MODEL_WORKERS`, `ASYNC_MODEL_QUEUE_SIZE` | `4`, `1000` | Worker pool size and backlog limit for async inference/training. |
| ML | `MODEL_PREDICTION_TIMEOUT`, `MODEL_TRAINING_TIMEOUT` | `30s`, `600s` | Upper bounds enforced by `AsyncModelWorker`. |
| ML | `RATELIMIT_*` keys | see defaults above | Per-endpoint quotas (`predict`, `train`, `feedback`, etc.). |
| ML | `FEATURE_CONFIG_PATH` | `config/features.yaml` | Overrides the feature configuration loaded by `AntennaSelector`. |
| ML | `FEATURE_IMPORTANCE_PATH` | `/tmp/feature_importance.json` | Destination for persisted feature importance dumps. |
| Data collection | `COLLECTION_DURATION`, `COLLECTION_INTERVAL` | `60s`, `1s` | Defaults consumed by `NEFDataCollector.collect_training_data`. |
| Data collection | `UE_TRACKING_MAX_UES`, `UE_TRACKING_TTL_HOURS` | `10000`, `24` | Size and TTL of memory-managed UE caches. |

## Failure Modes & Safeguards

- **QoS rejection and automatic fallback.** If the ML confidence misses the required threshold for the advertised `service_priority`, the NEF logs `HANDOVER_COMPLIANCE{outcome="failed"}`, increments `HANDOVER_FALLBACKS`, and applies the A3 rule before returning the decision.
- **Circuit breaker observability.** The `/api/v1/circuit-breakers/status` endpoint exposes breaker health so operators can understand whether repeated 5xx responses are due to upstream instability or ML service throttling.
- **Model failure fallback.** `AntennaSelector.predict` wraps inference in `safe_execute`. If LightGBM throws or the scaler is unfitted, the method returns the configured fallback antenna and logs a warning instead of crashing the API.
- **Strict schema validation.** Pydantic models (`PredictionRequestWithQoS`, `CollectDataRequest`, etc.) reject invalid QoS payloads before they reach the model layer. Asynchronous collectors normalise and validate QoS dictionaries to prevent poisoning the feature store.

## Metrics & Dashboards

### ML Service Prometheus Metrics

| Metric | Type | Labels | Purpose |
| --- | --- | --- | --- |
| `ml_prediction_requests_total` | Counter | `status` | Success vs error counts for API requests. |
| `ml_prediction_latency_seconds` | Histogram | – | Latency distribution for `/api/predict*` calls. |
| `ml_antenna_predictions_total` | Counter | `antenna_id` | Distribution of selected antennas. |
| `ml_prediction_confidence_avg` | Gauge | `antenna_id` | Latest confidence value per antenna. |
| `ml_model_training_duration_seconds` | Histogram | – | Training runtimes. |
| `ml_model_training_samples` | Gauge | – | Samples processed during the latest training run. |
| `ml_model_training_accuracy` | Gauge | – | Reported validation accuracy. |
| `ml_feature_importance` | Gauge | `feature` | Latest feature importance snapshot. |
| `ml_data_drift_score` | Gauge | – | Average absolute drift across tracked features. |
| `ml_prediction_error_rate` | Gauge | – | Error fraction over the most recent metrics window. |
| `ml_cpu_usage_percent`, `ml_memory_usage_bytes` | Gauge | – | Process resource usage. |

Dashboards under `monitoring/grafana/dashboards/ml_service.json` surface these metrics by default.

### Data Drift Monitoring

The `DataDriftMonitor` class (in `ml_service/app/monitoring/metrics.py`) tracks feature distribution changes over rolling windows. It validates incoming feature values against `ml_service/app/config/features.yaml` which specifies numeric min/max bounds or allowed categories. During prediction, the monitor logs alerts when the absolute difference between current and baseline feature means exceeds configured thresholds. Configure per-feature thresholds when creating the monitor:

```python
monitor = DataDriftMonitor(window_size=100, thresholds={"speed": 5.0, "sinr_current": 2.0})
```

### Feature Transformation Registry

The ML service uses a central registry to map feature names to transformation functions. During feature extraction, registered transforms ensure consistent data types and preprocessing. Built-in transforms include `identity`, `float`, `int`, and `bool`. Custom transforms can be registered via `app/config/features.yaml` using fully qualified Python paths (e.g., `math.sqrt`) or programmatically via `register_feature_transform()`.

### Mobility Metrics

The `MobilityMetricTracker` class (in `ml_service/app/utils/mobility_metrics.py`) incrementally computes heading change rate and path curvature for coordinate streams. Each update runs in O(1) time by relying only on the previous segment rather than recomputing from full position history.

### NEF Emulator Metrics

| Metric | Type | Labels | Purpose |
| --- | --- | --- | --- |
| `nef_handover_decisions_total` | Counter | `outcome` | Applied vs skipped handovers. |
| `nef_handover_fallback_total` | Counter | – | Count of ML fallbacks to deterministic logic. |
| `nef_handover_compliance_total` | Counter | `outcome` | QoS compliance pass/fail. |
| `nef_request_duration_seconds` | Histogram | `method`, `endpoint` | NEF API latency including ML round-trips. |

## Feature Store Integration

The UE metrics feature view in Feast (`mlops/feature_store/feature_repo/schema.py`) includes QoS columns alongside mobility signals:

| Column | Type | Description |
| --- | --- | --- |
| `latency_ms` | Float32 | Observed round-trip latency in milliseconds |
| `throughput_mbps` | Float32 | Effective user throughput measured in Mbps |
| `packet_loss_rate` | Float32 | Packet loss percentage for the UE link |

These fields flow to both the offline Parquet source and the online SQLite store. The canonical offline file is expected at `mlops/feast_repo/data/training_data.parquet`. Generate source data using the synthetic QoS generator (see `docs/qos/synthetic_qos_dataset.md`), then apply with:

```bash
cd mlops/feast_repo
PYTHONPATH=../.. feast apply
```

Range enforcement for QoS metrics is handled by `validate_feature_ranges` pipeline hooks using bounds declared in `ml_service/app/config/features.yaml`.

## Validation Architecture

QoS validation spans multiple layers to ensure data quality from ingestion through prediction:

- **`mlops/data_pipeline/nef_collector.py`** – `QoSRequirements.from_payload` normalizes NEF payloads, coerces numeric thresholds, and raises `QoSValidationError` for malformed records before storage.
- **`ml_service/app/data/nef_collector.py`** – `_normalize_qos_payload` mirrors offline validation logic during live data collection.
- **`ml_service/app/utils/common_validators.py`** – `NumericValidator`, `StringValidator`, `GeospatialValidator`, and composite helpers (`UEDataValidator`, `DataCollectionValidator`) provide reusable validation primitives.
- **`ml_service/app/config/feature_specs.py`** – `_load_specs` parses `features.yaml` for per-feature min/max bounds and categorical allow-lists; `validate_feature_ranges` enforces these specs before model access.
- **Pydantic schemas** – `CollectDataRequest`, `PredictionRequestWithQoS` enforce field types and value ranges at the API boundary before payloads reach collectors or models.

## Tests & Examples

- **Model-side QoS tests:** `ml_service/ml_service/tests/test_qos_classifier.py`, `test_qos_core.py`, `test_qos_encoding.py`, and `test_qos_schema.py` validate scoring, compliance, encoding, and schema behaviour.
- **Feature-range enforcement:** `tests/mlops/test_qos_feature_ranges.py` asserts that Feast schemas and `validate_feature_ranges` accept in-range QoS metrics and reject out-of-range values.
- **NEF QoS APIs:** `services/nef-emulator/tests/api/test_qos_information.py` and `test_qos_notification.py` exercise the QoS discovery and monitoring endpoints without requiring a live database.

### Replaying a QoS Prediction

1. Start the stack (`docker compose up --build`).
2. Authenticate against the ML service:

   ```bash
   TOKEN=$(curl -s -X POST http://localhost:5050/api/login \
       -H 'Content-Type: application/json' \
       -d '{"username":"admin","password":"admin"}' | jq -r .access_token)
   ```

3. Submit a QoS-aware prediction (trimmed example):

   ```bash
   curl -X POST http://localhost:5050/api/predict-with-qos \
       -H "Authorization: Bearer $TOKEN" \
       -H 'Content-Type: application/json' \
       -d '{
             "ue_id": "demo-ue",
             "latitude": 38.0,
             "longitude": 23.7,
             "connected_to": "antenna_1",
             "rf_metrics": {"antenna_1": {"rsrp": -78, "sinr": 15}},
             "service_type": "embb",
             "service_priority": 7,
             "latency_requirement_ms": 40.0,
             "throughput_requirement_mbps": 120.0
          }'
   ```

Example QoS monitoring payloads for end-to-end tests live under `services/nef-emulator/docs/test_plan/AsSessionWithQoS/`.

## Known Gaps & Open Questions

- `qos_compliance` currently judges priority fulfilment purely from model confidence; it does not yet incorporate live latency or throughput deltas from NEF callbacks.
- Mutual TLS, OAuth, nonce validation, and `/api/v2/*` contracts referenced in older docs are **not** implemented. Any deployment requiring those guarantees must design and implement them explicitly.
- The control plane does not currently export structured alerts when circuit breakers open or when fallbacks exceed a threshold—operators should monitor the provided Prometheus metrics for now.
- The feedback endpoint stores samples in memory and hands them to `ModelManager` but no automated retraining job is wired to consume them in production. Formalising that loop remains future work.
- Grafana dashboards focus on the ML service; an equivalent dashboard for NEF QoS decisions and fallback rates would help spot regressions earlier.

Please update this page whenever QoS behaviour, configuration, or tests change.


