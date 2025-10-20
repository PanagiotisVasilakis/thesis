"""API routes for ML Service."""
from flask import jsonify, request, current_app, g
import time
from pathlib import Path
import asyncio
from pydantic import ValidationError

from . import api_bp
from .decorators import require_auth, require_roles
from ..api_lib import load_model, predict as predict_ue, train as train_model
from ..data.nef_collector import NEFDataCollector
from ..clients.nef_client import NEFClient, NEFClientError
from ..errors import (
    RequestValidationError,
    ModelError,
    NEFConnectionError,
)
from ..monitoring.metrics import track_prediction, track_training
from ..schemas import PredictionRequest, TrainingSample, FeedbackSample
from ..initialization.model_init import ModelManager
from ..auth import (
    create_access_token,
    create_refresh_token,
    verify_refresh_token,
    rotate_refresh_token,
    revoke_refresh_tokens_for_subject,
)
from ..validation import (
    validate_json_input,
    validate_path_params,
    validate_request_size,
    validate_content_type,
    LoginRequest,
    RefreshTokenRequest,
    CollectDataRequest,
    model_version_validator,
    bounded_int,
)
from ..rate_limiter import limiter, limit_for


@api_bp.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint."""
    return jsonify({"status": "ok", "service": "ml-service"})


@api_bp.route("/model-health", methods=["GET"])
def model_health():
    """Return model readiness and metadata."""

    ready = ModelManager.is_ready()
    meta = ModelManager.get_metadata()
    return jsonify({"ready": ready, "metadata": meta})


@api_bp.route("/models", methods=["GET"])
def list_models():
    """Return all discovered model versions."""
    versions = ModelManager.list_versions()
    return jsonify({"versions": versions})


@api_bp.route("/login", methods=["POST"])
@limiter.limit(limit_for("login"))
@validate_content_type("application/json")
@validate_request_size(1)  # 1MB max for login
@validate_json_input(LoginRequest)
def login():
    """Return a JWT token for valid credentials."""
    data = request.validated_data  # type: ignore[attr-defined]
    if (
        data.username == current_app.config["AUTH_USERNAME"]
        and data.password == current_app.config["AUTH_PASSWORD"]
    ):
        roles = list(current_app.config.get("AUTH_ROLES", []))
        revoke_refresh_tokens_for_subject(data.username)
        token = create_access_token(data.username, roles=roles)
        refresh_token = create_refresh_token(data.username, roles=roles)
        return jsonify(
            {
                "access_token": token,
                "refresh_token": refresh_token,
                "roles": roles,
            }
        )
    return jsonify({"error": "Invalid credentials"}), 401


@api_bp.route("/refresh", methods=["POST"])
@limiter.limit(limit_for("refresh"))
@validate_content_type("application/json")
@validate_request_size(1)
@validate_json_input(RefreshTokenRequest)
def refresh_token():
    """Issue a new access token using a valid refresh token."""
    data = request.validated_data  # type: ignore[attr-defined]
    payload = verify_refresh_token(data.refresh_token)
    if not payload:
        return jsonify({"error": "Invalid refresh token"}), 401

    rotate_refresh_token(payload["jti"])
    subject = payload["sub"]
    roles = payload.get("roles", [])

    access_token = create_access_token(subject, roles=roles)
    new_refresh_token = create_refresh_token(subject, roles=roles)

    return jsonify(
        {
            "access_token": access_token,
            "refresh_token": new_refresh_token,
            "roles": roles,
        }
    )


@api_bp.route("/predict", methods=["POST"])
@require_auth
@require_roles("predict", "admin")
@limiter.limit(limit_for("predict"))
@validate_content_type("application/json")
@validate_request_size(5)  # 5MB max for prediction requests
@validate_json_input(PredictionRequest)
def predict():
    """Make antenna selection prediction based on UE data."""
    req = request.validated_data  # type: ignore[attr-defined]

    try:
        model = load_model(current_app.config["MODEL_PATH"])
        request_payload = req.model_dump(exclude_none=True)
        result, features = predict_ue(request_payload, model=model)
    except (ValueError, TypeError, KeyError) as exc:
        # Handle specific model-related errors
        raise ModelError(f"Prediction failed: {exc}") from exc
    except FileNotFoundError as exc:
        # Handle missing model file
        raise ModelError(f"Model file not found: {exc}") from exc

    track_prediction(result["antenna_id"], result["confidence"])
    if hasattr(current_app, "metrics_collector"):
        current_app.metrics_collector.drift_monitor.update(features)  # type: ignore[attr-defined]

    return jsonify(
        {
            "ue_id": req.ue_id,
            "predicted_antenna": result["antenna_id"],
            "confidence": result["confidence"],
            "features_used": list(features.keys()),
        }
    )


@api_bp.route("/predict-async", methods=["POST"])
@require_auth
@require_roles("predict", "admin")
@limiter.limit(limit_for("predict_async"))
@validate_content_type("application/json")
@validate_request_size(5)  # 5MB max for prediction requests
@validate_json_input(PredictionRequest)
async def predict_async():
    """Make async antenna selection prediction based on UE data."""
    req = request.validated_data  # type: ignore[attr-defined]

    try:
        model = load_model(current_app.config["MODEL_PATH"])

        # Extract features for async prediction
        request_payload = req.model_dump(exclude_none=True)
        features = model.extract_features(request_payload)

        # Use async prediction
        result = await model.predict_async(features)

    except (ValueError, TypeError, KeyError) as exc:
        # Handle specific model-related errors
        raise ModelError(f"Async prediction failed: {exc}") from exc
    except FileNotFoundError as exc:
        # Handle missing model file
        raise ModelError(f"Model file not found: {exc}") from exc

    track_prediction(result["antenna_id"], result["confidence"])
    if hasattr(current_app, "metrics_collector"):
        current_app.metrics_collector.drift_monitor.update(features)  # type: ignore[attr-defined]

    return jsonify(
        {
            "ue_id": req.ue_id,
            "predicted_antenna": result["antenna_id"],
            "confidence": result["confidence"],
            "features_used": list(features.keys()),
            "async": True,
        }
    )


@api_bp.route("/train", methods=["POST"])
@require_auth
@require_roles("train", "admin")
@limiter.limit(limit_for("train"))
@validate_content_type("application/json")
@validate_request_size(50)  # 50MB max for training data
@validate_json_input(TrainingSample, allow_list=True)
def train():
    """Train the model with provided data."""
    validated_samples = request.validated_data  # type: ignore[attr-defined]
    samples = [sample.model_dump(exclude_none=True) for sample in validated_samples]

    try:
        model = load_model(current_app.config["MODEL_PATH"])
        start = time.time()
        metrics = train_model(samples, model=model)
        duration = time.time() - start
    except (ValueError, TypeError, KeyError) as exc:
        # Handle specific training errors
        raise ModelError(f"Training failed: {exc}") from exc
    except FileNotFoundError as exc:
        # Handle missing model file
        raise ModelError(f"Model file not found: {exc}") from exc
    except MemoryError as exc:
        # Handle out of memory errors during training
        raise ModelError(f"Insufficient memory for training: {exc}") from exc
    track_training(
        duration,
        metrics.get("samples", 0),
        metrics.get("val_accuracy"),
        metrics.get("feature_importance"),
    )
    ModelManager.save_active_model(metrics)

    return jsonify({"status": "success", "metrics": metrics})


@api_bp.route("/train-async", methods=["POST"])
@require_auth
@require_roles("train", "admin")
@limiter.limit(limit_for("train_async"))
@validate_content_type("application/json")
@validate_request_size(50)  # 50MB max for training data
@validate_json_input(TrainingSample, allow_list=True)
async def train_async():
    """Train the model asynchronously with provided data."""
    validated_samples = request.validated_data  # type: ignore[attr-defined]
    samples = [sample.model_dump(exclude_none=True) for sample in validated_samples]

    try:
        model = load_model(current_app.config["MODEL_PATH"])
        start = time.time()
        
        # Use async training
        metrics = await model.train_async(samples)
        duration = time.time() - start
        
    except (ValueError, TypeError, KeyError) as exc:
        # Handle specific training errors
        raise ModelError(f"Async training failed: {exc}") from exc
    except FileNotFoundError as exc:
        # Handle missing model file
        raise ModelError(f"Model file not found: {exc}") from exc
    except MemoryError as exc:
        # Handle out of memory errors during training
        raise ModelError(f"Insufficient memory for async training: {exc}") from exc
        
    track_training(
        duration, metrics.get("samples", 0), metrics.get("val_accuracy")
    )
    ModelManager.save_active_model(metrics)

    return jsonify({"status": "success", "metrics": metrics, "async": True})


@api_bp.route("/nef-status", methods=["GET"])
@require_auth
@require_roles("nef", "admin")
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
        raise NEFConnectionError(
            f"NEF returned {response.status_code}: {response.text}"
        )
    except ValueError as exc:
        current_app.logger.error("Invalid NEF response: %s", exc)
        raise NEFConnectionError(f"Invalid response from NEF: {exc}") from exc
    except NEFClientError as exc:
        current_app.logger.error("NEF connection error: %s", exc)
        raise NEFConnectionError(f"Failed to connect to NEF: {exc}") from exc


@api_bp.route("/collect-data", methods=["POST"])
@require_auth
@require_roles("data", "admin")
@limiter.limit(limit_for("collect_data"))
@validate_content_type("application/json")
@validate_request_size(1)  # 1MB max for data collection params
@validate_json_input(CollectDataRequest, required=False)
def collect_data():
    """Collect training data from the NEF emulator."""
    params = getattr(request, "validated_data", None)
    if params is None:
        params = CollectDataRequest.model_validate({})

    duration = params.duration
    interval = params.interval
    username = params.username
    password = params.password

    nef_url = current_app.config["NEF_API_URL"]
    collector = NEFDataCollector(
        nef_url=nef_url, username=username, password=password
    )

    if username and password and not collector.login():
        raise RequestValidationError("Authentication failed")

    if not collector.get_ue_movement_state():
        raise RequestValidationError("No UEs found in movement state")

    def _execute_collection():
        async def _collect():
            return await collector.collect_training_data(
                duration=duration, interval=interval
            )

        try:
            return asyncio.run(_collect())
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(_collect())
            finally:
                loop.close()

    try:
        samples = _execute_collection()
    except NEFClientError as exc:
        raise NEFConnectionError(exc) from exc

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
@require_roles("feedback", "admin")
@limiter.limit(limit_for("feedback"))
@validate_content_type("application/json")
@validate_request_size(10)  # 10MB max for feedback data
@validate_json_input(FeedbackSample, allow_list=True)
def feedback():
    """Receive handover outcome feedback from the NEF emulator."""
    samples = request.validated_data  # type: ignore[attr-defined]
    if not isinstance(samples, list):
        samples = [samples]

    retrained = False
    for sample in samples:
        retrained = ModelManager.feed_feedback(
            sample.model_dump(exclude_none=True, exclude={"success"}),
            success=sample.success,
        ) or retrained

    return jsonify({"status": "received", "samples": len(samples), "retrained": retrained})


@api_bp.route("/models/<version>", methods=["POST", "PUT"])
@require_auth
@require_roles("admin")
@validate_path_params(version=model_version_validator)
def switch_model(version: str):
    """Switch the active model to the specified version."""
    try:
        ModelManager.switch_version(version)
        return jsonify({"status": "ok", "version": version})
    except ValueError as err:
        raise RequestValidationError(str(err)) from err
    except FileNotFoundError as err:
        raise ModelError(f"Model version '{version}' not found: {err}") from err
    except PermissionError as err:
        raise ModelError(f"Permission denied accessing model '{version}': {err}") from err
    except OSError as err:
        raise ModelError(f"System error switching to model '{version}': {err}") from err
