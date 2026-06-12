"""JSONL trace I/O for canonical policy comparison records."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, List, Mapping, Sequence

from .schemas import MeasurementTraceRecord, PolicyDecisionRecord


def read_trace_jsonl(path: Path) -> List[MeasurementTraceRecord]:
    """Read canonical measurement trace records from JSONL."""
    records: List[MeasurementTraceRecord] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
                records.append(MeasurementTraceRecord.from_dict(payload))
            except Exception as exc:  # noqa: BLE001 - include line number
                raise ValueError(f"invalid trace record at {path}:{line_number}: {exc}") from exc
    return records


def write_trace_jsonl(records: Sequence[MeasurementTraceRecord], path: Path) -> None:
    """Write canonical measurement trace records to JSONL."""
    if not records:
        raise ValueError("cannot write an empty measurement trace")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record.to_dict(), sort_keys=True) + "\n")


def write_decisions_jsonl(records: Sequence[PolicyDecisionRecord], path: Path) -> None:
    """Write policy decision records to JSONL."""
    if not records:
        raise ValueError("cannot write an empty decision log")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record.to_dict(), sort_keys=True) + "\n")


def read_decisions_jsonl(path: Path) -> List[PolicyDecisionRecord]:
    """Read policy decision records from JSONL."""
    decisions: List[PolicyDecisionRecord] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                decisions.append(PolicyDecisionRecord.from_dict(json.loads(stripped)))
            except Exception as exc:  # noqa: BLE001 - include line number
                raise ValueError(
                    f"invalid decision record at {path}:{line_number}: {exc}"
                ) from exc
    return decisions


def stable_json_hash(payload: Mapping[str, Any] | Iterable[Any]) -> str:
    """Return a deterministic SHA-256 hash for JSON-serializable metadata."""
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def topology_hash_from_path(path: Path) -> str:
    """Hash a topology JSON file using canonical sorted JSON."""
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, dict) and isinstance(payload.get("metadata"), dict):
        payload["metadata"].pop("created_at", None)
    return stable_json_hash(payload)
