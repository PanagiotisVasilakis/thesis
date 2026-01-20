"""API routes for ML Service."""
from flask import jsonify, request, current_app, g
import time
import math
from pathlib import Path
import asyncio
from pydantic import ValidationError

from . import api_bp
from .decorators import require_auth, require_roles, handle_model_errors
from ..api_lib import load_model, predict as predict_ue, train as train_model
from ..data.nef_collector import NEFDataCollector
from ..clients.nef_client import NEFClient, NEFClientError
from ..errors import (
    RequestValidationError,
    ModelError,
    NEFConnectionError,
)
from ..monitoring.metrics import track_prediction, track_training, QOS_FEEDBACK_EVENTS, ADAPTIVE_CONFIDENCE
from ..schemas import PredictionRequest, TrainingSample, FeedbackSample
from ..schemas import PredictionRequestWithQoS, QoSFeedbackRequest
from ..core.adaptive_qos import adaptive_qos_manager
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
@handle_model_errors("Prediction")
def predict():
    """Make antenna selection prediction based on UE data."""
    req = request.validated_data  # type: ignore[attr-defined]

    model = load_model(current_app.config["MODEL_PATH"])
    request_payload = req.model_dump(exclude_none=True)
    result, features = predict_ue(request_payload, model=model)

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


@api_bp.route("/predict-with-qos", methods=["POST"])
@require_auth
@require_roles("predict", "admin")
@limiter.limit(limit_for("predict"))
@validate_content_type("application/json")
@validate_request_size(5)  # 5MB max for prediction requests
@validate_json_input(PredictionRequestWithQoS)
@handle_model_errors("Prediction")
def predict_with_qos():
    """Make antenna selection prediction considering QoS requirements."""
    req = request.validated_data  # type: ignore[attr-defined]

    model = load_model(current_app.config["MODEL_PATH"])
    request_payload = req.model_dump(exclude_none=True)
    result, features = predict_ue(request_payload, model=model)

    track_prediction(result["antenna_id"], result["confidence"])
    if hasattr(current_app, "metrics_collector"):
        current_app.metrics_collector.drift_monitor.update(features)  # type: ignore[attr-defined]

    return jsonify(
        {
            "ue_id": req.ue_id,
            "predicted_antenna": result["antenna_id"],
            "confidence": result["confidence"],
            "qos_compliance": result.get("qos_compliance", {"service_priority_ok": True}),
            "features_used": list(features.keys()),
        }
    )


@api_bp.route("/qos-feedback", methods=["POST"])
@require_auth
@require_roles("predict", "admin", "nef")
@limiter.limit(limit_for("feedback"))
@validate_content_type("application/json")
@validate_request_size(1)
@validate_json_input(QoSFeedbackRequest)
def qos_feedback():
    """Ingest post-handover QoS metrics from the NEF emulator."""

    payload: QoSFeedbackRequest = request.validated_data  # type: ignore[attr-defined]
    observed = (
        payload.observed_qos.to_filtered_dict()
        if payload.observed_qos is not None
        else {}
    )

    model = load_model(current_app.config["MODEL_PATH"])
    model.record_qos_feedback(
        ue_id=payload.ue_id,
        antenna_id=payload.antenna_id,
        service_type=payload.service_type,
        metrics=observed,
        passed=payload.success,
        confidence=payload.confidence,
        qos_requirements=payload.qos_requirements or {},
        timestamp=payload.timestamp,
    )

    outcome = "success" if payload.success else "failure"
    try:
        QOS_FEEDBACK_EVENTS.labels(service_type=payload.service_type, outcome=outcome).inc()
    except Exception as exc:
        current_app.logger.debug("Failed to increment QoS feedback metric: %s", exc)

    adaptive_required = adaptive_qos_manager.get_required_confidence(
        payload.service_type,
        payload.service_priority,
    )

    try:
        ADAPTIVE_CONFIDENCE.labels(service_type=payload.service_type).set(adaptive_required)
    except Exception as exc:
        current_app.logger.debug("Failed to set adaptive confidence metric: %s", exc)

    return jsonify(
        {
            "status": "accepted",
            "adaptive_required_confidence": adaptive_required,
        }
    )


