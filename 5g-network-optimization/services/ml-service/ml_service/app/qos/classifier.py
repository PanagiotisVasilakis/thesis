"""QoS service classifier for multi-objective scoring and compliance checks."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Mapping, Optional, Tuple

import yaml


_DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "features.yaml"
)


@dataclass(frozen=True)
class MetricDefinition:
    """Configuration describing how a QoS metric should be evaluated."""

    weight: float
    objective: str
    threshold: float
    tolerance: float = 0.0
    mandatory: bool = True

    def normalized_objective(self) -> str:
        obj = self.objective.lower().strip()
        if obj not in {"min", "max"}:
            raise ValueError(f"Unsupported objective '{self.objective}'")
        return obj


@dataclass(frozen=True)
class MetricDefaults:
    """Optional default weight and threshold hints for a metric."""

    weight: Optional[float] = None
    threshold: Optional[float] = None

    def as_dict(self) -> Dict[str, float]:
        data: Dict[str, float] = {}
        if self.weight is not None:
            data["weight"] = float(self.weight)
        if self.threshold is not None:
            data["threshold"] = float(self.threshold)
        return data


@dataclass(frozen=True)
class QoSProfile:
    metrics: Dict[str, MetricDefinition]
    minimum_score: Optional[float]
    metric_defaults: Dict[str, MetricDefaults]


class QoSServiceClassifier:
    """Compute QoS scores and compliance for configured service profiles."""

    def __init__(
        self,
        config_path: Optional[str] = None,
        default_service: str = "default",
    ) -> None:
        self._config_path = Path(config_path) if config_path else _DEFAULT_CONFIG_PATH
        self._profiles = self._load_profiles(self._config_path)
        self._default_service = default_service
        if default_service not in self._profiles:
            if self._profiles:
                self._default_service = next(iter(self._profiles))
            else:
                raise ValueError(
                    "No QoS profiles available. Please configure 'qos_profiles' entries."
                )

    @staticmethod
    def _load_profiles(path: Path) -> Dict[str, QoSProfile]:
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        raw_profiles = data.get("qos_profiles", {})
        profiles: Dict[str, QoSProfile] = {}
        for service, raw in raw_profiles.items():
            metrics = raw.get("metrics", {})
            metric_defs: Dict[str, MetricDefinition] = {}
            for metric_name, cfg in metrics.items():
                try:
                    weight = float(cfg.get("weight", 0.0))
                except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
                    raise ValueError(
                        f"Invalid weight for metric '{metric_name}' in '{service}'"
                    ) from exc
                threshold = float(cfg.get("threshold", 0.0))
                objective = str(cfg.get("objective", "max")).lower()
                tolerance = float(cfg.get("tolerance", 0.0))
                mandatory = bool(cfg.get("mandatory", True))
                metric_defs[metric_name] = MetricDefinition(
                    weight=weight,
                    objective=objective,
                    threshold=threshold,
                    tolerance=tolerance,
                    mandatory=mandatory,
                )
            defaults_cfg = raw.get("metric_defaults", {})
            metric_defaults: Dict[str, MetricDefaults] = {}
            for metric_name, cfg in defaults_cfg.items():
                weight_val = cfg.get("weight")
                threshold_val = cfg.get("threshold")
                try:
                    weight_default = (
                        float(weight_val) if weight_val is not None else None
                    )
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        f"Invalid default weight for metric '{metric_name}' in '{service}'"
                    ) from exc
                try:
                    threshold_default = (
                        float(threshold_val) if threshold_val is not None else None
                    )
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        f"Invalid default threshold for metric '{metric_name}' in '{service}'"
                    ) from exc
                metric_defaults[metric_name] = MetricDefaults(
                    weight=weight_default, threshold=threshold_default
                )
            minimum_score = raw.get("minimum_score")
            profiles[service] = QoSProfile(
                metrics=metric_defs,
                minimum_score=(
                    float(minimum_score) if minimum_score is not None else None
                ),
                metric_defaults=metric_defaults,
            )
        return profiles

    def available_services(self) -> Iterable[str]:
        return self._profiles.keys()

    def get_metric_defaults(
        self, service_type: Optional[str] = None
    ) -> Dict[str, Dict[str, float]]:
        """Return configured default weights/thresholds for a service type."""

        profile = self._get_profile(service_type)
        return {
            name: defaults.as_dict() for name, defaults in profile.metric_defaults.items()
        }

    def _get_profile(self, service_type: Optional[str]) -> QoSProfile:
        if service_type and service_type in self._profiles:
            return self._profiles[service_type]
        if self._default_service not in self._profiles:
            raise ValueError(f"Default service '{self._default_service}' is not configured")
        return self._profiles[self._default_service]

    def _normalize_weights(self, metrics: Mapping[str, MetricDefinition]) -> Dict[str, float]:
        total = sum(max(0.0, metric.weight) for metric in metrics.values())
        if total <= 0:
            raise ValueError("Metric weights must sum to a positive value")
        return {name: max(0.0, metric.weight) / total for name, metric in metrics.items()}

    @staticmethod
    def _normalize_metric(value: float, metric: MetricDefinition) -> float:
        objective = metric.normalized_objective()
        threshold = metric.threshold
        if objective == "max":
            if threshold <= 0:
                return 1.0 if value >= threshold else 0.0
            ratio = value / threshold
            return max(0.0, min(ratio, 1.0))
        # objective == "min"
        if value <= 0:
            return 1.0
        if threshold <= 0:
            return 1.0 if value <= threshold else max(0.0, min(threshold / value, 1.0))
        ratio = threshold / value
        return max(0.0, min(ratio, 1.0))

    @staticmethod
    def _check_compliance(value: float, metric: MetricDefinition) -> bool:
        objective = metric.normalized_objective()
        tolerance = metric.tolerance
        threshold = metric.threshold
        if objective == "max":
            return value + tolerance >= threshold
        return value <= threshold + tolerance

    def score(
        self, service_type: Optional[str], metrics: Mapping[str, float]
    ) -> Tuple[float, Dict[str, Dict[str, float]]]:
        profile = self._get_profile(service_type)
        metric_defs = profile.metrics
        if not metric_defs:
            raise ValueError(f"No QoS metrics configured for service '{service_type}'")
        missing = [name for name in metric_defs if name not in metrics]
        if missing:
            raise ValueError(f"Missing metrics for scoring: {', '.join(sorted(missing))}")
        weights = self._normalize_weights(metric_defs)
        score = 0.0
        breakdown: Dict[str, Dict[str, float]] = {}
        for name, metric_def in metric_defs.items():
            value = float(metrics[name])
            normalized = self._normalize_metric(value, metric_def)
            weight = weights[name]
            score += normalized * weight
            breakdown[name] = {
                "value": value,
                "weight": weight,
                "normalized_score": normalized,
                "threshold": metric_def.threshold,
                "objective": metric_def.normalized_objective(),
            }
        return score, breakdown

    def evaluate_compliance(
        self,
        service_type: Optional[str],
        metrics: Mapping[str, float],
        score: Optional[float] = None,
    ) -> Tuple[bool, Dict[str, Dict[str, float]]]:
        profile = self._get_profile(service_type)
        metric_defs = profile.metrics
        missing = [name for name in metric_defs if name not in metrics]
        if missing:
            raise ValueError(f"Missing metrics for compliance: {', '.join(sorted(missing))}")
        results: Dict[str, Dict[str, float]] = {}
        compliant = True
        for name, metric_def in metric_defs.items():
            value = float(metrics[name])
            meets = self._check_compliance(value, metric_def)
            results[name] = {
                "value": value,
                "threshold": metric_def.threshold,
                "objective": metric_def.normalized_objective(),
                "tolerance": metric_def.tolerance,
                "compliant": meets,
            }
            if not meets and metric_def.mandatory:
                compliant = False
        minimum_score = profile.minimum_score
        if minimum_score is not None:
            if score is None:
                score, _ = self.score(service_type, metrics)
            meets = score >= minimum_score
            results["_minimum_score"] = {
                "value": score,
                "threshold": float(minimum_score),
                "objective": "min_score",
                "compliant": meets,
            }
            if not meets:
                compliant = False
        return compliant, results

    def assess(
        self, service_type: Optional[str], metrics: Mapping[str, float]
    ) -> Dict[str, object]:
        score, breakdown = self.score(service_type, metrics)
        compliant, compliance_details = self.evaluate_compliance(
            service_type, metrics, score
        )
        return {
            "service_type": service_type or self._default_service,
            "score": score,
            "breakdown": breakdown,
            "compliant": compliant,
            "compliance_details": compliance_details,
        }

