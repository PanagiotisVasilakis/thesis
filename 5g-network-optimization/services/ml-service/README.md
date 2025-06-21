# ML Service

This Flask-based microservice predicts optimal antenna assignments for user equipment (UE).
It exposes a small REST API used by the NEF emulator and by the training scripts.

## API Endpoints

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

## Environment Variables

The service reads configuration from the Flask app settings. Important variables:

| Variable      | Description                                               | Default                       |
|---------------|-----------------------------------------------------------|-------------------------------|
| `NEF_API_URL` | Base URL of the NEF emulator used by the `/nef-status` API | `http://localhost:8080`       |
| `MODEL_PATH`  | Location of the persisted model file                      | `app/models/antenna_selector.joblib` |

These can be supplied in your environment or via `docker-compose`.

## Running Locally

Install the dependencies and start the Flask app:

```bash
pip install -r requirements.txt
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

Use `collect_training_data.py` to gather samples from the NEF emulator and
optionally train the model via the `/api/train` endpoint.

```bash
# Collect data for five minutes and train the model when done
python collect_training_data.py --duration 300 --train
```

The script accepts `--url`, `--username` and `--password` options to authenticate
with the NEF emulator if needed.
