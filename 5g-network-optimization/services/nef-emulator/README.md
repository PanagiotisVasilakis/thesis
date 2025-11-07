# NEF Emulator

FastAPI-based Network Exposure Function emulator with a web UI, CAPIF integration hooks, and optional ML-driven handover logic.

## Why this service matters

- **End-to-end NEF sandbox** – REST API for gNBs, cells, UEs, mobility patterns, and 3GPP northbound endpoints (monitoring events, QoS sessions).
- **Operational UI** – Dashboard, map, import/export, and CRUD flows served directly from the backend (`/ui`, `/static`).
- **Handover experimentation** – Toggleable ML handover pipeline that cooperates with the ML microservice or a local model and falls back to the 3GPP A3 rule.
- **Observability & automation** – Prometheus metrics (`/metrics`), CAPIF onboarding helpers, seeded demo database scripts, request timing middleware, and Make targets for common workflows.

---

## System architecture

### FastAPI surfaces

- `app.main:app` exposes internal REST APIs under `settings.API_V1_STR` (default `/api/v1`). Router groups live in `app/api/api_v1/endpoints` and include login, users, network inventory (gNBs, Cells, UEs, Paths), movement control, QoS information, mobility patterns, and ML handover utilities.
- A dedicated `nef_app` sub-application is mounted at `/nef`. It wraps the 3GPP-facing endpoints (`/3gpp-monitoring-event/v1`, `/3gpp-as-session-with-qos/v1`) used by CAPIF-integrated NetApps.
- Static dashboards are delivered with `Jinja2Templates` and `StaticFiles`. Pages include `/login`, `/dashboard`, `/map`, `/export`, `/import`, and error fallbacks. See `docs/UI.md` for deep dives into the frontend structure.

### Data stores and background jobs

- **PostgreSQL** holds structured entities (users, UEs, cells, paths). SQLAlchemy sessions are created in `app/db/session.py` and wired via FastAPI dependencies.
- **MongoDB** stores monitoring subscriptions, notifications, and UE movement snapshots used by the UI polling layer (`crud_mongo`).
- `app/initial_data.py` seeds baseline database state and (optionally) onboards the NEF to CAPIF using `evolved5g`'s `CAPIFProviderConnector`.
- The `backend_pre_start.py` retry loop ensures Postgres availability before Uvicorn boots; `start-reload.sh` launches Uvicorn with autoreload (and optional `prestart.sh` hook when provided).

### ML handover pipeline

- `HandoverEngine` evaluates UE state from `NetworkStateManager`. When `use_ml` is enabled it posts feature vectors to `${ML_SERVICE_URL}/api/predict` and expects `{predicted_antenna, confidence}` in return.
- Confidence thresholds (`ML_CONFIDENCE_THRESHOLD`) decide whether to accept ML outputs or fall back to the deterministic `A3EventRule`. Lack of sufficient antennas also automatically disables ML (minimum count defaults to three).
- Key metrics exported via `app/monitoring/metrics.py`:
  - `nef_handover_decisions_total{outcome}` – applied vs skipped handovers
  - `nef_handover_fallback_total` – ML predictions discarded due to low confidence
  - `nef_request_duration_seconds{method,endpoint}` – histogram of request latencies (populated by the middleware that also adds the `X-Process-Time` header)

---

## Local development

### Prerequisites

- Docker Engine ≥ 23 and Docker Compose V2
- `make` (GNU make – install via `build-essential` on Debian/Ubuntu) if you want to reuse provided targets
- `jq` for the optional dataset seeding script (`app/db/init_simple.sh`)

### Create your `.env`

The stack relies on a `.env` file in `services/nef-emulator/`. If `env-file-for-local.dev` is available in your working copy you can copy it with `make prepare-dev-env`; otherwise craft one manually.

Start from the essentials:

