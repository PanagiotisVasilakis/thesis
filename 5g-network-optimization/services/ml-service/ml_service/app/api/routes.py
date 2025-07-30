"""API routes for ML Service."""
from flask import jsonify, request, current_app, g
import time
from pathlib import Path
from functools import wraps
import asyncio
from pydantic import ValidationError

from . import api_bp
from ..api_lib import load_model, predict as predict_ue, train as train_model
from ..data.nef_collector import NEFDataCollector
from ..clients.nef_client import NEFClient, NEFClientError
from ..monitoring.metrics import track_prediction, track_training
from ..schemas import PredictionRequest, TrainingSample, FeedbackSample
from ..initialization.model_init import ModelManager
from ..auth import create_access_token, verify_token


def require_auth(func):
    """Decorator enforcing JWT authentication."""
    def _check_token():
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return jsonify({"error": "Missing token"}), 401
        token = header.split(" ", 1)[1]
        user = verify_token(token)
        if not user:
            return jsonify({"error": "Invalid token"}), 401
        g.user = user

    if asyncio.iscoroutinefunction(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            resp = _check_token()
            if resp is not None:
                return resp
            return await func(*args, **kwargs)

        return async_wrapper
    else:
        @wraps(func)
        def wrapper(*args, **kwargs):
            resp = _check_token()
            if resp is not None:
                return resp
            return func(*args, **kwargs)

        return wrapper


@api_bp.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint."""
    return jsonify({"status": "ok", "service": "ml-service"})


@api_bp.route("/login", methods=["POST"])
def login():
    """Return a JWT token for valid credentials."""
    data = request.get_json(silent=True) or {}
    username = data.get("username")
    password = data.get("password")
    if (
        username == current_app.config["AUTH_USERNAME"]
        and password == current_app.config["AUTH_PASSWORD"]
    ):
        token = create_access_token(username)
        return jsonify({"access_token": token})
    return jsonify({"error": "Invalid credentials"}), 401


@api_bp.route("/predict", methods=["POST"])
@require_auth
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
    if hasattr(current_app, "metrics_collector"):
        current_app.metrics_collector.drift_monitor.update(features)

    return jsonify(
        {
            "ue_id": req.ue_id,
            "predicted_antenna": result["antenna_id"],
            "confidence": result["confidence"],
            "features_used": list(features.keys()),
        }
    )


@api_bp.route("/train", methods=["POST"])
@require_auth
def train():
    """Train the model with provided data."""
    payload = request.get_json(silent=True)
    if not isinstance(payload, list):
        return jsonify({"error": "Training data must be a list"}), 400

    samples = []
    try:
        for item in payload:
            samples.append(
                TrainingSample.parse_obj(item).dict(exclude_none=True)
            )
    except ValidationError as err:
        return jsonify({"error": err.errors()}), 400

    model = load_model(current_app.config["MODEL_PATH"])
    start = time.time()
    metrics = train_model(samples, model=model)
    duration = time.time() - start
    track_training(
        duration, metrics.get("samples", 0), metrics.get("val_accuracy")
    )
    model.save()

    return jsonify({"status": "success", "metrics": metrics})


@api_bp.route("/nef-status", methods=["GET"])
@require_auth
def nef_status():
    """Check NEF connectivity and get status."""
    try:
        nef_url = current_app.config["NEF_API_URL"]
        client = NEFClient(nef_url)
        response = client.get_status()

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
    except ValueError as exc:
        current_app.logger.error("Invalid NEF response: %s", exc)
        return (
            jsonify(
                {
                    "status": "error",
                    "message": f"Invalid response from NEF: {exc}",
                }
            ),
            500,
        )
    except NEFClientError as exc:
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


@api_bp.route("/collect-data", methods=["POST"])
@require_auth
async def collect_data():
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

    samples = await collector.collect_training_data(
        duration=duration, interval=interval
    )

    latest = None
    try:
        files = sorted(Path(collector.data_dir).glob("training_data_*.json"))
        if files:
            latest = str(files[-1])
    except OSError:
        current_app.logger.exception(
            "Failed to find latest training data file"
        )

    return jsonify({"samples": len(samples), "file": latest})


@api_bp.route("/feedback", methods=["POST"])
@require_auth
def feedback():
    """Receive handover outcome feedback from the NEF emulator."""
    payload = request.get_json(silent=True)
    if payload is None:
        return jsonify({"error": "Invalid JSON"}), 400

    data_list = payload if isinstance(payload, list) else [payload]
    samples = []
    try:
        for item in data_list:
            samples.append(FeedbackSample.parse_obj(item))
    except ValidationError as err:
        return jsonify({"error": err.errors()}), 400

    retrained = False
    for sample in samples:
        retrained = ModelManager.feed_feedback(
            sample.dict(exclude_none=True, exclude={"success"}),
            success=sample.success,
        ) or retrained

    return jsonify({"status": "received", "samples": len(samples), "retrained": retrained})
