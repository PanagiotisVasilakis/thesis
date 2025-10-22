# NEF ↔ ML Service Integration Blueprint

## 1. Current NEF References in the Thesis Repository
The existing documentation highlights three key areas where the Network Exposure Function (NEF) is described:

1. **Project Summary (`docs/THESIS_SUMMARY.md`)** – Introduces the NEF emulator as the mobility event source that exposes REST endpoints and a deterministic fallback path based on the A3 rule when ML predictions are unavailable.
2. **QoS Solution Architecture (`docs/qos/qos_solution_architecture.md`)** – Positions the NEF within the QoS assurance flow, describing the UE mobility simulator and placeholders for richer NEF–ML payload definitions.
3. **MLOps Pipeline (`mlops/README.md`)** – Mentions the CI/CD workflow that builds and deploys Docker images for both the NEF emulator and the ML service, ensuring aligned release management.

These references motivate a deeper definition of the runtime contract between the NEF emulator and the ML inference API so that handover decisions can be automated, audited and reproduced.

## 2. Interaction Overview
The NEF emulator acts as the producer of mobility events and radio measurements, while the ML service scores the likelihood of improved QoS by switching cells. The NEF orchestrates the interaction through three phases:

1. **Feature Assembly** – Collect UE telemetry, enrich it with cached context and build the payload defined below.
2. **ML Invocation** – Send the payload to the ML service using the transport and security profile described in §3.
3. **Decision Application** – Apply the ML recommendation or fall back to deterministic logic based on the decision logic in §4.

## 3. Request / Response Extensions
### 3.1 Transport and Security
- **Protocol**: HTTPS over HTTP/2 to support concurrent mobility event scoring with lower latency head-of-line blocking.
- **Authentication**: Mutual TLS (mTLS) between NEF and ML service pods using service mesh identities (e.g., SPIFFE/SPIRE). Certificates are rotated by the platform CA every 24 hours.
- **Authorisation**: OAuth 2.0 client credentials flow layered on top of mTLS. The NEF obtains a short-lived access token (≤5 minutes) from the platform IAM service and includes it in the `Authorization: Bearer <token>` header.
- **Integrity & Replay Protection**: Each request carries an `X-Request-Nonce` header. The ML service validates uniqueness within a 10-minute sliding window, persisting hashes in Redis.
- **Timeouts & Retries**: Client timeout is 250 ms with two retries using exponential backoff (100 ms, 200 ms). Idempotency is preserved via the `interaction_id` field.

### 3.2 Prediction Request Payload (`POST /api/v2/predict`)
```json
{
  "interaction_id": "uuid",
  "timestamp": "2024-03-01T12:03:12.512Z",
  "ue_id": "string",
  "serving_cell": {
    "cell_id": "string",
    "earfcn": 6200,
    "rsrp": -91.2,
    "rsrq": -8.5,
    "sinr": 12.1
  },
  "candidate_cells": [
    {
      "cell_id": "string",
      "rsrp": -86.4,
      "rsrq": -7.1,
      "sinr": 15.8,
      "backhaul_load": 0.42
    }
  ],
  "mobility": {
    "latitude": 48.8566,
    "longitude": 2.3522,
    "speed_mps": 14.3,
    "heading_deg": 185.0,
    "altitude_m": 27.5,
    "heading_change_rate": 2.1,
    "path_curvature": 0.03
  },
  "radio_context": {
    "band": "n78",
    "duplex_mode": "TDD",
    "ue_capabilities": ["EN-DC", "256QAM"],
    "slice_id": "embb-gold",
    "qos_class_identifier": 9
  },
  "service_requirements": {
    "target_latency_ms": 20,
    "min_throughput_mbps": 75,
    "reliability_target": 0.999
  }
}
```

### 3.3 Prediction Response Payload
```json
{
  "interaction_id": "uuid",
  "decision": {
    "action": "HANDOVER",  // HANDOVER | STAY | DEGRADE | FAILOVER
    "target_cell_id": "string",
    "confidence": 0.87,
    "expected_latency_ms": 18,
    "expected_throughput_mbps": 92,
    "rationale": [
      {
        "feature": "candidate_cells[0].sinr",
        "contribution": 0.32
      },
      {
        "feature": "mobility.heading_change_rate",
        "contribution": -0.05
      }
    ]
  },
  "ttl_seconds": 5,
  "fallback_hint": {
    "trigger": "LOW_CONFIDENCE",
    "recommended_action": "A3_RULE",
    "metadata": {
      "confidence_threshold": 0.8,
      "reason": "Confidence below SLA"
    }
  },
  "audit": {
    "model_version": "2024.03.01-rc1",
    "feature_store_commit": "a13f2e7",
    "processing_latency_ms": 37,
    "received_nonce": "abc123"
  }
}
```

