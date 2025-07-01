# -*- coding: utf-8 -*-
"""Utility script to generate presentation visuals.

This script creates example antenna coverage maps as well as trajectory
plots for linear and L-shaped mobility patterns. The generated PNG files
and accompanying description text files are stored under
``presentation_assets/`` within the repository.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

# ---------------------------------------------------------------------------
# Configure import paths so that local service packages are available
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[1]
SERVICES_ROOT = REPO_ROOT / "5g-network-optimization" / "services"
ML_SERVICE_ROOT = SERVICES_ROOT / "ml-service"
NEF_APP_ROOT = SERVICES_ROOT / "nef-emulator" / "backend" / "app" / "app"

for path in (ML_SERVICE_ROOT, NEF_APP_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from ml_service.app.models.antenna_selector import AntennaSelector
from ml_service.app.visualization.plotter import (
    plot_antenna_coverage,
    plot_movement_trajectory,
)
from app.tools.mobility.adapter import MobilityPatternAdapter


def _write_description(image_path: Path, text: str) -> None:
    """Create a text file next to ``image_path`` with the given ``text``."""
    desc_path = image_path.with_suffix(".txt")
    desc_path.write_text(text.strip() + "\n")


def generate_assets(output_base: Path) -> None:
    output_base.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Antenna coverage visualization
    # ------------------------------------------------------------------
    model = AntennaSelector()  # untrained model is sufficient for demo
    coverage_png = Path(plot_antenna_coverage(model, output_dir=str(output_base)))
    _write_description(
        coverage_png,
        "Coverage map illustrating which antenna serves each location using "
        "a dummy antenna selector model.",
    )

    # ------------------------------------------------------------------
    # Linear trajectory visualization
    # ------------------------------------------------------------------
    lin_model = MobilityPatternAdapter.get_mobility_model(
        "linear",
        ue_id="demo_linear",
        start_position=(0, 0, 0),
        end_position=(200, 100, 0),
        speed=5.0,
    )
    lin_points = MobilityPatternAdapter.generate_path_points(lin_model, duration=60, time_step=1.0)
    lin_mov = [{**p, "connected_to": "antenna_1"} for p in lin_points]
    lin_png = Path(
        plot_movement_trajectory(lin_mov, output_dir=str(output_base / "linear"))
    )
    _write_description(
        lin_png,
        "Linear movement path from (0,0) to (200,100) visualized over time.",
    )

    # ------------------------------------------------------------------
    # L-shaped trajectory visualization
    # ------------------------------------------------------------------
    l_model = MobilityPatternAdapter.get_mobility_model(
        "l_shaped",
        ue_id="demo_l_shaped",
        start_position=(0, 0, 0),
        corner_position=(100, 0, 0),
        end_position=(100, 100, 0),
        speed=5.0,
    )
    l_points = MobilityPatternAdapter.generate_path_points(l_model, duration=80, time_step=1.0)
    l_mov = [{**p, "connected_to": "antenna_1"} for p in l_points]
    l_png = Path(
        plot_movement_trajectory(l_mov, output_dir=str(output_base / "l_shaped"))
    )
    _write_description(
        l_png,
        "L-shaped movement with a 90-degree turn at the corner point.",
    )

    print("Generated assets:")
    for p in (coverage_png, lin_png, l_png):
        print(" -", p)


def main() -> None:
    base = REPO_ROOT / "presentation_assets"
    generate_assets(base)


if __name__ == "__main__":
    main()
