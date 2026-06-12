"""Reusable tuned A3 config helpers for offline replay and live NEF mode."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, Tuple


REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE_SERVICE_PATH = (
    REPO_ROOT / "5g-network-optimization" / "services" / "handover-baseline-service"
)
REQUIRED_SELECTED_PARAMETER_KEYS = {
    "a3_offset_db",
    "hysteresis_db",
    "time_to_trigger_s",
    "cooldown_s",
}


def ensure_baseline_service_importable() -> None:
    if not BASELINE_SERVICE_PATH.exists():
        raise ValueError(f"baseline service path is missing: {BASELINE_SERVICE_PATH}")
    service_path = str(BASELINE_SERVICE_PATH)
    if service_path not in sys.path:
        sys.path.insert(0, service_path)


def load_tuned_a3_config(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"tuned A3 config does not exist: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"tuned A3 config must be a JSON object: {path}")
    params = data.get("selected_parameters")
    if not isinstance(params, dict):
        raise ValueError("tuned A3 config must contain selected_parameters")
    missing = sorted(REQUIRED_SELECTED_PARAMETER_KEYS.difference(params))
    if missing:
        raise ValueError(
            "tuned A3 selected_parameters missing required keys: " + ", ".join(missing)
        )
    return data


def selected_parameters_from_config(data: Mapping[str, Any]):
    ensure_baseline_service_importable()
    from handover_baseline import A3Parameters  # type: ignore[import-not-found]

    params = data.get("selected_parameters")
    if not isinstance(params, Mapping):
        raise ValueError("tuned A3 config must contain selected_parameters")
    return A3Parameters(
        a3_offset_db=float(params["a3_offset_db"]),
        hysteresis_db=float(params["hysteresis_db"]),
        time_to_trigger_s=float(params["time_to_trigger_s"]),
        cooldown_s=float(params["cooldown_s"]),
        minimum_neighbour_rsrp_dbm=(
            None
            if params.get("minimum_neighbour_rsrp_dbm") is None
            else float(params["minimum_neighbour_rsrp_dbm"])
        ),
    )


def build_tuned_policy_from_config(path: Path) -> Tuple[Any, Dict[str, Any]]:
    """Build a tuned A3 policy from a real selected-parameters artifact."""
    ensure_baseline_service_importable()
    from handover_baseline import TunedA3Policy  # type: ignore[import-not-found]
    from handover_baseline.tuned_a3_policy import A3TuningResult  # type: ignore[import-not-found]

    data = load_tuned_a3_config(path)
    if "selected_score" not in data:
        raise ValueError("tuned A3 config must contain selected_score")
    if not data.get("objective"):
        raise ValueError("tuned A3 config must contain objective")
    evaluated = data.get("evaluated_configuration_scores") or data.get(
        "evaluated_configurations"
    )
    if not isinstance(evaluated, list) or not evaluated:
        raise ValueError("tuned A3 config must preserve evaluated configuration scores")
    selected_parameters = selected_parameters_from_config(data)
    selected_score = float(data["selected_score"])
    objective = str(data["objective"])
    tuning_result = A3TuningResult(
        selected_parameters=selected_parameters,
        selected_score=selected_score,
        evaluated_configurations=[],
        objective=objective,
    )
    return TunedA3Policy(tuning_result), data
