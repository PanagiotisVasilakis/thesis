from scripts.policy_comparison.complexity import (
    candidate_complexity_for_feature_vector,
    candidate_complexity_for_record,
    complexity_bucket,
)
from scripts.policy_comparison.nef_trace import feature_vector_to_trace_record


def test_complexity_bucket_default_thresholds():
    assert complexity_bucket(0) == "sparse"
    assert complexity_bucket(1) == "sparse"
    assert complexity_bucket(2) == "moderate"
    assert complexity_bucket(3) == "high"
    assert complexity_bucket(4, high_complexity_threshold=5) == "moderate"
    assert complexity_bucket(5, high_complexity_threshold=5) == "high"


def test_candidate_complexity_counts_viable_non_serving_cells_only():
    record = feature_vector_to_trace_record(
        {
            "ue_id": "ue-1",
            "latitude": 10.0,
            "longitude": 20.0,
            "connected_to": "cell-a",
            "neighbor_rsrp_dbm": {
                "cell-a": -82.0,
                "cell-b": -80.0,
                "cell-c": -116.0,
                "cell-d": -78.0,
                "cell-e": -81.0,
            },
            "neighbor_sinrs": {
                "cell-a": 8.0,
                "cell-b": 4.0,
                "cell-c": 9.0,
                "cell-d": -6.0,
                "cell-e": 1.0,
            },
        },
        scenario="highway",
        seed=42,
        step_index=0,
        timestamp_s=0.0,
    )

    complexity = candidate_complexity_for_record(record)

    assert complexity.viable_candidate_count == 2
    assert complexity.complexity_bucket == "moderate"
    assert complexity.viable_candidates == ["cell-b", "cell-e"]


def test_candidate_complexity_for_feature_vector_high_bucket():
    complexity = candidate_complexity_for_feature_vector(
        {
            "connected_to": "A",
            "neighbor_rsrp_dbm": {"A": -80, "B": -79, "C": -78, "D": -77},
            "neighbor_sinrs": {"B": 0, "C": -4, "D": 6},
        }
    )

    assert complexity.viable_candidate_count == 3
    assert complexity.complexity_bucket == "high"
