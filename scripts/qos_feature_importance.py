#!/usr/bin/env python3
"""Compute feature importances for the QoS-aware antenna selector."""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "5g-network-optimization" / "services"))
sys.path.insert(0, str(REPO_ROOT / "5g-network-optimization" / "services" / "ml-service"))

from ml_service.app.models.lightgbm_selector import LightGBMSelector


@dataclass(frozen=True)
class DatasetConfig:
    samples: int = 1200
    neighbor_count: int = 8
    seed: int = 42


DEFAULT_QOS_FEATURES: Dict[str, float] = {
    "service_type": 5,  # encoded later by model pipeline
    "service_priority": 5,
    "latency_ms": 45.0,
    "throughput_mbps": 180.0,
    "packet_loss_rate": 0.25,
    "latency_requirement_ms": 50.0,
    "throughput_requirement_mbps": 200.0,
    "jitter_ms": 5.0,
    "reliability_pct": 99.5,
}


def populate_synthetic_qos(sample: Dict[str, float | int | str], rng: random.Random) -> None:
    rsrp_current = float(sample.get("rsrp_current", -85.0))
    cell_load = float(sample.get("cell_load", 0.5))
    mobility = float(sample.get("speed", 5.0))

    quality = max(0.0, min(1.0, (rsrp_current + 120.0) / 55.0))
    load_penalty = min(1.5, cell_load * 1.6)
    mobility_penalty = min(1.0, mobility / 45.0)

    latency_req = 18.0 + (1.0 - quality) * 35.0 + load_penalty * 12.0
    throughput_req = 110.0 + quality * 130.0 - load_penalty * 40.0
    reliability_req = 97.5 + quality * 1.8 - load_penalty * 0.9

    observed_latency = latency_req * (1.0 + load_penalty * 0.18 + mobility_penalty * 0.12)
    throughput_factor = max(0.25, min(1.25, quality + 0.25 - load_penalty * 0.18))
    observed_throughput = throughput_req * throughput_factor
    observed_jitter = max(0.15, observed_latency * (0.018 + load_penalty * 0.035))
    observed_loss = min(20.0, (1.0 - quality + load_penalty * 0.2) * 5.0 * rng.uniform(0.8, 1.2))
    observed_reliability = max(0.0, 100.0 - observed_loss)

    sample["latency_requirement_ms"] = round(latency_req, 3)
    sample["throughput_requirement_mbps"] = round(max(15.0, throughput_req), 3)
    sample["reliability_pct"] = round(min(99.99, reliability_req), 4)
    sample["observed_latency_ms"] = round(observed_latency, 3)
    sample["observed_throughput_mbps"] = round(max(5.0, observed_throughput), 3)
    sample["observed_jitter_ms"] = round(observed_jitter, 4)
    sample["observed_packet_loss_rate"] = round(observed_loss, 4)
    sample["latency_delta_ms"] = round(observed_latency - latency_req, 3)
    sample["throughput_delta_mbps"] = round(observed_throughput - throughput_req, 3)
    sample["reliability_delta_pct"] = round(observed_reliability - reliability_req, 4)


def apply_qos_defaults(sample: Dict[str, float | int | str]) -> None:
    for key, value in DEFAULT_QOS_FEATURES.items():
        sample.setdefault(key, value)

    latency_req = float(sample.get("latency_requirement_ms", DEFAULT_QOS_FEATURES["latency_requirement_ms"]))
    throughput_req = float(sample.get("throughput_requirement_mbps", DEFAULT_QOS_FEATURES["throughput_requirement_mbps"]))
    reliability_req = float(sample.get("reliability_pct", DEFAULT_QOS_FEATURES["reliability_pct"]))

    latency_obs = float(sample.setdefault("observed_latency_ms", sample.get("latency_ms", latency_req)))
    throughput_obs = float(sample.setdefault("observed_throughput_mbps", sample.get("throughput_mbps", throughput_req)))
    jitter_obs = float(sample.setdefault("observed_jitter_ms", sample.get("jitter_ms", DEFAULT_QOS_FEATURES["jitter_ms"])))
    loss_obs = float(sample.setdefault("observed_packet_loss_rate", sample.get("packet_loss_rate", DEFAULT_QOS_FEATURES["packet_loss_rate"])))

    sample.setdefault("latency_delta_ms", latency_obs - latency_req)
    sample.setdefault("throughput_delta_mbps", throughput_obs - throughput_req)
    observed_reliability = max(0.0, 100.0 - loss_obs)
    sample.setdefault("reliability_delta_pct", observed_reliability - reliability_req)


