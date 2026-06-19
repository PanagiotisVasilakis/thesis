"""Load and score explicit-stay oracle ranker artifacts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import joblib
import numpy as np


MODEL_TYPE = "oracle_candidate_ranker_v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class OracleRankerArtifact:
    path: Path
    model: Any
    model_family: str
    feature_columns: tuple[str, ...]
    metadata: Mapping[str, Any]
    artifact_sha256: str

    def score_rows(self, rows: Sequence[Mapping[str, Any]]) -> list[float]:
        matrix = np.asarray(
            [[float(row[column]) for column in self.feature_columns] for row in rows],
            dtype=float,
        )
        return [float(value) for value in self.model.predict(matrix)]


def load_oracle_ranker_artifact(path: Path) -> OracleRankerArtifact:
    metadata_path = Path(f"{path}.meta.json")
    if not path.is_file() or not metadata_path.is_file():
        raise ValueError("oracle ranker artifact and metadata are required")
    payload = joblib.load(path)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    digest = sha256_file(path)
    if metadata.get("model_type") != MODEL_TYPE:
        raise ValueError("unsupported oracle ranker model_type")
    if metadata.get("model_sha256") != digest:
        raise ValueError("oracle ranker artifact hash mismatch")
    columns = tuple(str(item) for item in metadata.get("feature_columns") or [])
    if not columns or {"ue_id", "serving_cell", "action_cell"}.intersection(columns):
        raise ValueError("oracle ranker feature metadata is invalid")
    return OracleRankerArtifact(
        path=path,
        model=payload["selected_model"],
        model_family=str(metadata["selected_model_family"]),
        feature_columns=columns,
        metadata=metadata,
        artifact_sha256=digest,
    )
