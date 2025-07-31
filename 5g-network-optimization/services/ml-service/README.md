# ML Service

This Flask-based microservice predicts optimal antenna assignments for user equipment (UE).
It exposes a REST API consumed by the NEF emulator and by the training scripts.

## Application Factory

The entry point for the service is `app/__init__.py` which implements a
Flask application factory named `create_app`. The factory performs the
following tasks:

1. Loads default configuration such as `NEF_API_URL` and the `MODEL_PATH` for
   the persisted model.
2. Creates the model directory and initializes the ML model via
   `app.initialization.model_init.initialize_model`. The service always uses a
   LightGBM model. If no model exists a lightweight synthetic one is trained and
   stored automatically.
3. Registers the REST API blueprint from `app/api` and visualization routes
   from `app/api/visualization`.

```python
from ml_service.app import create_app
app = create_app()
```

Running `python app.py` simply invokes this factory and serves the app.

## API Endpoints

The routes are defined in `app/api/routes.py`. Example calls are shown using
`curl` with the default port `5050`. Most endpoints require a JWT token which
can be obtained from `/api/login` using the credentials configured via
`AUTH_USERNAME` and `AUTH_PASSWORD`.

### `GET /api/health`
Simple health probe.

```bash
curl http://localhost:5050/api/health
```

### `POST /api/login`
Obtain a JWT token. Use the configured username and password.

```bash
curl -X POST http://localhost:5050/api/login \
     -H 'Content-Type: application/json' \
     -d '{"username":"admin","password":"admin"}'
```

### `POST /api/predict`
Submit UE information and receive the recommended antenna.
The request body should contain fields such as `ue_id`, `latitude`, `longitude`,
`connected_to` and an optional `rf_metrics` dictionary.  `rf_metrics` may include
per‑antenna `rsrp`, `sinr` and `rsrq` values if available. Example:

```bash
curl -X POST http://localhost:5050/api/predict \
     -H 'Content-Type: application/json' \
     -H 'Authorization: Bearer <TOKEN>' \
     -d '{
           "ue_id": "u1",
           "latitude": 100,
           "longitude": 50,
           "connected_to": "antenna_1",
          "rf_metrics": {
            "antenna_1": {"rsrp": -80, "sinr": 15, "rsrq": -10}
          }
         }'
```

### `POST /api/train`
Provide an array of training samples to update the model. Each element should
include the same fields as `/api/predict` plus `optimal_antenna` which is the
label used during training.

```bash
curl -X POST http://localhost:5050/api/train \
     -H 'Content-Type: application/json' \
     -H 'Authorization: Bearer <TOKEN>' \
     -d @training_data.json
```

### `GET /api/nef-status`
Check connectivity with the NEF emulator specified by `NEF_API_URL`.

```bash
curl http://localhost:5050/api/nef-status
```

### `POST /api/collect-data`
Trigger data collection directly from the NEF emulator. Provide NEF credentials
and optional `duration` and `interval` parameters.

```bash
curl -X POST http://localhost:5050/api/collect-data \
     -H 'Content-Type: application/json' \
     -H 'Authorization: Bearer <TOKEN>' \
     -d '{"username": "admin", "password": "admin", "duration": 60, "interval": 1}'
```

### `GET /metrics`
Expose Prometheus metrics for monitoring.

```bash
curl http://localhost:5050/metrics
```

### Visualization Endpoints
Additional helpers under `/api/visualization` generate PNG images.

```
# Coverage map of predicted antennas
curl -o coverage.png http://localhost:5050/api/visualization/coverage-map

# Movement trajectory (POST JSON array of samples)
curl -X POST http://localhost:5050/api/visualization/trajectory \
     -H 'Content-Type: application/json' -d @trajectory.json -o trajectory.png
```

## Environment Variables

The service reads configuration from the Flask app settings. Important variables:

| Variable | Description | Default |
|---------------|-----------------------------------------------------------|-------------------------------|
| `NEF_API_URL` | Base URL of the NEF emulator used by the `/nef-status` API | `http://localhost:8080` |
| `MODEL_PATH` | Location of the persisted model file | `app/models/antenna_selector.joblib` |
| `LIGHTGBM_TUNE` | Run hyperparameter tuning on startup when set to `1` | `0` |
| `LIGHTGBM_TUNE_N_ITER` | Number of parameter combinations to try during tuning | `10` |
| `LIGHTGBM_TUNE_CV` | Cross-validation folds used while tuning | `3` |
| `NEIGHBOR_COUNT` | Preallocate feature slots for this many neighbouring antennas | *(dynamic)* |
| `RESOURCE_BLOCKS` | Number of resource blocks used when computing per-antenna RSRQ | `50` |
| `AUTH_USERNAME` | Username for the `/api/login` endpoint | `admin` |
| `AUTH_PASSWORD` | Password for the `/api/login` endpoint | `admin` |
| `JWT_SECRET` | Secret key used to sign JWT tokens | `change-me` |
| `SSL_CERTFILE` | Path to TLS certificate for HTTPS | *(unset)* |
| `SSL_KEYFILE` | Path to TLS key for HTTPS | *(unset)* |