```dotenv
# Core service URLs
DOMAIN=localhost
NEF_HOST=nef.local
NGINX_HTTP=8090
NGINX_HTTPS=4443

# Backend FastAPI settings
SERVER_NAME=nef-emulator
SERVER_HOST=https://localhost
PROJECT_NAME=NEF Emulator
BACKEND_CORS_ORIGINS=["http://localhost:3000"]

# Auth bootstrap
FIRST_SUPERUSER=admin@my-email.com
FIRST_SUPERUSER_PASSWORD=pass
USERS_OPEN_REGISTRATION=false
USE_PUBLIC_KEY_VERIFICATION=false

# PostgreSQL
POSTGRES_SERVER=db
POSTGRES_DB=app
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres

# MongoDB
MONGO_CLIENT=mongodb://mongo_nef:27017
MONGO_USER=root
MONGO_PASSWORD=pass
MONGO_EXPRESS_ENABLE_ADMIN=true

# CAPIF (adjust to your deployment)
CAPIF_HOST=capifcore
CAPIF_HTTP_PORT=8080
CAPIF_HTTPS_PORT=443
EXTERNAL_NET=true

# Observability
LOG_LEVEL=info
LOG_FILE=

# ML integration
ML_SERVICE_URL=http://ml-service:5050
ML_HANDOVER_ENABLED=0
ML_CONFIDENCE_THRESHOLD=0.5
ML_LOCAL=0

# Reverse proxy image tag
DOCKER_IMAGE_BACKEND=nef-emulator-backend
TAG=local
```