- **`decision.action`** enumerates possible outcomes. `DEGRADE` asks the NEF to adjust QoS parameters without handover; `FAILOVER` signals deterministic logic should take over immediately.
- **`fallback_hint`** gives the NEF sufficient context to decide whether to retry, fall back to heuristics or escalate to NOC tooling.
- **`audit`** metadata ensures end-to-end traceability and ties back to MLflow and Feast artefacts.

### 3.4 Training Feedback Endpoint (`POST /api/v2/feedback`)
- Used by the NEF to stream ground-truth outcomes (successful or failed handovers) back to the ML service.
- Payload extends the request schema with `observed_metrics` (e.g., `actual_latency_ms`, `packet_loss`, `handover_success`), enabling continual learning pipelines.
- Requires exactly-once semantics enforced by `interaction_id` and nonce replay checks.

## 4. Decision & Fallback Logic
The NEF applies the following decision tree after receiving the response:

1. **Transport/Protocol Failure** – If the request exhausts retries or returns ≥500, execute deterministic A3 handover logic and flag the interaction for offline analysis.
2. **Security Failure** – If token validation or nonce verification fails, quarantine the event, rotate credentials and fall back to deterministic logic until health checks recover.
3. **Low Confidence** – If `decision.confidence < 0.8` or `fallback_hint.trigger == "LOW_CONFIDENCE"`, run the A3 rule but log the model output for retraining.
4. **TTL Breach** – If the NEF cannot apply the decision within `ttl_seconds`, discard the prediction, emit a `handover.fallbacks` event annotated with `reason="ttl_expired"`, and rescore with fresh telemetry.
5. **Service Degradation** – When circuit-breaker counters in the ML service exceed `CB_FAILURE_THRESHOLD` it returns synthetic `503` responses. The NEF interprets consecutive 5xx responses as a health incident, forces `ML_HANDOVER_ENABLED=0`, and routes all traffic through the A3 rule until the breaker recovers.
6. **Successful Recommendation** – Apply the recommended action (`HANDOVER`, `STAY`, `DEGRADE`) and push an acknowledgement to the observability topic.

## 5. Sequence Placement & Integration Touchpoints
1. **Telemetry Ingress** – UE events enter the NEF mobility pipeline. The NEF publishes metrics to Prometheus before invoking the ML service.
2. **Feature Engineering Hook** – NEF assembles the payload, attaching cached slice/QoS metadata from the policy function.
3. **Secure Invocation** – NEF sends the HTTPS request with mTLS and bearer token. Istio/Linkerd sidecars enforce policy and record traces.
4. **ML Decision Processing** – ML service validates nonce, verifies token scopes and scores the request. It stores decisions and explanations in MLflow.
5. **Response Handling** – NEF applies the decision, honours TTL, and emits Kafka events (`topic: handover.decisions`) for auditing.
6. **Fallback Triggering** – On any of the failures listed in §4, NEF triggers deterministic A3 logic and publishes an alert on `topic: handover.fallbacks`.
7. **Feedback Loop** – Successful or failed outcomes are posted to `/api/v2/feedback` within 60 seconds. A background worker batches feedback into the training data lake.

## 6. Implementation Milestones
To operationalise this blueprint, adopt the following milestones:

1. **Contract Validation** – Update FastAPI and Flask schemas to match the payload definitions. Add Pydantic/Marshmallow models and schema tests.
2. **Security Enablement** – Provision mTLS certificates and integrate OAuth client credentials flow. Extend integration tests to cover nonce replay protection.
3. **Observability & Feedback** – Implement structured logging, Kafka topics, and the feedback ingestion endpoint. Ensure MLflow tracking includes the `interaction_id`.

Each milestone can be delivered independently while maintaining backward compatibility by supporting both `/api/predict` (v1) and `/api/v2/predict` during migration.
