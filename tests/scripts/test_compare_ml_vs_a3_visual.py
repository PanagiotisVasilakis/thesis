"""Tests for ML vs A3 comparison tooling analytics helpers."""

import pandas as pd
import pytest

from scripts.compare_ml_vs_a3_visual import (
    ComparisonVisualizer,
    _derive_metrics_from_events,
)


def _event_payload(**overrides):
    base = {
        "ue_id": "ue-1",
        "event_type": "applied",
        "timestamp": "2024-01-01T12:00:00",
        "handover_result": {"from": "antenna_1", "to": "antenna_2"},
        "observed_qos": {"latest": {"latency_ms": 12.0}},
        "qos_compliance": {"passed": True, "service_type": "embb", "violations": []},
        "ml_confidence": 0.9,
    }
    base.update(overrides)
    return base


def test_derive_metrics_tracks_skips_and_per_ue():
    events = [
        _event_payload(),
        _event_payload(
            ue_id="ue-1",
            timestamp="2024-01-01T12:00:05",
            handover_result={"from": "antenna_2", "to": "antenna_3"},
            qos_compliance={
                "passed": False,
                "service_type": "embb",
                "violations": [{"metric": "latency", "delta": 4.2}],
            },
            ml_confidence=0.6,
        ),
        {
            "ue_id": "ue-2",
            "event_type": "skipped",
            "timestamp": "2024-01-01T12:00:06",
            "outcome": "already_connected",
        },
    ]

    derived = _derive_metrics_from_events(events, mode="ml", pingpong_window=2.0)

    assert derived["total_handovers"] == 2.0
    assert derived["skipped_handovers"] == 1.0
    assert derived["qos_compliance_ok"] == 1.0
    assert derived["qos_compliance_failed"] == 1.0
    assert derived["qos_violations_by_metric"]["latency"] == 1.0
    assert derived["handover_events_by_type"]["skipped"] == 1.0
    assert derived["skipped_by_outcome"]["already_connected"] == 1.0
    per_ue = derived["handover_events_per_ue"]
    assert per_ue["ue-1"]["applied"] == 2.0
    assert per_ue["ue-2"]["skipped"] == 1.0
    assert derived["p50_handover_interval"] == 5.0
    assert derived["p95_handover_interval"] == 5.0
    assert derived["avg_confidence"] == pytest.approx(0.75)
    assert derived["dwell_time_samples"] == [5.0]
    assert derived["latency_samples"] == [12.0]
    assert derived["confidence_samples"] == [0.9, 0.6]


def test_export_per_ue_report_contains_skip_rates(tmp_path):
    output_dir = tmp_path / "reports"
    visualizer = ComparisonVisualizer(output_dir=str(output_dir))

    ml_metrics = {
        "handover_events_per_ue": {
            "ue-1": {"applied": 1.0, "skipped": 4.0},
            "ue-2": {"applied": 3.0, "skipped": 1.0},
        }
    }
    a3_metrics = {
        "handover_events_per_ue": {
            "ue-1": {"applied": 2.0, "skipped": 0.0},
        }
    }

    csv_path = visualizer.export_per_ue_report(ml_metrics, a3_metrics)
    df = pd.read_csv(csv_path)

    ue1 = df[df["ue_id"] == "ue-1"].set_index("mode")
    assert float(ue1.loc["ML", "skip_rate_pct"]) == 80.0
    assert int(ue1.loc["A3", "skipped"]) == 0


def test_export_skip_reason_report_summarizes_shares(tmp_path):
    output_dir = tmp_path / "reports"
    visualizer = ComparisonVisualizer(output_dir=str(output_dir))

    ml_metrics = {
        "skipped_by_outcome": {
            "already_connected": 9,
            "recent_handover": 1,
        }
    }

    csv_path = visualizer.export_skip_reason_report(ml_metrics)
    df = pd.read_csv(csv_path)

    totals = {row.outcome: row.share_pct for row in df.itertuples()}
    assert totals["already_connected"] == pytest.approx(90.0)
    assert totals["recent_handover"] == pytest.approx(10.0)