def generate_training_dataset(cfg: DatasetConfig, use_qos_features: bool = True) -> List[Dict[str, float | int | str]]:
    rng = random.Random(cfg.seed)
    dataset: List[Dict[str, float | int | str]] = []

    for idx in range(cfg.samples):
        ue_id = f"ue_{idx:05d}"
        base_lat = (idx * 7.5) % 1000.0
        base_lon = (idx * 4.5) % 866.0
        speed = rng.uniform(0.5, 45.0)
        connected_idx = rng.randint(0, cfg.neighbor_count - 1)

        sample: Dict[str, float | int | str] = {
            "ue_id": ue_id,
            "latitude": base_lat,
            "longitude": base_lon,
            "speed": speed,
            "direction_x": math.cos(idx * 0.05),
            "direction_y": math.sin(idx * 0.05),
            "heading_change_rate": rng.uniform(0.0, 0.1),
            "path_curvature": rng.uniform(0.0, 0.05),
            "velocity": speed,
            "acceleration": rng.uniform(-0.5, 0.5),
            "cell_load": rng.uniform(0.1, 0.95),
            "handover_count": rng.randint(0, 5),
            "time_since_handover": rng.uniform(0.5, 60.0),
            "signal_trend": rng.uniform(-0.8, 0.8),
            "environment": rng.uniform(0.0, 1.0),
            "rsrp_stddev": rng.uniform(0.5, 3.5),
            "sinr_stddev": rng.uniform(0.2, 2.5),
            "altitude": rng.uniform(0.0, 120.0),
        }

        rsrp_base = -65.0 - rng.uniform(0.0, 15.0)
        sinr_base = 18.0 - rng.uniform(0.0, 6.0)

        rsrp_best = -float("inf")
        best_idx = 0
        for antenna_idx in range(cfg.neighbor_count):
            delta = rng.uniform(-6.0, 6.0)
            rsrp = rsrp_base + delta - antenna_idx * rng.uniform(0.5, 2.0)
            sinr = sinr_base + rng.uniform(-2.0, 2.0)
            rsrq = -9.0 + rng.uniform(-2.5, 2.5)
            load = rng.uniform(0.05, 0.95)

            key_suffix = antenna_idx + 1
            sample[f"rsrp_a{key_suffix}"] = rsrp
            sample[f"sinr_a{key_suffix}"] = sinr
            sample[f"rsrq_a{key_suffix}"] = rsrq
            sample[f"neighbor_cell_load_a{key_suffix}"] = load

            if rsrp > rsrp_best:
                rsrp_best = rsrp
                best_idx = antenna_idx

        sample["best_rsrp_diff"] = rsrp_base - rsrp_best
        sample["best_sinr_diff"] = sinr_base - sample[f"sinr_a{best_idx+1}"]
        sample["best_rsrq_diff"] = -10.0 - sample[f"rsrq_a{best_idx+1}"]

        sample["rsrp_current"] = sample[f"rsrp_a{connected_idx+1}"]
        sample["sinr_current"] = sample[f"sinr_a{connected_idx+1}"]
        sample["rsrq_current"] = sample[f"rsrq_a{connected_idx+1}"]
        sample["connected_to"] = f"antenna_{connected_idx+1}"
        sample["optimal_antenna"] = f"antenna_{best_idx+1}"

        if use_qos_features:
            populate_synthetic_qos(sample, rng)
        else:
            sample["latency_requirement_ms"] = DEFAULT_QOS_FEATURES["latency_requirement_ms"]
            sample["throughput_requirement_mbps"] = DEFAULT_QOS_FEATURES["throughput_requirement_mbps"]
            sample["reliability_pct"] = DEFAULT_QOS_FEATURES["reliability_pct"]
            sample["observed_latency_ms"] = sample["latency_requirement_ms"]
            sample["observed_throughput_mbps"] = sample["throughput_requirement_mbps"]
            sample["observed_jitter_ms"] = DEFAULT_QOS_FEATURES["jitter_ms"]
            sample["observed_packet_loss_rate"] = DEFAULT_QOS_FEATURES["packet_loss_rate"]
            sample["latency_delta_ms"] = 0.0
            sample["throughput_delta_mbps"] = 0.0
            sample["reliability_delta_pct"] = 0.0

        apply_qos_defaults(sample)
        dataset.append(sample)

    return dataset


