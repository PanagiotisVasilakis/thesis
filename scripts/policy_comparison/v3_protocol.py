"""Protocol-lock validation for untouched v3 final seeds."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


DEFAULT_PROTOCOL_PATH = Path("configs/thesis_v3_protocol.json")


def load_protocol(path: Path = DEFAULT_PROTOCOL_PATH) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("protocol_version") != "physical_handover_v3":
        raise ValueError("unexpected thesis v3 protocol version")
    return data


def require_capture_allowed(seed: int, protocol: Mapping[str, Any]) -> None:
    final_seeds = {int(item) for item in protocol.get("final_seeds") or []}
    if seed not in final_seeds:
        return
    if protocol.get("model_selection_frozen") is not True:
        raise ValueError("final-seed capture blocked until model selection is frozen")
    if protocol.get("final_results_unlocked") is not True:
        raise ValueError("final-seed capture blocked until the tuning gate unlocks final results")
    if not protocol.get("selected_model_artifact_sha256"):
        raise ValueError("final-seed capture requires a selected model artifact hash")
    if protocol.get("metric_version") != "v3_physical_qos_cost":
        raise ValueError("final-seed capture requires the frozen v3 metric")
