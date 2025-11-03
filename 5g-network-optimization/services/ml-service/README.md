# ML Service

Flask-based microservice that predicts handover targets for user equipment (UE) and delivers training/monitoring tooling for the NEF emulator. Every behaviour described below is derived from the current codebase (`ml_service/app`).

## Highlights

- Flask application factory (`ml_service.app.create_app`) with background model initialisation, structured logging, JWT auth, and Prometheus metrics.
- Rich model manager supporting LightGBM, LSTM, Ensemble, and Online models selectable via `MODEL_TYPE`.
- **Ping-pong prevention** in ML predictions to prevent rapid handover oscillations (critical for thesis demonstration).
- JWT-protected REST API with rate limiting, QoS-aware `/api/predict-with-qos`, async prediction/training helpers, NEF integration, and feedback ingestion for drift handling.
- Dedicated `/metrics` endpoint guarded by pluggable credentials (basic, API key, or JWT) plus helper endpoints to mint metrics tokens.
- Visualization blueprint for coverage maps and trajectories saved under `output/`.
- Extensive configuration surface via environment variables, all funnelled through `ml_service.app.config.constants`.

## Application lifecycle

`create_app()` performs the following steps:

1. Loads defaults (`NEF_API_URL`, `MODEL_PATH`, auth secrets, JWT expiry, etc.) and applies any overrides passed via the optional `config` mapping.
2. Ensures the model directory exists and kicks off `ModelManager.initialize(..., background=True)` unless `app.testing` is set. This spawns a monitored thread that either loads an existing model or trains one using synthetic data; the placeholder instance returned immediately is replaced once training completes.
3. Registers two blueprints: `/api` (core REST endpoints) and `/api/visualization` (image generation helpers). It also wires rate limiting (`Flask-Limiter` default: 100 requests/min) and global error handlers.
4. Mounts Prometheus middleware (`MetricsMiddleware`) and starts a `MetricsCollector` background thread to publish latency, drift, and resource metrics.
5. Exposes authenticated `/metrics`, `/metrics/auth/token`, and `/metrics/auth/stats` endpoints. Metrics authentication is skipped in testing but enforced in every other mode.
6. Adds request/response logging with correlation IDs, making every log line traceable.

`app.py` configures logging via `services/logging_config.py` and runs the Flask server on port `5050`, optionally wrapping it in TLS when `SSL_CERTFILE` and `SSL_KEYFILE` are present.

## Directory guide

- `app/api/routes.py` – synchronous and async REST endpoints (prediction, training, NEF connectivity, feedback, data collection, model management).
- `app/api/visualization.py` – coverage-map and trajectory PNG generators backed by Matplotlib helpers.
- `app/initialization/model_init.py` – `ModelManager`, synthetic training bootstrap, model version discovery (`MODEL_VERSION = 1.0.0`).
- `app/monitoring/metrics.py` – custom Prometheus registry, middleware, drift monitor, and background collector.
- `app/auth` – JWT issuance/verification (`create_access_token`, `verify_token`) and metrics authentication strategies.
- `collect_training_data.py` – CLI utility to harvest NEF samples or delegate to `/api/collect-data`.

## Running locally

```bash
python -m venv .venv
. .venv/Scripts/activate  # or source .venv/bin/activate on Linux/macOS
pip install -r ../../requirements.txt
export AUTH_USERNAME=admin AUTH_PASSWORD=admin JWT_SECRET=change-me
python app.py
```

The service listens on `http://localhost:5050` by default. Set `SSL_CERTFILE`/`SSL_KEYFILE` to serve HTTPS.

### Docker

```bash
docker build -t ml-service .
docker run -p 5050:5050 \
     -e AUTH_USERNAME=admin -e AUTH_PASSWORD=admin -e JWT_SECRET=change-me \
     -e NEF_API_URL=http://localhost:8080 \
     ml-service
```

The top-level `docker-compose.yml` in this repository starts the NEF emulator, ML service, and monitoring stack end-to-end.

## API overview

All endpoints live under `/api` and return JSON. Rate limiting and JWT authentication apply to every route except where noted.

| Endpoint | Method | Auth? | Purpose |
|----------|--------|-------|---------|
| `/api/health` | GET | No | Liveness probe. |
| `/api/model-health` | GET | No | Reports `ModelManager.is_ready()` and the latest metadata (version, timestamps, metrics). |
| `/api/login` | POST | No | Issues a JWT given `AUTH_USERNAME`/`AUTH_PASSWORD`. Body validated via `LoginRequest` Pydantic model. |
| `/api/predict` | POST | Yes | Synchronous prediction. Uses `PredictionRequest`, calls `predict()` helper, records metrics & drift data. |
| `/api/predict-with-qos` | POST | Yes | QoS-aware prediction that returns a `qos_compliance` verdict alongside the antenna suggestion. |
| `/api/predict-async` | POST | Yes | Runs `model.predict_async` if the underlying selector supports it. |
| `/api/train` | POST | Yes | Batch training. Accepts list of `TrainingSample` payloads (50 MB cap) and persists via `ModelManager.save_active_model`. |
| `/api/train-async` | POST | Yes | Awaitable variant using `model.train_async`. |
| `/api/collect-data` | POST | Yes | Asynchronously fetches samples from the NEF emulator using `NEFDataCollector.collect_training_data`. Optional credentials/duration/interval. |
| `/api/nef-status` | GET | Yes | Health-checks the configured NEF URL through `NEFClient.get_status()`, returning version headers when reachable. |
| `/api/models` | GET | Yes | Lists discovered `antenna_selector_v*.joblib` versions. |
| `/api/models/<version>` | POST/PUT | Yes | Switches active model; validates via `model_version_validator` and raises structured errors on missing files/permissions. |
| `/api/feedback` | POST | Yes | Accepts a list of `FeedbackSample` entries, feeding them into `ModelManager.feed_feedback` for drift-triggered retraining. |

