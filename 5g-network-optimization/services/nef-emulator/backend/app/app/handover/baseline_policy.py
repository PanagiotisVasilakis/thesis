"""Bridge the shared NEF runtime to the baseline-service A3 policies.

This module does not implement A3 logic. It only makes the service-level
``handover-baseline-service`` package importable to the existing NEF process
and adapts NEF feature vectors into the package's typed policy input.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, Optional


BASELINE_HANDOVER_MODES = {"fixed_a3_baseline", "tuned_a3_baseline"}
_BASELINE_PATH_ENV = "HANDOVER_BASELINE_SERVICE_PATH"
_TUNED_CONFIG_ENV = "TUNED_A3_CONFIG_PATH"


class BaselinePolicyError(RuntimeError):
    """Raised when a baseline policy cannot be loaded or evaluated safely."""


def ensure_baseline_service_importable() -> Path:
    """Add the baseline service package path to ``sys.path`` if needed."""
    for candidate in _candidate_service_paths():
        package_dir = candidate / "handover_baseline"
        if package_dir.is_dir():
            service_path = str(candidate)
            if service_path not in sys.path:
                sys.path.insert(0, service_path)
            return candidate

    searched = ", ".join(str(path) for path in _candidate_service_paths())
    raise BaselinePolicyError(
        "handover-baseline-service package is not available to the NEF runtime; "
        f"set {_BASELINE_PATH_ENV} or mount the service package. Searched: {searched}"
    )


class BaselinePolicyManager:
    """Lazy policy loader for live NEF baseline modes."""

    def __init__(self) -> None:
        self._policies: Dict[str, Any] = {}

    def reset(self, ue_id: Optional[str] = None) -> None:
        """Reset cached policy state without dropping selected parameters."""
        for policy in self._policies.values():
            reset = getattr(policy, "reset", None)
            if callable(reset):
                reset(ue_id)

    def decide(
        self,
        *,
        mode: str,
        ue_id: str,
        feature_vector: Mapping[str, Any],
        timestamp_s: float,
        step_index: Optional[int] = None,
    ) -> Any:
        """Evaluate one baseline policy decision against a NEF feature vector."""
        if mode not in BASELINE_HANDOVER_MODES:
            raise BaselinePolicyError(f"unsupported baseline policy mode: {mode}")

        ensure_baseline_service_importable()
        from handover_baseline import snapshot_from_feature_vector

        policy = self._policy_for_mode(mode)
        snapshot = snapshot_from_feature_vector(
            feature_vector,
            ue_id=ue_id,
            timestamp_s=timestamp_s,
            step_index=step_index,
        )
        return policy.decide(snapshot)

    def _policy_for_mode(self, mode: str) -> Any:
        if mode == "fixed_a3_baseline":
            return self._policies.setdefault(mode, _build_fixed_policy())

        if mode == "tuned_a3_baseline":
            config_path = _require_tuned_config_path()
            cache_key = f"{mode}:{config_path}"
            if cache_key not in self._policies:
                self._policies[cache_key] = _build_tuned_live_policy(config_path)
            return self._policies[cache_key]

        raise BaselinePolicyError(f"unsupported baseline policy mode: {mode}")


def _build_fixed_policy() -> Any:
    ensure_baseline_service_importable()
    from handover_baseline import FixedA3Policy

    return FixedA3Policy()


def _build_tuned_live_policy(config_path: Path) -> Any:
    """Build a tuned live policy from a real saved selected-parameter config."""
    ensure_baseline_service_importable()
    from handover_baseline import A3Parameters, FixedA3Policy

    payload = _load_json_object(config_path)
    raw_parameters = payload.get("selected_parameters") or payload.get("parameters")
    if not isinstance(raw_parameters, Mapping):
        raise BaselinePolicyError(
            f"tuned A3 config must contain selected_parameters: {config_path}"
        )

    allowed = {
        "a3_offset_db",
        "hysteresis_db",
        "time_to_trigger_s",
        "cooldown_s",
        "minimum_neighbour_rsrp_dbm",
    }
    parameters = {
        key: value
        for key, value in raw_parameters.items()
        if key in allowed
    }
    missing = {
        "a3_offset_db",
        "hysteresis_db",
        "time_to_trigger_s",
        "cooldown_s",
    } - set(parameters)
    if missing:
        raise BaselinePolicyError(
            "tuned A3 config selected_parameters missing required keys: "
            + ", ".join(sorted(missing))
        )

    try:
        selected_parameters = A3Parameters(**parameters)
    except (TypeError, ValueError) as exc:
        raise BaselinePolicyError(
            f"tuned A3 config selected_parameters are invalid: {config_path}"
        ) from exc

    return FixedA3Policy(
        selected_parameters,
        name="tuned_a3_baseline",
    )


def _load_json_object(path: Path) -> Mapping[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BaselinePolicyError(f"tuned A3 config does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise BaselinePolicyError(f"tuned A3 config is not valid JSON: {path}") from exc

    if not isinstance(data, Mapping):
        raise BaselinePolicyError(f"tuned A3 config must be a JSON object: {path}")
    return data


def _require_tuned_config_path() -> Path:
    raw_path = os.getenv(_TUNED_CONFIG_ENV)
    if not raw_path:
        raise BaselinePolicyError(
            f"tuned_a3_baseline requires {_TUNED_CONFIG_ENV} to point to a "
            "saved non-ML tuning result; no tuned parameters will be fabricated."
        )
    return Path(raw_path).expanduser().resolve()


def _candidate_service_paths() -> list[Path]:
    candidates: list[Path] = []
    env_path = os.getenv(_BASELINE_PATH_ENV)
    if env_path:
        candidates.append(Path(env_path).expanduser().resolve())

    candidates.append(Path("/opt/handover-baseline-service"))

    current = Path(__file__).resolve()
    for parent in current.parents:
        if parent.name == "services":
            candidates.append(parent / "handover-baseline-service")
        elif parent.name == "5g-network-optimization":
            candidates.append(parent / "services" / "handover-baseline-service")

    unique: list[Path] = []
    seen = set()
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            unique.append(candidate)
            seen.add(key)
    return unique
