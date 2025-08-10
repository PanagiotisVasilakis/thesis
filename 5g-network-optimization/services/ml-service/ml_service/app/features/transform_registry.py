"""Registry for feature transformation functions.

This module maintains two registries:

* ``_TRANSFORMS`` maps transform names to callables. It ships with a small
  collection of built-in transforms and can be extended dynamically via
  :func:`register_transform`.
* ``_FEATURE_TRANSFORMS`` maps feature names to callables.  These mappings are
  typically populated from configuration files (``features.yaml``) or
  programmatically through :func:`register_feature_transform`.

The :func:`apply_feature_transforms` helper applies all registered transforms to
an extracted feature dictionary.  Unknown features fall back to the identity
transform.
"""

from __future__ import annotations

from typing import Any, Callable, Dict
import importlib

# ---------------------------------------------------------------------------
# Transform function registry
# ---------------------------------------------------------------------------

_TRANSFORMS: Dict[str, Callable[[Any], Any]] = {}


def register_transform(name: str, func: Callable[[Any], Any]) -> None:
    """Register a raw transform function under ``name``.

    If a transform with the same name already exists it will be overwritten.
    """

    if not callable(func):  # pragma: no cover - defensive check
        raise TypeError("Transform must be callable")
    _TRANSFORMS[name] = func


# Built-in transforms available out of the box. These provide sensible defaults
# for numerical features but can be replaced or extended by the application.
register_transform("identity", lambda x: x)
register_transform("float", lambda x: float(x) if x is not None else 0.0)
register_transform("int", lambda x: int(x) if x is not None else 0)
register_transform(
    "bool",
    lambda x: bool(int(x)) if isinstance(x, str) else bool(x),
)


def resolve_transform(spec: str) -> Callable[[Any], Any]:
    """Return a transform callable for ``spec``.

    ``spec`` may be either the name of a previously registered transform or a
    fully qualified ``"module:function"`` path.  In the latter case the
    function is imported and registered automatically.
    """

    if spec in _TRANSFORMS:
        return _TRANSFORMS[spec]

    if "." in spec:
        module_path, func_name = spec.rsplit(".", 1)
        module = importlib.import_module(module_path)
        func = getattr(module, func_name)
        if not callable(func):  # pragma: no cover - defensive check
            raise TypeError(f"{spec} is not callable")
        register_transform(spec, func)
        return func

    raise KeyError(f"Unknown transform: {spec}")


# ---------------------------------------------------------------------------
# Feature -> transform registry
# ---------------------------------------------------------------------------

_FEATURE_TRANSFORMS: Dict[str, Callable[[Any], Any]] = {}


def register_feature_transform(
    feature_name: str, transform: str | Callable[[Any], Any]
) -> None:
    """Associate ``feature_name`` with a transform.

    ``transform`` may be a callable or a string understood by
    :func:`resolve_transform`.
    """

    if callable(transform):
        func = transform
    else:
        func = resolve_transform(transform)
    _FEATURE_TRANSFORMS[feature_name] = func


def get_feature_transform(feature_name: str) -> Callable[[Any], Any]:
    """Return the transform function for ``feature_name``.

    Features without a registered transform use the ``identity`` transform.
    """

    return _FEATURE_TRANSFORMS.get(feature_name, _TRANSFORMS["identity"])


def apply_feature_transforms(features: Dict[str, Any]) -> Dict[str, Any]:
    """Apply registered transforms to the ``features`` mapping in-place."""

    for name, func in _FEATURE_TRANSFORMS.items():
        if name in features:
            try:
                features[name] = func(features[name])
            except Exception:  # pragma: no cover - ignore transformation errors
                pass
    return features


def clear_feature_transforms() -> None:
    """Remove all feature-level transform registrations."""

    _FEATURE_TRANSFORMS.clear()