@api_bp.route("/predict-async", methods=["POST"])
@require_auth
@require_roles("predict", "admin")
@limiter.limit(limit_for("predict_async"))
@validate_content_type("application/json")
@validate_request_size(5)  # 5MB max for prediction requests
@validate_json_input(PredictionRequest)
@handle_model_errors("Async prediction")
async def predict_async():
    """Make async antenna selection prediction based on UE data."""
    req = request.validated_data  # type: ignore[attr-defined]

    model = load_model(current_app.config["MODEL_PATH"])
    request_payload = req.model_dump(exclude_none=True)
    features = model.extract_features(request_payload)
    result = await model.predict_async(features)

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
@handle_model_errors("Training")
def train():
    """Train the model with provided data."""
    validated_samples = request.validated_data  # type: ignore[attr-defined]
    samples = [sample.model_dump(exclude_none=True) for sample in validated_samples]

    model = load_model(current_app.config["MODEL_PATH"])
    start = time.time()
    training_metrics = train_model(samples, model=model)
    duration = time.time() - start

    track_training(
        duration,
        training_metrics.get("samples", 0),
        training_metrics.get("val_accuracy"),
        training_metrics.get("feature_importance"),
    )
    ModelManager.save_active_model(training_metrics)

    return jsonify({"status": "success", "metrics": training_metrics})


@api_bp.route("/train-cv", methods=["POST"])
@require_auth
@require_roles("train", "admin")
@limiter.limit(limit_for("train"))
@validate_content_type("application/json")
@validate_request_size(50)
@validate_json_input(TrainingSample, allow_list=True)
@handle_model_errors("Cross-validation training")
def train_cv():
    """Train model with K-fold cross-validation for thesis-grade evaluation.
    
    Query Parameters:
        n_folds: Number of CV folds (default: 5)
    
    Returns:
        Metrics including mean ± std accuracy and F1, suitable for thesis reporting
    """
    validated_samples = request.validated_data  # type: ignore[attr-defined]
    samples = [sample.model_dump(exclude_none=True) for sample in validated_samples]
    
    n_folds = request.args.get("n_folds", 5, type=int)
    
    model = load_model(current_app.config["MODEL_PATH"])
    
    # Check if model has train_with_cv method
    if not hasattr(model, "train_with_cv"):
        return jsonify({
            "error": "Model does not support cross-validation training",
        }), 400
    
    start = time.time()
    cv_metrics = model.train_with_cv(samples, n_folds=n_folds)
    duration = time.time() - start
    
    cv_metrics["training_duration_seconds"] = duration
    
    # Save the model that was trained on all data
    if "final_model_metrics" in cv_metrics:
        track_training(
            duration,
            cv_metrics["final_model_metrics"].get("samples", 0),
            cv_metrics.get("cv_mean_accuracy"),
            cv_metrics["final_model_metrics"].get("feature_importance"),
        )
        ModelManager.save_active_model(cv_metrics["final_model_metrics"])
    
    return jsonify({
        "status": "success",
        "cv_metrics": cv_metrics,
        "report": {
            "accuracy": cv_metrics.get("accuracy_report"),
            "f1": cv_metrics.get("f1_report"),
        }
    })