Additional tuning knobs are listed in [Configuration reference](#configuration-reference).

### Start the stack

With a `.env` in place you can use either the Make targets or Compose directly:

```powershell
# Build the backend and reverse proxy images
make build

# Start the developer profile (FastAPI + Postgres + Mongo + reverse proxy)
make up

# To run detached:
make upd

# Follow logs
make logs-dev
```

Equivalent Compose commands (from `services/nef-emulator/`):

```powershell
docker compose --profile dev build
docker compose --profile dev up
```

Compose profiles:

- `dev` – backend (FastAPI with reload), Postgres, Mongo, reverse proxy.
- `debug` – adds pgAdmin (`:5050`) and Mongo Express (`:8081`) for live inspection. Use `make debug-up` / `make debug-upd`.

### Access points

| Feature | URL (HTTP) | URL (HTTPS) | Notes |
|---------|------------|-------------|-------|
| Swagger UI (internal APIs) | `http://localhost:${NGINX_HTTP}/docs` | `https://localhost:${NGINX_HTTPS}/docs` | Available on the root app |
| 3GPP northbound Swagger | `http://localhost:${NGINX_HTTP}/nef/docs` | `https://localhost:${NGINX_HTTPS}/nef/docs` | Mounted sub-application |
| Web UI login | `http://localhost:${NGINX_HTTP}/login` | `https://localhost:${NGINX_HTTPS}/login` | Default credentials from env |
| Prometheus metrics | `http://localhost:${NGINX_HTTP}/metrics` | `https://localhost:${NGINX_HTTPS}/metrics` | Scrape with Prometheus or curl |

Self-signed certificates are generated at container start (`nginx/self-signed-crt.sh`). Browsers will prompt for trust on first visit.

### Seed demo data (optional)

Once the stack is running you can load a sample scenario (paths, gNB, cells, UEs) via:

```powershell
make db-init
```

The script logs in using `FIRST_SUPERUSER` credentials and issues REST POSTs. Ensure `jq` is installed locally.

Resetting data:

```powershell
make db-reset    # truncates SQL tables + wipes Mongo database
make db-reinit   # reset + seed again
```

---

## API surface

| Group | Prefix | Description |
|-------|--------|-------------|
| Authentication | `/api/v1/login` | Token issuance for the UI and NetApps |
| Users & admin | `/api/v1/users` | CRUD for users, leverages FastAPI dependencies and SQLAlchemy |
| Network inventory | `/api/v1/gNBs`, `/Cells`, `/UEs`, `/paths` | Manage topology entities backing the UI datatables |
| Mobility & telemetry | `/api/v1/ue_movement`, `/mobility-patterns` | Control UE mobility, fetch trajectories, produce feature vectors |
| QoS utilities | `/api/v1/qosInfo` | Exposes QoS profiles as defined in `config/qosCharacteristics.json` |
| ML handover | `/api/v1/ml/state/{ue_id}`, `/api/v1/ml/handover` | Inspect feature vectors, trigger handover decisions |
| 3GPP APIs | `/nef/3gpp-monitoring-event/v1`, `/nef/3gpp-as-session-with-qos/v1` | CAPIF-exposed monitoring events, QoS session flows with callback registration |

Detailed request/response examples live under `docs/test_plan/`.

### Mobility modelling

Trajectory generation follows the 3GPP TR 38.901 §7.6 patterns and lives in `app/mobility_models/models.py`:

- `LinearMobilityModel` and `LShapedMobilityModel` reproduce the straight-line (§7.6.3.2) and two-segment L-path kinematics with timestamp-aligned sampling.
- `RandomWaypointModel` implements the waypoint-based walk (§7.6.3.3), including pause handling and randomised speed selection between `v_min`/`v_max`.
- `ManhattanGridMobilityModel` and `UrbanGridMobilityModel` cover the orthogonal street-grid cases (§7.6.3.4) with probabilistic turn selection at intersections.
- `RandomDirectionalMobilityModel` supports continuous direction changes with exponential timers, plus boundary reflection via `_handle_boundary_collision`.
- `ReferencePointGroupMobilityModel` layers group offsets on top of any centre model to simulate correlated UE clusters (§7.6.3.5).

All concrete models inherit from `MobilityModel`, which records trajectories and surfaces `get_position_at_time()` for interpolated `(x, y, z)` lookup. The shared `_interpolate_position()` helper performs timestamp-ordered interpolation, ensuring smooth playback for the UI and feature extractors.

### Handover flow example

```powershell
# Inspect the dynamic feature vector for UE 202010000000001
curl -k "https://localhost:${env:NGINX_HTTPS}/api/v1/ml/state/202010000000001" -H "Authorization: Bearer $token"

# Ask the engine to evaluate a handover for the same UE
curl -k -X POST "https://localhost:${env:NGINX_HTTPS}/api/v1/ml/handover?ue_id=202010000000001" -H "Authorization: Bearer $token"
```

Return payloads contain the applied antenna and are mirrored in `NetworkStateManager.handover_history`.

---

## Monitoring & operations

- Prometheus scrape endpoint: `/metrics` (see metric names above).
- Every HTTP response carries `X-Process-Time` exposing server-side latency.
- Reverse proxy logs live in the `nginxdata` volume; FastAPI logs honour `LOG_LEVEL`/`LOG_FILE` settings.
- Use `make logs-dev`, `make logs-debug`, or `docker compose logs -f backend` for streaming logs.

---

## CAPIF integration

The onboard workflow is automated by `app/initial_data.py`, which is executed during container start. To successfully register with CAPIF:

1. **Run CAPIF Core Function** – Follow <https://github.com/EVOLVED-5G/CAPIF_API_Services> and ensure the core services are reachable.
2. **Share Docker network** – Set `EXTERNAL_NET=true` so Compose attaches `services_default` (must already exist – created by CAPIF stack). For cross-host deployments set it to `false` and route traffic manually.
3. **Host entries** – Map `capifcore` in `/etc/hosts` (either to `127.0.0.1` or the CAPIF VM IP).
4. **Start NEF** – `make up` or `make debug-up`. On boot, `capif_service_description()` rewrites `app/core/capif_files/*.json` with the runtime hostnames and ports, then `capif_nef_connector()` registers and publishes services.
5. **Validate** – After a successful run 12 certificate artefacts should exist in `backend/app/app/core/certificates/`. Logs will record onboarding success/failure.

`USE_PUBLIC_KEY_VERIFICATION=true` switches API authentication to CAPIF-issued tokens (public-key validation). When `false`, the local JWT secret secures the endpoints.

---

## Web UI overview

- **Dashboard** – CRUD on gNBs, cells, paths, UEs using datatables and form modals.
- **Map** – Visualizes UE motion (polling loop) and streaming callback notifications.
- **Export / Import** – Round-trip scenarios as JSON files.
- **Authentication** – Tokens stored in `localStorage` (`app_auth`), bootstrap login drives all pages.

Refer to `docs/UI.md` for library details (CoreUI, Leaflet, DataTables, Toastr, CodeMirror) and architectural notes.

---

## Configuration reference

| Variable | Required | Default / Example | Purpose |
|----------|----------|-------------------|---------|
| `DOMAIN` | ✅ | `localhost` | Base domain the reverse proxy advertises |
| `NEF_HOST` | ✅ | `nef.local` | Reverse proxy hostname (used in TLS certs) |
| `NGINX_HTTP` / `NGINX_HTTPS` | ✅ | `8090` / `4443` | Published ports for HTTP/HTTPS |
| `SERVER_NAME` | ✅ | `nef-emulator` | FastAPI title |
| `SERVER_HOST` | ✅ | `https://localhost` | External FastAPI URL for OpenAPI generation |
| `BACKEND_CORS_ORIGINS` | ➖ | `[]` | Allowed origins for CORS |
| `FIRST_SUPERUSER`, `FIRST_SUPERUSER_PASSWORD` | ✅ | `admin@my-email.com`, `pass` | Bootstrap admin credentials |
| `USERS_OPEN_REGISTRATION` | ➖ | `false` | Allow users to self-register |
| `USE_PUBLIC_KEY_VERIFICATION` | ➖ | `false` | Enforce CAPIF certificate validation |
| `POSTGRES_SERVER`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | ✅ | `db`, `app`, `postgres`, `postgres` | SQL connection settings |
| `MONGO_CLIENT` | ✅ | `mongodb://mongo_nef:27017` | Mongo URI for monitoring collections |
| `MONGO_USER`, `MONGO_PASSWORD` | ✅ | `root`, `pass` | Credentials passed to the Mongo container |
| `MONGO_EXPRESS_ENABLE_ADMIN` | ➖ | `true` | Enables admin mode in Mongo Express when using debug profile |
| `CAPIF_HOST`, `CAPIF_HTTP_PORT`, `CAPIF_HTTPS_PORT` | ✅ (when using CAPIF) | `capifcore`, `8080`, `443` | CAPIF API service endpoints |
| `EXTERNAL_NET` | ➖ | `true` | Attach Compose stack to CAPIF docker network |
| `PRODUCTION`, `DOMAIN_NAME`, `NGINX_HOST` | ➖ | – | Adjust CAPIF service descriptors for production deployments |
| `ML_SERVICE_URL` | ➖ | `http://ml-service:5050` | Remote ML microservice base URL |
| `ML_HANDOVER_ENABLED` | ➖ | `0` | Force ML handover on/off (overrides automatic antenna-count heuristic) |
| `ML_LOCAL` | ➖ | `0` | Install and use embedded ML package within the backend image |
| `ML_CONFIDENCE_THRESHOLD` | ➖ | `0.5` | Minimum confidence accepted from ML responses |
| `A3_HYSTERESIS_DB`, `A3_TTT_S` | ➖ | `2.0`, `0.0` | Parameters for the fallback A3 rule |
| `NOISE_FLOOR_DBM`, `RESOURCE_BLOCKS` | ➖ | `-100`, `50` | RF calculations inside `NetworkStateManager` |
| `LOG_LEVEL`, `LOG_FILE` | ➖ | `info`, _blank_ | Structured logging configuration |
| `DOCKER_IMAGE_BACKEND`, `TAG` | ➖ | `nef-emulator-backend`, `local` | Image naming overrides for Compose |
| `INSTALL_DEV`, `INSTALL_JUPYTER` | ➖ | `true` / `false` | Build args used in `Dockerfile.backend` |

---

## Development workflow

### Install dependencies locally

```powershell
cd services/nef-emulator/backend/app
poetry install
```

Run tests:

```powershell
poetry run pytest
```

The test suite exercises configuration loading, database initialisation, and UE API contracts (`tests/api/test_ue_endpoints.py`).

### Helpful Make targets

| Target | Description |
|--------|-------------|
| `make build` | Build backend and nginx images |
| `make up` / `make upd` | Start dev profile (foreground / detached) |
| `make debug-up` | Start debug profile with pgAdmin & Mongo Express |
| `make logs-<service>` | Follow logs (backend / mongo / dev / debug) |
| `make db-init` | Seed demo topology via REST calls |
| `make db-reset` | Truncate Postgres tables & drop Mongo DB |

---

## Troubleshooting

- **`.env` missing variables** – FastAPI will exit if required settings (e.g., `FIRST_SUPERUSER`) are absent. Double-check against the configuration table.
- **CAPIF onboarding fails** – Ensure `capifcore` is reachable from the backend container (`docker compose exec backend ping capifcore`). Inspect `backend/app/app/core/certificates/` for partial artefacts.
- **`make db-init` errors** – Verify the NEF stack is already running and that `jq` is installed on the host. The script expects HTTPS reachable at `${DOMAIN}:${NGINX_HTTPS}` with the reverse proxy container healthy.
- **ML service timeouts** – The backend logs exceptions from `requests.post`. Set `ML_HANDOVER_ENABLED=0` or `ML_CONFIDENCE_THRESHOLD=1` to temporarily force A3-only operations.
- **Self-signed certificate warnings** – Import `nginx/certs/*.crt` into your trust store or use the HTTP port for local iteration.

---

### Further reading

- `docs/UI.md` – Frontend and interaction design notes.
- `docs/antenna_and_path_loss.md` – RF modelling documentation.
- `tests/` – Usage examples that accompany the endpoints.

Happy experimenting with the NEF Emulator!
