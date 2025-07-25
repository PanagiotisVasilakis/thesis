"""API routes for ML Service."""
from flask import jsonify, request, current_app
import requests
import time
from pathlib import Path
from pydantic import ValidationError

from . import api_bp
from ..api_lib import load_model, predict as predict_ue, train as train_model
from ..data.nef_collector import NEFDataCollector
from ..monitoring.metrics import track_prediction, track_training
from ..schemas import PredictionRequest, TrainingSample


@api_bp.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint."""
    return jsonify({"status": "ok", "service": "ml-service"})


@api_bp.route("/predict", methods=["POST"])
def predict():
    """Make antenna selection prediction based on UE data."""
    payload = request.get_json(silent=True)
    if payload is None:
        return jsonify({"error": "Invalid JSON"}), 400

    try:
        req = PredictionRequest.parse_obj(payload)
    except ValidationError as err:
        return jsonify({"error": err.errors()}), 400

    model = load_model(current_app.config["MODEL_PATH"])
    result, features = predict_ue(req.dict(exclude_none=True), model=model)
    track_prediction(result["antenna_id"], result["confidence"])

    return jsonify(
        {
            "ue_id": req.ue_id,
            "predicted_antenna": result["antenna_id"],
            "confidence": result["confidence"],
            "features_used": list(features.keys()),
        }
    )


@api_bp.route("/train", methods=["POST"])
def train():
    """Train the model with provided data."""
    payload = request.get_json(silent=True)
    if not isinstance(payload, list):
        return jsonify({"error": "Training data must be a list"}), 400

    samples = []
    try:
        for item in payload:
            samples.append(TrainingSample.parse_obj(item).dict(exclude_none=True))
    except ValidationError as err:
        return jsonify({"error": err.errors()}), 400

    model = load_model(current_app.config["MODEL_PATH"])
    start = time.time()
    metrics = train_model(samples, model=model)
    duration = time.time() - start
    track_training(duration, metrics.get("samples", 0), metrics.get("val_accuracy"))
    model.save()

    return jsonify({"status": "success", "metrics": metrics})


@api_bp.route("/nef-status", methods=["GET"])
def nef_status():
    """Check NEF connectivity and get status."""
    try:
        nef_url = current_app.config["NEF_API_URL"]
        response = requests.get(f"{nef_url}/api/v1/paths/")

        if response.status_code == 200:
            return jsonify(
                {
                    "status": "connected",
                    "nef_version": response.headers.get(
                        "X-API-Version", "unknown"
                    ),
                }
            )
        else:
            return jsonify(
                {
                    "status": "error",
                    "code": response.status_code,
                    "message": response.text,
                }
            )
    except requests.exceptions.RequestException as exc:
        current_app.logger.error("NEF connection error: %s", exc)
        return (
            jsonify(
                {
                    "status": "error",
                    "message": f"Failed to connect to NEF: {exc}",
                }
            ),
            502,
        )
    except Exception as e:
        current_app.logger.exception("Unexpected error contacting NEF")
        return (
            jsonify(
                {
                    "status": "error",
                    "message": f"Failed to connect to NEF: {str(e)}",
                }
            ),
            500,
        )


@api_bp.route("/collect-data", methods=["POST"])
def collect_data():
    """Collect training data from the NEF emulator."""
    params = request.json or {}

    duration = int(params.get("duration", 60))
    interval = int(params.get("interval", 1))
    username = params.get("username")
    password = params.get("password")

    nef_url = current_app.config["NEF_API_URL"]
    collector = NEFDataCollector(
        nef_url=nef_url, username=username, password=password
    )

    if username and password and not collector.login():
        return jsonify({"error": "Authentication failed"}), 400

    if not collector.get_ue_movement_state():
        return jsonify({"error": "No UEs found in movement state"}), 400

    samples = collector.collect_training_data(
        duration=duration, interval=interval
    )

    latest = None
    try:
        files = sorted(Path(collector.data_dir).glob("training_data_*.json"))
        if files:
            latest = str(files[-1])
    except OSError:
        current_app.logger.exception("Failed to find latest training data file")

    return jsonify({"samples": len(samples), "file": latest})
