#!/usr/bin/env python3
"""Capture canonical measurement traces from the existing NEF feature endpoint."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

if __package__ in {None, ""}:  # pragma: no cover - direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.policy_comparison.nef_trace import capture_nef_trace_records
from scripts.policy_comparison.trace_io import write_trace_jsonl


def parse_ue_ids(raw_values: Sequence[str]) -> list[str]:
    ue_ids: list[str] = []
    for raw in raw_values:
        ue_ids.extend(item.strip() for item in raw.split(",") if item.strip())
    if not ue_ids:
        raise ValueError("at least one --ue-id is required")
    if len(set(ue_ids)) != len(ue_ids):
        raise ValueError("duplicate UE IDs are not allowed")
    return ue_ids


def ensure_fresh_file(path: Path) -> None:
    if path.exists() and path.stat().st_size > 0:
        raise ValueError(f"output trace already exists and is not empty: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)


def resolve_nef_url(explicit: str | None) -> str:
    if explicit:
        return explicit
    nef_url = os.environ.get("NEF_URL")
    if nef_url:
        return nef_url
    scheme = os.environ.get("NEF_SCHEME")
    host = os.environ.get("NEF_HOST")
    port = os.environ.get("NEF_PORT")
    if scheme and host and port:
        return f"{scheme}://{host}:{port}"
    raise ValueError(
        "NEF URL is required. Use --nef-url, NEF_URL, or NEF_SCHEME/NEF_HOST/NEF_PORT."
    )


def run(args: argparse.Namespace) -> int:
    output = Path(args.output)
    ensure_fresh_file(output)
    metadata_path = output.with_suffix(output.suffix + ".metadata.json")
    ensure_fresh_file(metadata_path)

    ue_ids = parse_ue_ids(args.ue_id)
    records = capture_nef_trace_records(
        nef_url=resolve_nef_url(args.nef_url),
        ue_ids=ue_ids,
        scenario=args.scenario,
        seed=args.seed,
        samples=args.samples,
        interval_s=args.interval_s,
        timeout_s=args.timeout_s,
        topology_hash=args.topology_hash,
        topology_json=Path(args.topology_json) if args.topology_json else None,
    )
    write_trace_jsonl(records, output)

    metadata = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scenario": args.scenario,
        "seed": args.seed,
        "samples": args.samples,
        "interval_s": args.interval_s,
        "ue_ids": ue_ids,
        "record_count": len(records),
        "source": "existing_nef_feature_endpoint",
        "endpoint": "/api/v1/ml/state/{ue_id}",
        "no_policy_decisions_captured": True,
        "no_handover_applied": True,
    }
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    print(f"Captured {len(records)} records to {output}")
    print(f"Metadata written to {metadata_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Capture policy-free canonical trace records from the existing "
            "NEF /api/v1/ml/state/{ue_id} endpoint."
        )
    )
    parser.add_argument("--scenario", required=True, help="Scenario name, e.g. highway.")
    parser.add_argument("--seed", required=True, type=int, help="Trace seed label.")
    parser.add_argument(
        "--ue-id",
        action="append",
        required=True,
        help="UE ID to sample. Can be repeated or comma-separated.",
    )
    parser.add_argument("--output", required=True, help="Fresh trace JSONL output path.")
    parser.add_argument("--nef-url", help="NEF base URL. Falls back to NEF_URL.")
    parser.add_argument(
        "--samples",
        type=int,
        default=1,
        help="Number of samples per UE. Default: 1.",
    )
    parser.add_argument(
        "--interval-s",
        type=float,
        default=1.0,
        help="Seconds between samples. Default: 1.0.",
    )
    parser.add_argument(
        "--timeout-s",
        type=float,
        default=5.0,
        help="HTTP timeout per NEF feature-vector request. Default: 5.0.",
    )
    parser.add_argument("--topology-hash", help="Existing topology hash label.")
    parser.add_argument("--topology-json", help="Topology JSON file to hash.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except Exception as exc:  # noqa: BLE001 - command should fail visibly
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