### Visualization endpoints

- `GET /api/visualization/coverage-map` – generates a coverage heatmap. Will auto-train with synthetic data if the model is uninitialised.
- `POST /api/visualization/trajectory` – consumes an array of UE snapshots and emits `trajectory.png` in the configured output directory.

Example usage:

```bash
# Acquire a JWT token
TOKEN=$(curl -s -X POST http://localhost:5050/api/login \
     -H "Content-Type: application/json" \
     -d '{"username":"admin","password":"admin"}' | jq -r .access_token)

# Run a prediction
curl -X POST http://localhost:5050/api/predict \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
                    "ue_id":"ue-42",
                    "latitude":38.0,
                    "longitude":23.7,
                    "connected_to":"antenna_1",
                    "rf_metrics": {
                         "antenna_1": {"rsrp": -78, "sinr": 15, "rsrq": -9}
                    }
               }'
```

## Metrics & authentication

- `/metrics` returns Prometheus-formatted stats generated by `generate_latest(metrics.REGISTRY)`.
- Requests must supply Basic credentials (`METRICS_AUTH_USERNAME`/`METRICS_AUTH_PASSWORD`), a bearer API key (`METRICS_API_KEY`), or a valid JWT minted with `/metrics/auth/token`.
- `/metrics/auth/token` issues a JWT signed with `JWT_SECRET` and honours the expiry configured by `METRICS_JWT_EXPIRY_SECONDS`.
- `/metrics/auth/stats` exposes failed-attempt counters and lockout information maintained by `MetricsAuthenticator`.

## Environment variables

### Core settings

| Variable | Default | Description |
|----------|---------|-------------|
| `AUTH_USERNAME` / `AUTH_PASSWORD` | *(unset)* | Required for `/api/login`. If omitted, authentication is disabled and a warning is logged (only recommended for local experiments). |
| `JWT_SECRET` | random per boot | HMAC key for JWTs. Provide a stable value for multi-instance deployments. |
| `NEF_API_URL` | `http://localhost:8080` | Base URL consumed by NEF client calls and the data collector. |
| `MODEL_PATH` | `ml_service/app/models/antenna_selector_v1.0.0.joblib` | Storage location for the active model and metadata. Parent folders are created automatically. |
| `MODEL_TYPE` | `lightgbm` | Chooses selector class (`lightgbm`, `lstm`, `ensemble`, `online`). Metadata can override this. |
| `NEIGHBOR_COUNT` | `3` | Passed to selector constructors to size neighbour-aware features. |
| `LIGHTGBM_TUNE` | `0` | When `1`, runs randomized LightGBM tuning during bootstrap. Tweaked via `LIGHTGBM_TUNE_N_ITER` and `LIGHTGBM_TUNE_CV`. |
| `PORT` / `HOST` | `5050` / `0.0.0.0` | Gunicorn/Flask bind address and port when launched via `app.py`. |
| `RATE_LIMIT_PER_MINUTE` | `100` | Default `Flask-Limiter` quota. |

### Metrics auth options

| Variable | Default | Notes |
|----------|---------|-------|
| `METRICS_AUTH_ENABLED` | `true` | Flag consumed by helper scripts; the service itself always enforces authentication outside of testing. |
| `METRICS_AUTH_USERNAME` | `metrics` | Basic auth username. Leave blank to disable basic auth. |
| `METRICS_AUTH_PASSWORD` | *(unset)* | Basic auth password. |
| `METRICS_API_KEY` | *(unset)* | Bearer API key alternative. |
| `METRICS_JWT_EXPIRY_SECONDS` | `3600` | Token TTL for `/metrics/auth/token`. |

### Logging and HTTPS

- `LOG_LEVEL`, `LOG_FILE` influence `configure_logging`.
- `SSL_CERTFILE`, `SSL_KEYFILE` enable TLS when set.

Refer to `ml_service/app/config/constants.py` for the complete list, including cache sizing, drift monitoring, async worker limits, and input sanitisation toggles.

## Collecting and training data

`collect_training_data.py` orchestrates NEF sampling and optional training.

```bash
python collect_training_data.py \
     --url http://localhost:8080 \
     --username admin --password admin \
     --duration 300 --interval 1 --train
```

- Uses `NEFDataCollector` to login, validate UE movement, and gather JSON samples under `ml_service/app/data/collected_data/`.
- When `--ml-service-url` is supplied, the script delegates to `/api/collect-data` on a running ML service, automatically authenticating via `/api/login`.
- If Feast helpers are available (`feature_store_utils`), samples are ingested before training.

## Testing & quality

```bash
pytest tests
```

The top-level scripts `scripts/setup_tests.sh` and `scripts/run_tests.sh` install dependencies, configure `PYTHONPATH`, and run the suite with coverage. Unit tests rely on tmp paths for generated artefacts, so the repository stays clean after execution.

## Troubleshooting

- **Model never becomes ready**: check logs for thread monitor entries (`model_background_init`). A failure reverts to the last good model path and surfaces in `/api/model-health` metadata.
- **401 on `/metrics`**: ensure at least one metrics credential is configured. Use `/metrics/auth/token` to mint a short-lived JWT.
- **`/api/collect-data` returns zero samples**: verify the NEF emulator has UEs in motion via its `/api/v1/movement` endpoints before invoking collection.
- **Rate limit exceeded**: increase `RATE_LIMIT_PER_MINUTE` or tune specific routes by extending `Flask-Limiter` in `rate_limiter.py`.

Everything above reflects the current code; adjust this README whenever API routes, defaults, or background services change.
