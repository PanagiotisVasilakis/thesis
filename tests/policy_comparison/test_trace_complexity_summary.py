import json

from scripts.policy_comparison.nef_trace import feature_vector_to_trace_record
from scripts.policy_comparison.summarize_trace_complexity import (
    main as trace_complexity_main,
    summarize_trace_records,
)
from scripts.policy_comparison.trace_io import write_trace_jsonl


def make_record(step, *, candidate_count):
    rsrp = {"A": -80.0}
    sinr = {"A": 10.0}
    for index in range(candidate_count):
        cell_id = chr(ord("B") + index)
        rsrp[cell_id] = -82.0 - index
        sinr[cell_id] = 8.0
    return feature_vector_to_trace_record(
        {
            "ue_id": "ue-1",
            "latitude": 37.0,
            "longitude": 23.0,
            "connected_to": "A",
            "neighbor_rsrp_dbm": rsrp,
            "neighbor_sinrs": sinr,
        },
        scenario="highway_dense",
        seed=51,
        step_index=step,
        timestamp_s=float(step),
    )


def test_trace_complexity_summary_counts_histogram_and_buckets():
    records = [
        make_record(0, candidate_count=0),
        make_record(1, candidate_count=1),
        make_record(2, candidate_count=2),
        make_record(3, candidate_count=3),
        make_record(4, candidate_count=4),
    ]

    summary = summarize_trace_records(
        records,
        thresholds=(3, 4, 5),
        min_high_count=1,
        min_high_fraction=0.5,
    )

    assert summary["candidate_count_histogram"] == {
        "0": 1,
        "1": 1,
        "2": 1,
        "3": 1,
        "4": 1,
    }
    assert summary["thresholds"]["3"]["high"] == 2
    assert summary["thresholds"]["4"]["high"] == 1
    assert summary["thresholds"]["5"]["high"] == 0
    assert summary["minimum_pass"] is True


def test_trace_complexity_cli_fails_when_high_coverage_missing(tmp_path):
    trace = tmp_path / "trace.jsonl"
    write_trace_jsonl(
        [make_record(index, candidate_count=1) for index in range(3)],
        trace,
    )
    output_dir = tmp_path / "summary"

    exit_code = trace_complexity_main(
        [
            "--trace",
            str(trace),
            "--output-dir",
            str(output_dir),
            "--min-high-count",
            "2",
            "--min-high-fraction",
            "0.5",
        ]
    )

    assert exit_code == 1
    report = json.loads((output_dir / "trace_complexity_summary.json").read_text())
    assert report["pass"] is False
    assert report["fail_reasons"]


def test_trace_complexity_cli_passes_when_fraction_is_sufficient(tmp_path):
    trace = tmp_path / "trace.jsonl"
    write_trace_jsonl(
        [
            make_record(0, candidate_count=3),
            make_record(1, candidate_count=3),
            make_record(2, candidate_count=1),
        ],
        trace,
    )
    output_dir = tmp_path / "summary"

    exit_code = trace_complexity_main(
        [
            "--trace",
            str(trace),
            "--output-dir",
            str(output_dir),
            "--min-high-count",
            "500",
            "--min-high-fraction",
            "0.5",
        ]
    )

    assert exit_code == 0
    report = json.loads((output_dir / "trace_complexity_summary.json").read_text())
    assert report["pass"] is True
