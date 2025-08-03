"""Feature range specification loading and validation utilities."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict
import yaml

# Default path to the feature specification file
_FEATURE_SPEC_PATH = Path(__file__).with_name("features.yaml")


def _load_specs(path: Path = _FEATURE_SPEC_PATH) -> Dict[str, Dict[str, Any]]:
    """Load feature specifications from YAML configuration.

    The configuration is expected to contain a ``base_features`` list where
    each element may define ``min``/``max`` numeric bounds or a set of
    ``categories`` for categorical features.
    """
    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    specs: Dict[str, Dict[str, Any]] = {}
    for item in data.get("base_features", []):
        name = item.get("name")
        if not name:
            continue
        spec: Dict[str, Any] = {}
        if "min" in item:
            try:
                spec["min"] = float(item["min"])
            except (TypeError, ValueError):
                pass
        if "max" in item:
            try:
                spec["max"] = float(item["max"])
            except (TypeError, ValueError):
                pass
        if "categories" in item:
            spec["categories"] = set(item["categories"])
        if spec:
            specs[str(name)] = spec
    return specs


# Load specifications at import time for reuse
FEATURE_SPECS: Dict[str, Dict[str, Any]] = _load_specs()


def get_feature_specs() -> Dict[str, Dict[str, Any]]:
    """Return a copy of the loaded feature specifications."""
    return FEATURE_SPECS.copy()


def validate_feature_ranges(features: Dict[str, Any]) -> None:
    """Validate feature values against configured ranges or categories.

    Args:
        features: Mapping of feature names to their values.

    Raises:
        ValueError: If any feature lies outside its allowed range or category.
    """
    violations = []
    for name, spec in FEATURE_SPECS.items():
        if name not in features:
            continue
        value = features[name]
        if "categories" in spec:
            if value not in spec["categories"]:
                violations.append(f"{name}={value} not in {sorted(spec['categories'])}")
            continue
        # Numeric range validation
        try:
            val = float(value)
        except (TypeError, ValueError):
            violations.append(f"{name}={value} is not numeric")
            continue
        if "min" in spec and val < spec["min"]:
            violations.append(f"{name}<{spec['min']}")
        if "max" in spec and val > spec["max"]:
            violations.append(f"{name}>{spec['max']}")
    if violations:
        raise ValueError("Out-of-range feature values: " + ", ".join(violations))
