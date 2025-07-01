"""API routes for ML Service."""
from flask import jsonify, request, current_app
import requests
from pathlib import Path
from . import api_bp
from ..initialization.model_init import get_model
from ..data.nef_collector import NEFDataCollector

# Initialize the model
model = get_model()


@api_bp.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint."""
    return jsonify({"status": "ok", "service": "ml-service"})


@api_bp.route("/predict", methods=["POST"])
def predict():
    """Make antenna selection prediction based on UE data."""
    data = request.json

    try:
        # Extract features from request data
        features = model.extract_features(data)

        # Make prediction
        result = model.predict(features)

        return jsonify(
            {
                "ue_id": data.get("ue_id"),
                "predicted_antenna": result["antenna_id"],
                "confidence": result["confidence"],
                "features_used": list(features.keys()),
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@api_bp.route("/train", methods=["POST"])
def train():
    """Train the model with provided data."""
    data = request.json

    try:
        # Train the model
        metrics = model.train(data)

        # Save the model
        model.save()

        return jsonify({"status": "success", "metrics": metrics})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


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
    except Exception as e:
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
    except Exception:
        pass

    return jsonify({"samples": len(samples), "file": latest})