The service always runs with a LightGBM model; no other model types are supported.
`RESOURCE_BLOCKS` is used by `NetworkStateManager` when calculating RSRQ for each antenna.
`MODEL_PATH` determines where this model is stored and is read from the environment at startup. Override it to choose a custom location.
To retain the model between container runs you can mount a host directory and point `MODEL_PATH` at a file in that directory.

Each saved model is accompanied by a `*.meta.json` file containing the
`model_type`, training metrics, a `trained_at` timestamp and a version string.  When the service
starts, this metadata is checked to ensure the correct model class is loaded.
If the stored type differs from the configured one a `ModelError` is raised.
A warning is logged when the version in the metadata does not match the
internal model format version (`1.0`).

During initialization the service keeps track of the last successfully loaded
model. Should loading or training fail for any reason, this previous model is
restored automatically and the error is logged. This ensures predictions can
continue using the last working model even if a startup update fails.

For example, create a `docker-compose.override.yml`:

```yaml
services:
  ml-service:
    volumes:
      - ./model-data:/persisted-model
    environment:
      - MODEL_PATH=/persisted-model/antenna_selector.joblib
```

This service is called by the NEF emulator using the `ML_SERVICE_URL` variable.
The emulator sends UE feature vectors to `/api/predict` and expects the returned
`antenna_id` to perform a handover.

These variables can be supplied in your environment or via `docker-compose`.

Example request mirroring the NEF emulator:
```bash
curl -X POST http://localhost:5050/api/predict \
     -H 'Content-Type: application/json' \
     -H 'Authorization: Bearer <TOKEN>' \
     -d '{"ue_id":"u1","latitude":100,"longitude":50,"connected_to":"antenna_1"}'
```

## Running Locally

Install the dependencies and start the Flask app:

```bash
pip install -r ../../../requirements.txt
python app.py
```

The API will be available on `http://localhost:5050`.
To serve the API over HTTPS set `SSL_CERTFILE` and `SSL_KEYFILE` to the
paths of your certificate and key.

## Running with Docker

Build and run the container directly:

```bash
docker build -t ml-service .
docker run -p 5050:5050 \
  -e NEF_API_URL=http://localhost:8080 \
  -e SSL_CERTFILE=/certs/cert.pem \
  -e SSL_KEYFILE=/certs/key.pem \
  -v /path/to/certs:/certs:ro \
  ml-service
```

The service is also started automatically when using the repository
`docker-compose.yml`.

## Training the Model

Ensure the NEF emulator is running with UEs in motion
before collecting data.  Training data is gathered with
`collect_training_data.py` which leverages `app/data/nef_collector.py`.
Collected JSON files are stored under `app/data/collected_data` and can be sent
to the `/api/train` endpoint to update the selected model. The trained model is
persisted at the location specified by `MODEL_PATH`.
Each sample now also contains an `rf_metrics` dictionary with per-antenna RSRP,
SINR and optionally RSRQ values.
If the NEF provides altitude for a UE it is stored in the `altitude` field so
that predictions can account for the device's height.

```bash
# Collect data for five minutes and train the model when done
python collect_training_data.py --duration 300 --train
```

The script accepts `--url`, `--username` and `--password` options to authenticate
with the NEF emulator if needed.  Passing `--ml-service-url` will trigger
collection via the `/api/collect-data` endpoint of a running ML service instead
of gathering data locally. After training, the updated model file can be
loaded automatically on the next service start.

## Hyperparameter Tuning

Set the environment variable `LIGHTGBM_TUNE=1` before starting the service to
run a quick randomized search for optimal LightGBM parameters. During
initialization the service generates synthetic data and executes the tuning
routine defined in `app/utils/tuning.py`.  The best estimator is then persisted
at `MODEL_PATH`.

The tuning helpers expose optional `n_iter` and `cv` parameters controlling the
number of random search iterations and the cross‑validation folds. When the
service starts with `LIGHTGBM_TUNE=1` these values default to `10` and `3`
respectively.  You can override them by setting `LIGHTGBM_TUNE_N_ITER` and
`LIGHTGBM_TUNE_CV` environment variables or by calling
`tune_and_train(model, data, n_iter=..., cv=...)` directly from your own
scripts.

With the default search (`n_iter=10`, `cv=3`) tuning synthetic data of 500
samples typically finishes in a few seconds on a modern laptop and requires less
than 200 MB of RAM. Increase `n_iter` or `cv` to explore a larger parameter
space at the cost of longer runtimes and higher memory usage.

```bash
LIGHTGBM_TUNE=1 python app.py
```

Tuning uses a small search space suitable for demonstration purposes. Adjust
`tuning.tune_lightgbm` if more exhaustive searches are required.