def compute_feature_importance(cfg: DatasetConfig, *, use_qos_features: bool = True) -> Dict[str, object]:
    dataset = generate_training_dataset(cfg, use_qos_features=use_qos_features)
    selector = LightGBMSelector(neighbor_count=cfg.neighbor_count)
    training_metrics = selector.train(dataset)
    model = selector.model
    if model is None:
        raise RuntimeError("Model failed to train; selector.model is None")

    split_importance = getattr(model, "feature_importances_", None)
    booster = getattr(model, "booster_", None)

    if split_importance is None:
        raise RuntimeError("LightGBM model does not expose feature_importances_")

    feature_names = selector.feature_names
    if booster is not None:
        gain_importance = booster.feature_importance(importance_type="gain")
    else:
        gain_importance = split_importance

    importance_rows = []
    for name, gain, split in zip(feature_names, gain_importance, split_importance):
        importance_rows.append(
            {
                "feature": name,
                "gain": float(gain),
                "split": float(split),
            }
        )

    importance_rows.sort(key=lambda row: row["gain"], reverse=True)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": {
            "samples": cfg.samples,
            "neighbor_count": cfg.neighbor_count,
            "seed": cfg.seed,
            "use_qos_features": use_qos_features,
        },
        "training_metrics": training_metrics,
        "feature_importance": importance_rows,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compute QoS-aware feature importances")
    parser.add_argument("--samples", type=int, default=1200, help="Number of synthetic training samples")
    parser.add_argument("--neighbor-count", type=int, default=8, help="Number of neighbor antennas to model")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/qos_feature_importance.json"),
        help="Path to write the feature importance report (JSON)",
    )
    parser.add_argument(
        "--disable-qos",
        action="store_true",
        help="Generate dataset without QoS signals (for ablation studies)",
    )
    parser.add_argument(
        "--ablation",
        action="store_true",
        help="Run both QoS-enabled and QoS-disabled experiments and export comparison",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    cfg = DatasetConfig(samples=args.samples, neighbor_count=args.neighbor_count, seed=args.seed)

    if args.ablation:
        report_with = compute_feature_importance(cfg, use_qos_features=True)
        report_without = compute_feature_importance(cfg, use_qos_features=False)

        metrics_with = report_with["training_metrics"]
        metrics_without = report_without["training_metrics"]

        comparison = {
            "val_accuracy_with_qos": metrics_with.get("val_accuracy"),
            "val_accuracy_without_qos": metrics_without.get("val_accuracy"),
            "accuracy_delta": None,
        }
        if comparison["val_accuracy_with_qos"] is not None and comparison["val_accuracy_without_qos"] is not None:
            comparison["accuracy_delta"] = (
                comparison["val_accuracy_with_qos"] - comparison["val_accuracy_without_qos"]
            )

        output = {
            "with_qos": report_with,
            "without_qos": report_without,
            "comparison": comparison,
        }

        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(output, indent=2), encoding="utf-8")

        print("Ablation results written to", args.output)
        print("Top 5 features (with QoS):")
        for row in report_with["feature_importance"][:5]:
            print(f"  {row['feature']:<30} gain={row['gain']:.4f} split={row['split']:.1f}")
        print("Top 5 features (without QoS):")
        for row in report_without["feature_importance"][:5]:
            print(f"  {row['feature']:<30} gain={row['gain']:.4f} split={row['split']:.1f}")
        if comparison["accuracy_delta"] is not None:
            print(
                "Validation accuracy delta (with - without QoS):"
                f" {comparison['accuracy_delta']:+.4f}"
            )
        return 0

    use_qos = not args.disable_qos
    report = compute_feature_importance(cfg, use_qos_features=use_qos)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")

    label = "with QoS features" if use_qos else "without QoS features"
    print(f"Top 5 features by gain ({label}):")
    for row in report["feature_importance"][:5]:
        print(f"  {row['feature']:<30} gain={row['gain']:.4f} split={row['split']:.1f}")
    print(f"Report written to {args.output}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