@api_bp.route("/tune", methods=["POST"])
@require_auth
@require_roles("admin")
@limiter.limit(limit_for("train"))
@validate_content_type("application/json")
@validate_request_size(50)
@validate_json_input(TrainingSample, allow_list=True)
@handle_model_errors("Hyperparameter tuning")
def tune_hyperparameters():
    """Run hyperparameter optimization using Optuna.
    
    Query Parameters:
        n_trials: Number of optimization trials (default: 50)
        metric: Optimization metric ('accuracy' or 'f1', default: 'f1')
    
    Returns:
        Best parameters and optimization history
    """
    validated_samples = request.validated_data  # type: ignore[attr-defined]
    samples = [sample.model_dump(exclude_none=True) for sample in validated_samples]
    
    n_trials = request.args.get("n_trials", 50, type=int)
    metric = request.args.get("metric", "f1")
    
    try:
        from ..models.hyperparameter_tuning import HyperparameterTuner
        
        model = load_model(current_app.config["MODEL_PATH"])
        
        tuner = HyperparameterTuner(
            feature_names=model.feature_names,
            metric=metric,
        )
        
        if not tuner.is_available():
            return jsonify({
                "error": "Optuna not installed. Run: pip install optuna",
            }), 503
        
        start = time.time()
        results = tuner.optimize(samples, n_trials=n_trials)
        duration = time.time() - start
        
        results["tuning_duration_seconds"] = duration
        
        return jsonify({
            "status": "success",
            "results": results,
        })
        
    except ImportError as e:
        return jsonify({
            "error": f"Hyperparameter tuning module not available: {e}",
        }), 503


@api_bp.route("/train-async", methods=["POST"])
@require_auth
@require_roles("train", "admin")
@limiter.limit(limit_for("train_async"))
@validate_content_type("application/json")
@validate_request_size(50)  # 50MB max for training data
@validate_json_input(TrainingSample, allow_list=True)
@handle_model_errors("Async training")
async def train_async():
    """Train the model asynchronously with provided data."""
    validated_samples = request.validated_data  # type: ignore[attr-defined]
    samples = [sample.model_dump(exclude_none=True) for sample in validated_samples]

    model = load_model(current_app.config["MODEL_PATH"])
    start = time.time()
    training_metrics = await model.train_async(samples)
    duration = time.time() - start

    track_training(
        duration,
        training_metrics.get("samples", 0),
        training_metrics.get("val_accuracy"),
        training_metrics.get("feature_importance"),
    )
    ModelManager.save_active_model(training_metrics)

    return jsonify({"status": "success", "metrics": training_metrics, "async": True})


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


@api_bp.route("/explain", methods=["POST"])
@require_auth
@require_roles("predict", "admin")
@limiter.limit(limit_for("predict"))
@validate_content_type("application/json")
@validate_request_size(5)
@validate_json_input(PredictionRequest)
@handle_model_errors("Explanation")
def explain_prediction():
    """Explain a prediction using SHAP values.
    
    This endpoint provides interpretability for ML predictions, useful for:
    - Thesis documentation and figures
    - Debugging unexpected predictions
    - Understanding feature contributions
    
    Returns:
        JSON with prediction, confidence, and SHAP feature contributions
    """
    req = request.validated_data  # type: ignore[attr-defined]
    
    model = load_model(current_app.config["MODEL_PATH"])
    request_payload = req.model_dump(exclude_none=True)
    features = model.extract_features(request_payload)
    
    # Get SHAP explanation
    try:
        from ..models.interpretability import ModelExplainer
        
        explainer = ModelExplainer(
            model.model,
            model.feature_names,
        )
        
        if not explainer.is_available():
            return jsonify({
                "error": "SHAP not available. Install with: pip install shap",
                "ue_id": req.ue_id,
            }), 503
        
        explanation = explainer.explain_prediction(features, top_k=10)
        explanation["ue_id"] = req.ue_id
        explanation["features_used"] = list(features.keys())
        
        return jsonify(explanation)
        
    except ImportError as e:
        return jsonify({
            "error": f"Interpretability module not available: {e}",
            "ue_id": req.ue_id,
        }), 503
    except Exception as e:
        current_app.logger.error("Explanation failed: %s", e)
        return jsonify({
            "error": str(e),
            "ue_id": req.ue_id,
        }), 500


@api_bp.route("/feature-importance", methods=["GET"])
@require_auth
@require_roles("admin")
def feature_importance():
    """Get overall feature importance based on model's built-in feature importances.
    
    Returns:
        JSON with ranked feature importances
    """
    model = load_model(current_app.config["MODEL_PATH"])
    
    if not hasattr(model.model, 'feature_importances_'):
        return jsonify({
            "error": "Model does not have feature importances",
        }), 400
    
    importances = dict(zip(
        model.feature_names,
        [float(x) for x in model.model.feature_importances_]
    ))
    
    sorted_importances = sorted(
        importances.items(),
        key=lambda x: x[1],
        reverse=True
    )
    
    return jsonify({
        "feature_importance": dict(sorted_importances),
        "top_10": sorted_importances[:10],
    })


