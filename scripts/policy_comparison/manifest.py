"""Reproducibility manifest helpers for comparison runs."""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence


@dataclass(frozen=True)
class ReproducibilityManifest:
    """Metadata needed to reproduce an offline or live comparison run."""

    created_at: str
    scenario: str
    seed: int
    duration_s: Optional[float]
    tick_interval_s: Optional[float]
    topology_hash: Optional[str]
    policies: Dict[str, Dict[str, Any]]
    git_commit: Optional[str]
    git_dirty: bool
    git_dirty_files: Sequence[str] = field(default_factory=tuple)
    notes: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def write_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True),
            encoding="utf-8",
        )


def build_reproducibility_manifest(
    *,
    scenario: str,
    seed: int,
    policies: Mapping[str, Mapping[str, Any]],
    duration_s: Optional[float] = None,
    tick_interval_s: Optional[float] = None,
    topology_hash: Optional[str] = None,
    repo_root: Path = Path("."),
    notes: Optional[Mapping[str, Any]] = None,
) -> ReproducibilityManifest:
    """Build a manifest without recording secrets or environment dumps."""
    status_lines = _git_status(repo_root)
    return ReproducibilityManifest(
        created_at=datetime.now(timezone.utc).isoformat(),
        scenario=scenario,
        seed=seed,
        duration_s=duration_s,
        tick_interval_s=tick_interval_s,
        topology_hash=topology_hash,
        policies={name: dict(params) for name, params in policies.items()},
        git_commit=_git_commit(repo_root),
        git_dirty=bool(status_lines),
        git_dirty_files=tuple(status_lines),
        notes=dict(notes or {}),
    )


def _git_commit(repo_root: Path) -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def _git_status(repo_root: Path) -> Sequence[str]:
    try:
        result = subprocess.run(
            ["git", "status", "--short"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return ()
    return tuple(line.strip() for line in result.stdout.splitlines() if line.strip())
