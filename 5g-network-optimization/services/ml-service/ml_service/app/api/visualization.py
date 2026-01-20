"""Visualization endpoints for ML Service."""
from flask import Blueprint, request, send_file, current_app
import os
import logging
import requests
from ..errors import RequestValidationError, NEFConnectionError, ResourceNotFoundError
from .decorators import require_auth
from ..models.antenna_selector import DEFAULT_TEST_FEATURES
from ..initialization.model_init import ModelManager
from ..visualization.plotter import (
    plot_antenna_coverage,
    plot_movement_trajectory,
)
from ..utils.synthetic_data import generate_synthetic_training_data
from ..utils import get_output_dir

viz_bp = Blueprint("visualization", __name__, url_prefix="/api/visualization")

logger = logging.getLogger(__name__)


@viz_bp.route("/coverage-map", methods=["GET"])
@require_auth
def coverage_map():
    """Generate and return an antenna coverage map."""
    try:
        model = ModelManager.get_instance(current_app.config["MODEL_PATH"])
        # First, check if the model is trained
        try:
            # Try a simple prediction to see if model is trained
            model.predict(DEFAULT_TEST_FEATURES)
        except Exception as e:
            # Model is not trained, train it with synthetic data
            logger.warning(
                f"Model not trained: {str(e)}. Training with synthetic data..."
            )
            training_data = generate_synthetic_training_data(500)
            model.train(training_data)
            logger.info("Model trained successfully with synthetic data")

        # Resolve the output directory
        output_dir = get_output_dir()
        os.makedirs(output_dir, exist_ok=True)

        # Generate visualization with absolute path
        output_file = plot_antenna_coverage(model, output_dir=output_dir)

        # Check if the file exists
        if not os.path.exists(output_file):
            logger.warning(f"Output file not found at {output_file}")
            # Try to find the file in the relative path
            relative_path = os.path.join(
                "output", os.path.basename(output_file)
            )
            if os.path.exists(relative_path):
                output_file = os.path.abspath(relative_path)
                logger.info(f"Found file at {output_file}")

        # Return the image file
        return send_file(output_file, mimetype="image/png")

    except FileNotFoundError as e:
        logger.error("Coverage map file not found: %s", e)
        raise ResourceNotFoundError(e)
    except requests.exceptions.RequestException as e:
        logger.error("Request error generating coverage map: %s", e)
        raise NEFConnectionError("Failed to fetch required data") from e


@viz_bp.route("/trajectory", methods=["POST"])
@require_auth
def trajectory():
    """Generate and return a movement trajectory visualization."""
    try:
        # Get movement data from request
        movement_data = request.json

        if not movement_data:
            raise RequestValidationError("No movement data provided")

        # Resolve the output directory
        output_dir = get_output_dir()
        os.makedirs(output_dir, exist_ok=True)

        # Generate visualization with absolute path
        output_file = plot_movement_trajectory(
            movement_data, output_dir=output_dir
        )

        # Return the image file
        return send_file(output_file, mimetype="image/png")

    except FileNotFoundError as e:
        logger.error("Trajectory file not found: %s", e)
        raise ResourceNotFoundError(e)
    except requests.exceptions.RequestException as e:
        logger.error("Request error generating trajectory: %s", e)
        raise NEFConnectionError("Failed to fetch required data") from e
