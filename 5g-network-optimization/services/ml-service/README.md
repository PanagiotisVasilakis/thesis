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
`curl` with the default port `5050`.

### `GET /api/health`
Simple health probe.

```bash
curl http://localhost:5050/api/health
```

### `POST /api/predict`
Submit UE information and receive the recommended antenna.
The request body should contain fields such as `ue_id`, `latitude`, `longitude`,
`connected_to` and an optional `rf_metrics` dictionary. Example:

```bash
curl -X POST http://localhost:5050/api/predict \
     -H 'Content-Type: application/json' \
     -d '{
           "ue_id": "u1",
           "latitude": 100,
           "longitude": 50,
           "connected_to": "antenna_1",
           "rf_metrics": {
             "antenna_1": {"rsrp": -80, "sinr": 15}
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
     -d '{"username": "admin", "password": "admin", "duration": 60, "interval": 1}'
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

| Variable      | Description                                               | Default                       |
|---------------|-----------------------------------------------------------|-------------------------------|
| `NEF_API_URL` | Base URL of the NEF emulator used by the `/nef-status` API | `http://localhost:8080`       |
| `MODEL_PATH`  | Location of the persisted model file                      | `app/models/antenna_selector.joblib` |

The service always runs with a LightGBM model; no other model types are supported.

These can be supplied in your environment or via `docker-compose`.

## Running Locally

Install the dependencies and start the Flask app:

```bash
pip install -r ../../../requirements.txt
python app.py
```

The API will be available on `http://localhost:5050`.

## Running with Docker

Build and run the container directly:

```bash
docker build -t ml-service .
docker run -p 5050:5050 -e NEF_API_URL=http://localhost:8080 ml-service
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

```bash
# Collect data for five minutes and train the model when done
python collect_training_data.py --duration 300 --train
```

The script accepts `--url`, `--username` and `--password` options to authenticate
with the NEF emulator if needed.  Passing `--ml-service-url` will trigger
collection via the `/api/collect-data` endpoint of a running ML service instead
of gathering data locally. After training, the updated model file can be
loaded automatically on the next service start.