@api_bp.route("/latency-stats", methods=["GET"])
@require_auth
@require_roles("admin")
def latency_stats():
    """Get prediction latency statistics for thesis figures.
    
    Returns percentiles (p50, p95, p99) and histogram data suitable
    for generating latency distribution plots.
    
    Returns:
        JSON with latency percentiles and histogram buckets
    """
    try:
        from ..monitoring.metrics import (
            PREDICTION_LATENCY,
            PREDICTION_STAGE_LATENCY,
        )
        
        # Extract histogram data from Prometheus metrics
        latency_data = {}

        total_count, total_sum, buckets = _extract_histogram_samples(PREDICTION_LATENCY)

        latency_data["prediction"] = {
            "total_count": total_count,
            "total_sum": total_sum,
            "mean_latency_seconds": total_sum / total_count if total_count > 0 else 0,
            "mean_latency_ms": (total_sum / total_count * 1000) if total_count > 0 else 0,
            "buckets": buckets,
        }

        if total_count > 0 and buckets:
            latency_data["prediction"]["percentiles"] = _calculate_percentiles_from_buckets(
                buckets, total_count
            )
        
        # Get stage latency breakdown
        stage_latencies = {}
        for stage in ["feature_extraction", "model_inference", "ping_pong_check", "qos_validation"]:
            try:
                count, total, _ = _extract_histogram_samples(
                    PREDICTION_STAGE_LATENCY,
                    label_matcher=lambda labels, stage=stage: labels.get("stage") == stage,
                )
                stage_latencies[stage] = {
                    "count": count,
                    "mean_ms": (total / count * 1000) if count > 0 else 0,
                }
            except Exception:
                pass
        
        latency_data["stages"] = stage_latencies
        
        return jsonify({
            "status": "success",
            "latency_data": latency_data,
        })
        
    except Exception as e:
        current_app.logger.error("Failed to get latency stats: %s", e)
        return jsonify({
            "error": str(e),
        }), 500


def _extract_histogram_samples(metric, label_matcher=None):
    """Extract histogram buckets and summary stats from a Prometheus metric."""
    total_count = 0.0
    total_sum = 0.0
    buckets = []
    for family in metric.collect():
        for sample in family.samples:
            if label_matcher and not label_matcher(sample.labels):
                continue
            if sample.name.endswith("_sum"):
                total_sum = float(sample.value)
            elif sample.name.endswith("_count"):
                total_count = float(sample.value)
            elif sample.name.endswith("_bucket"):
                upper = sample.labels.get("le")
                if upper is None:
                    continue
                upper_bound = float("inf") if upper == "+Inf" else float(upper)
                buckets.append({"upper_bound": upper_bound, "count": float(sample.value)})
    buckets.sort(key=lambda b: b["upper_bound"])
    return total_count, total_sum, buckets


def _calculate_percentiles_from_buckets(buckets, total_count):
    """Calculate approximate percentiles from histogram buckets.
    
    Uses linear interpolation within buckets to estimate percentiles.
    """
    percentiles = {}
    target_percentiles = {
        "p50": 0.50,
        "p75": 0.75,
        "p90": 0.90,
        "p95": 0.95,
        "p99": 0.99,
    }
    
    for name, target_ratio in target_percentiles.items():
        target_count = total_count * target_ratio
        
        prev_bound = 0.0
        prev_count = 0.0
        
        for bucket in buckets:
            upper_bound = bucket["upper_bound"]
            count = bucket["count"]
            
            if count >= target_count:
                # Linear interpolation within bucket
                if count > prev_count:
                    ratio = (target_count - prev_count) / (count - prev_count)
                else:
                    ratio = 0
                if math.isinf(upper_bound):
                    percentile_value = prev_bound
                else:
                    percentile_value = prev_bound + ratio * (upper_bound - prev_bound)
                percentiles[name] = {
                    "seconds": float(percentile_value),
                    "ms": float(percentile_value * 1000),
                }
                break
            
            prev_bound = upper_bound
            prev_count = count
    
    return percentiles


