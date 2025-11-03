"""Lightweight compatibility layer for optional Feast dependency.

The project primarily depends on Feast for feature-store integration. The
thesis-focused test suite, however, should remain runnable even when Feast is
not installed (for example on CI runners or developer laptops that only need
the ML services).  This module attempts to import the real Feast classes and
falls back to small, behavioural stubs that satisfy the expectations of the
repository's utilities and tests.
"""

from __future__ import annotations

from typing import Iterable, Sequence

try:  # pragma: no cover - exercised indirectly when Feast is available
    from feast import Entity, FeatureView, Field, FileSource
    from feast.types import Float32, String, ValueType

    FEAST_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - executed during local tests
    FEAST_AVAILABLE = False

    class _FeastTypePlaceholder:
        """Small stand-in providing the minimal dtype interface used in tests."""

        def __init__(self, name: str) -> None:
            self._name = name

        def __repr__(self) -> str:
            return f"FeastTypePlaceholder({self._name})"

        def to_value_type(self) -> str:
            return self._name

    class Field:  # type: ignore[override]
        """Subset of :class:`feast.Field` needed for repository helpers."""

        def __init__(self, name: str, dtype: object) -> None:
            self.name = name
            self.dtype = dtype

        def __repr__(self) -> str:
            return f"Field(name={self.name!r}, dtype={self.dtype!r})"

    class Entity:  # type: ignore[override]
        """Minimal :class:`feast.Entity` approximation for tests."""

        def __init__(
            self,
            name: str,
            join_keys: Sequence[str] | None = None,
            description: str | None = None,
            value_type: object | None = None,
        ) -> None:
            self.name = name
            self.join_keys = list(join_keys or [])
            self.description = description or ""
            self.value_type = value_type

        def __repr__(self) -> str:
            return (
                "Entity("
                f"name={self.name!r}, join_keys={self.join_keys!r}, "
                f"value_type={self.value_type!r})"
            )

    class FileSource:  # type: ignore[override]
        """Simplified :class:`feast.FileSource` representation."""

        def __init__(
            self,
            path: str,
            timestamp_field: str | None = None,
            description: str | None = None,
        ) -> None:
            self.path = path
            self.timestamp_field = timestamp_field
            self.description = description or ""

        def __repr__(self) -> str:
            return (
                "FileSource("
                f"path={self.path!r}, timestamp_field={self.timestamp_field!r})"
            )

    class FeatureView:  # type: ignore[override]
        """Store initialisation arguments for test assertions."""

        def __init__(
            self,
            name: str,
            entities: Sequence[Entity] | None = None,
            ttl=None,
            schema=None,
            online: bool | None = None,
            source: FileSource | None = None,
            description: str | None = None,
        ) -> None:
            self.name = name
            self.entities = list(entities or [])
            self.ttl = ttl
            self.schema = schema
            self.online = bool(online)
            self.source = source
            self.description = description or ""

        def __repr__(self) -> str:
            return f"FeatureView(name={self.name!r})"

    class _ValueTypePlaceholder:
        """Expose the attributes accessed by the repository (STRING)."""

        def __init__(self) -> None:
            self.STRING = _FeastTypePlaceholder("ValueType.STRING")

        def __iter__(self) -> Iterable[object]:  # pragma: no cover - debug helper
            yield self.STRING

    Float32 = _FeastTypePlaceholder("Float32")
    String = _FeastTypePlaceholder("String")
    ValueType = _ValueTypePlaceholder()

__all__ = [
    "Entity",
    "FeatureView",
    "Field",
    "FileSource",
    "Float32",
    "String",
    "ValueType",
    "FEAST_AVAILABLE",
]