# =============================================================================
# A/B Testing Endpoints
# =============================================================================

@api_bp.route("/experiments", methods=["GET"])
@require_auth
@require_roles("admin")
def list_experiments():
    """List all A/B testing experiments."""
    try:
        from ..models.ab_testing import ABTestManager
        ab = ABTestManager.get_instance()
        return jsonify({
            "status": "success",
            "experiments": ab.list_experiments(),
        })
    except ImportError:
        return jsonify({"error": "A/B testing module not available"}), 503


@api_bp.route("/experiments", methods=["POST"])
@require_auth
@require_roles("admin")
@validate_content_type("application/json")
def create_experiment():
    """Create a new A/B testing experiment.
    
    Request body:
        name: Experiment name (required)
        control_model: Control model type (default: "lightgbm")
        treatment_model: Treatment model type (default: "lstm")
        traffic_split: Fraction for treatment (0.0-1.0, default: 0.1)
    """
    try:
        from ..models.ab_testing import ABTestManager
        
        data = request.get_json()
        if not data or "name" not in data:
            return jsonify({"error": "Experiment name is required"}), 400
        
        ab = ABTestManager.get_instance()
        experiment = ab.create_experiment(
            name=data["name"],
            control_model=data.get("control_model", "lightgbm"),
            treatment_model=data.get("treatment_model", "lstm"),
            traffic_split=float(data.get("traffic_split", 0.1)),
        )
        
        return jsonify({
            "status": "success",
            "experiment": experiment.to_dict(),
        })
        
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except ImportError:
        return jsonify({"error": "A/B testing module not available"}), 503


@api_bp.route("/experiments/<name>", methods=["GET"])
@require_auth
@require_roles("admin")
def get_experiment(name: str):
    """Get details of an A/B testing experiment."""
    try:
        from ..models.ab_testing import ABTestManager
        ab = ABTestManager.get_instance()
        experiment = ab.get_experiment(name)
        
        if experiment is None:
            return jsonify({"error": f"Experiment '{name}' not found"}), 404
        
        return jsonify({
            "status": "success",
            "experiment": experiment,
        })
        
    except ImportError:
        return jsonify({"error": "A/B testing module not available"}), 503


@api_bp.route("/experiments/<name>/end", methods=["POST"])
@require_auth
@require_roles("admin")
def end_experiment(name: str):
    """End an A/B testing experiment and get final results."""
    try:
        from ..models.ab_testing import ABTestManager
        ab = ABTestManager.get_instance()
        result = ab.end_experiment(name)
        
        if result is None:
            return jsonify({"error": f"Experiment '{name}' not found"}), 404
        
        return jsonify({
            "status": "success",
            "final_results": result,
        })
        
    except ImportError:
        return jsonify({"error": "A/B testing module not available"}), 503


@api_bp.route("/experiments/<name>/comparison", methods=["GET"])
@require_auth
@require_roles("admin")
def experiment_comparison(name: str):
    """Get thesis-ready comparison summary for an experiment.
    
    Returns formatted data suitable for thesis tables/figures.
    """
    try:
        from ..models.ab_testing import ABTestManager
        ab = ABTestManager.get_instance()
        summary = ab.get_comparison_summary(name)
        
        if summary is None:
            return jsonify({"error": f"Experiment '{name}' not found"}), 404
        
        return jsonify({
            "status": "success",
            "comparison": summary,
        })
        
    except ImportError:
        return jsonify({"error": "A/B testing module not available"}), 503


@api_bp.route("/model-type", methods=["GET"])
@require_auth
def get_model_type():
    """Get the current active model type configuration."""
    import os
    return jsonify({
        "status": "success",
        "model_type": os.getenv("MODEL_TYPE", "lightgbm"),
        "available_types": ["lightgbm", "lstm", "ensemble", "online"],
    })



