import pytest
import requests

from pathlib import Path

from scripts.policy_comparison.nef_trace import feature_vector_to_trace_record
from scripts.policy_comparison.policy_adapters import (
    CandidateRankerPolicyAdapter,
    ComplexityAwarePolicyAdapter,
    FixedA3PolicyAdapter,
    MLPolicyAdapter,
    PolicyAdapterError,
    StrongestSignalPolicyAdapter,
    TunedA3PolicyAdapter,
    trace_record_to_ml_payload,
)
from scripts.policy_comparison.schemas import PolicyDecisionRecord


def trace_record(step_index=0, serving="cell-a", cell_b_rsrp=-78.0):
    return feature_vector_to_trace_record(
        {
            "ue_id": "ue-1",
            "latitude": 37.1,
            "longitude": 23.2,
            "speed": 30.0,
            "connected_to": serving,
            "neighbor_rsrp_dbm": {"cell-a": -84.0, "cell-b": cell_b_rsrp},
            "neighbor_sinrs": {"cell-a": 8.0, "cell-b": 12.0},
            "neighbor_cell_loads": {"cell-a": 2.0, "cell-b": 4.0},
            "direction": [1.0, 0.0, 0.0],
            "handover_count": 2,
            "time_since_handover": 11.0,
            "rsrp_stddev": 1.5,
        },
        scenario="highway",
        seed=7,
        step_index=step_index,
        timestamp_s=float(step_index),
    )


def high_complexity_trace_record():
    return feature_vector_to_trace_record(
        {
            "ue_id": "ue-1",
            "latitude": 37.1,
            "longitude": 23.2,
            "speed": 30.0,
            "connected_to": "cell-a",
            "neighbor_rsrp_dbm": {
                "cell-a": -84.0,
                "cell-b": -78.0,
                "cell-c": -79.0,
                "cell-d": -80.0,
            },
            "neighbor_sinrs": {
                "cell-a": 8.0,
                "cell-b": 12.0,
                "cell-c": 10.0,
                "cell-d": 9.0,
            },
        },
        scenario="highway",
        seed=7,
        step_index=0,
        timestamp_s=0.0,
    )


class FakeRankerArtifact:
    path = Path("ranker.joblib")
    artifact_sha256 = "abc123"
    selected_threshold = 2.0
    model_family = "candidate_ranker"
    decision_parameters = {
        "selected_min_margin": 2.0,
        "min_ml_dwell_s": 10.0,
        "a3_reentry_extra_margin_db": 3.0,
    }

    def __init__(self, scores):
        self.scores = scores

    def score_rows(self, rows):
        return {
            row["candidate_cell"]: self.scores.get(row["candidate_cell"], 0.0)
            for row in rows
        }

    def safe_metadata(self):
        return {
            "model_type": "candidate_ranker_lightgbm_regressor",
            "model_family": "candidate_ranker",
            "target": "utility_margin_vs_stay",
            "selected_features": ["delta_rsrp_db"],
            "validation_metrics": {"validation_rmse": 0.1},
            "threshold_tuning_result": {"selected_threshold": 2.0},
            "ranker_decision_parameters": self.decision_parameters,
            "seed_split": {"validation_group_count": 1},
            "dataset_size": 4,
            "scenario_seeds": [41],
            "model_sha256": "abc123",
            "complexity_bucket_counts": {"high": 4},
            "high_complexity_row_count": 4,
            "min_high_complexity_rows": 1,
            "trace_complexity_summaries": [
                {
                    "trace": "trace.jsonl",
                    "record_count": 2,
                    "thresholds": {"3": {"high": 2, "high_fraction": 1.0}},
                }
            ],
        }


def test_fixed_a3_adapter_returns_canonical_schema_without_confidence():
    adapter = FixedA3PolicyAdapter()
    first = adapter.decide(trace_record(0))
    second = adapter.decide(trace_record(1))

    assert first.policy_name == "fixed_a3_baseline"
    assert first.confidence is None
    assert first.decision_latency_ms is not None
    assert second.decision_type == "handover"
    assert second.selected_target_cell == "cell-b"
    assert "time_to_trigger_state" in second.to_dict()
    assert second.debug["candidate_complexity"]["viable_candidate_count"] == 1


def test_strongest_signal_baseline_uses_configured_metric():
    adapter = StrongestSignalPolicyAdapter(metric="sinr")

    decision = adapter.decide(
        feature_vector_to_trace_record(
            {
                "ue_id": "ue-1",
                "latitude": 37.1,
                "longitude": 23.2,
                "connected_to": "cell-a",
                "neighbor_rsrp_dbm": {"cell-a": -80.0, "cell-b": -78.0, "cell-c": -76.0},
                "neighbor_sinrs": {"cell-a": 5.0, "cell-b": 12.0, "cell-c": 8.0},
            },
            scenario="highway",
            seed=7,
            step_index=0,
            timestamp_s=0.0,
        )
    )

    assert decision.policy_name == "strongest_sinr_baseline"
    assert decision.selected_target_cell == "cell-b"
    assert decision.debug["candidate_complexity"]["viable_candidate_count"] == 2


def test_tuned_a3_adapter_requires_real_tuned_policy():
    with pytest.raises(PolicyAdapterError, match="requires a real tuned policy"):
        TunedA3PolicyAdapter(None)


def test_tuned_a3_adapter_can_train_from_calibration_trace():
    adapter = TunedA3PolicyAdapter.from_calibration_trace(
        [trace_record(0), trace_record(1)]
    )

    assert adapter.name == "tuned_a3_baseline"
    assert adapter.parameters


def test_ml_payload_matches_existing_ml_shape():
    payload = trace_record_to_ml_payload(trace_record())

    assert payload["ue_id"] == "ue-1"
    assert payload["connected_to"] == "cell-a"
    assert payload["rf_metrics"]["cell-a"]["rsrp"] == -84.0
    assert payload["rf_metrics"]["cell-b"]["sinr"] == 12.0
    assert payload["rf_metrics"]["cell-b"]["cell_load"] == 4.0
    assert payload["handover_count"] == 2
    assert payload["time_since_handover"] == 11.0
    assert payload["rsrp_stddev"] == 1.5
    assert payload["service_type"] == "default"
    assert payload["service_priority"] == 5


def test_ml_payload_filters_observed_qos_to_ml_schema_fields():
    record = feature_vector_to_trace_record(
        {
            "ue_id": "ue-1",
            "latitude": 37.1,
            "longitude": 23.2,
            "speed": 30.0,
            "connected_to": "cell-a",
            "neighbor_rsrp_dbm": {"cell-a": -84.0, "cell-b": -78.0},
            "observed_qos": {
                "latest": {
                    "latency_ms": 12.0,
                    "jitter_ms": 1.0,
                    "throughput_mbps": 20.0,
                    "packet_loss_rate": 0.1,
                    "timestamp": 123456.0,
                }
            },
        },
        scenario="highway",
        seed=7,
        step_index=0,
        timestamp_s=0.0,
    )

    payload = trace_record_to_ml_payload(record)

    assert payload["observed_qos"] == {
        "latency_ms": 12.0,
        "jitter_ms": 1.0,
        "throughput_mbps": 20.0,
        "packet_loss_rate": 0.1,
    }


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeSession:
    def __init__(self):
        self.posts = []

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return FakeResponse(
            200,
            {
                "ue_id": "ue-1",
                "predicted_antenna": "cell-b",
                "confidence": 0.91,
                "qos_compliance": {"service_priority_ok": True},
            },
        )


def test_ml_policy_adapter_returns_canonical_decision_without_fallback():
    session = FakeSession()
    adapter = MLPolicyAdapter(ml_base_url="http://ml.local", session=session)

    decision = adapter.decide(trace_record())

    assert session.posts[0][0] == "http://ml.local/api/predict-with-qos"
    assert decision.policy_name == "ml_policy"
    assert decision.decision_type == "handover"
    assert decision.selected_target_cell == "cell-b"
    assert decision.confidence == 0.91
    assert decision.time_to_trigger_state == {}
    assert decision.cooldown_state == {}
    assert decision.debug["candidate_complexity"]["complexity_bucket"] == "sparse"


class AliasPredictionSession:
    def post(self, url, **kwargs):
        return FakeResponse(
            200,
            {
                "ue_id": "ue-1",
                "predicted_antenna": "antenna_2",
                "confidence": 0.88,
                "qos_compliance": {"service_priority_ok": True},
            },
        )


def test_ml_policy_adapter_resolves_nef_antenna_digit_alias():
    record = feature_vector_to_trace_record(
        {
            "ue_id": "ue-1",
            "latitude": 37.1,
            "longitude": 23.2,
            "connected_to": "1",
            "neighbor_rsrp_dbm": {"1": -84.0, "2": -78.0},
        },
        scenario="highway",
        seed=7,
        step_index=0,
        timestamp_s=0.0,
    )
    adapter = MLPolicyAdapter(
        ml_base_url="http://ml.local",
        session=AliasPredictionSession(),
    )

    decision = adapter.decide(record)

    assert decision.selected_target_cell == "2"
    assert decision.debug["ml_target_resolution"] == {
        "raw_target": "antenna_2",
        "resolved_target": "2",
        "method": "nef_antenna_digit_alias",
    }


class FailingSession:
    def post(self, url, **kwargs):
        return FakeResponse(503, {"error": "unavailable"})


def test_ml_policy_adapter_raises_on_ml_failure_instead_of_fallback():
    adapter = MLPolicyAdapter(ml_base_url="http://ml.local", session=FailingSession())

    with pytest.raises(PolicyAdapterError, match="HTTP 503"):
        adapter.decide(trace_record())


class FallbackResponseSession:
    def post(self, url, **kwargs):
        return FakeResponse(
            200,
            {
                "ue_id": "ue-1",
                "predicted_antenna": "cell-b",
                "confidence": 0.91,
                "fallback_reason": "geographic_override",
                "geographic_override": True,
            },
        )


def test_ml_policy_adapter_rejects_hidden_fallback_metadata():
    adapter = MLPolicyAdapter(
        ml_base_url="http://ml.local",
        session=FallbackResponseSession(),
    )

    with pytest.raises(PolicyAdapterError, match="fallback/override"):
        adapter.decide(trace_record())


class FlakyTransportSession:
    def __init__(self):
        self.calls = 0

    def post(self, url, **kwargs):
        self.calls += 1
        if self.calls == 1:
            raise requests.ConnectionError("worker restarted")
        return FakeResponse(
            200,
            {
                "ue_id": "ue-1",
                "predicted_antenna": "cell-b",
                "confidence": 0.91,
                "qos_compliance": {"service_priority_ok": True},
            },
        )


def test_ml_policy_adapter_retries_transport_disconnect_once():
    session = FlakyTransportSession()
    adapter = MLPolicyAdapter(
        ml_base_url="http://ml.local",
        session=session,
        retry_sleep_s=0.0,
    )

    decision = adapter.decide(trace_record())

    assert session.calls == 2
    assert decision.selected_target_cell == "cell-b"


def test_candidate_ranker_policy_adapter_selects_highest_scored_candidate():
    adapter = CandidateRankerPolicyAdapter(
        FakeRankerArtifact({"cell-b": 1.0, "cell-c": 4.0, "cell-d": 3.0})
    )

    decision = adapter.decide(high_complexity_trace_record())

    assert decision.policy_name == "ml_policy"
    assert decision.decision_type == "handover"
    assert decision.selected_target_cell == "cell-c"
    assert decision.confidence is None
    assert decision.debug["ml_backend"] == "candidate_ranker"
    assert decision.debug["ranker_selected_candidate"] == "cell-c"
    assert decision.debug["ranker_best_candidate"] == "cell-c"
    assert decision.debug["ranker_margin_vs_stay"] == 4.0
    assert decision.debug["ranker_min_margin"] == 2.0
    assert decision.debug["dwell_guard_applied"] is False
    assert decision.debug["ranker_artifact_sha256"] == "abc123"
    assert decision.debug["candidate_complexity"]["complexity_bucket"] == "high"


def test_candidate_ranker_policy_adapter_stays_below_threshold():
    adapter = CandidateRankerPolicyAdapter(FakeRankerArtifact({"cell-b": 1.5}))

    decision = adapter.decide(trace_record())

    assert decision.decision_type == "stay"
    assert decision.selected_target_cell is None
    assert decision.debug["ranker_selected_score"] == 1.5
    assert decision.debug["ranker_score_threshold"] == 2.0
    assert decision.debug["ranker_margin_vs_stay"] == 1.5


def test_candidate_ranker_policy_adapter_dwell_guard_suppresses_recent_ml_handover():
    adapter = CandidateRankerPolicyAdapter(
        FakeRankerArtifact({"cell-b": 5.0, "cell-c": 4.0, "cell-d": 3.0})
    )
    adapter.set_replay_state(
        "ue-1",
        {
            "recent_handover_count": 1,
            "time_since_last_handover_s": 3.0,
            "last_handover_source": "ml_high_complexity",
            "current_dwell_time_s": 3.0,
        },
    )

    decision = adapter.decide(high_complexity_trace_record())

    assert decision.decision_type == "stay"
    assert decision.debug["dwell_guard_applied"] is True
    assert decision.reason == "ranker_dwell_guard"


class FakeSparsePolicy:
    name = "tuned_a3_baseline"
    parameters = {"source": "unit-test"}

    def reset(self, ue_id=None):
        return None

    def decide(self, record):
        serving = record.visible_cell_map[record.serving_cell]
        return PolicyDecisionRecord(
            ue_id=record.ue_id,
            timestamp_s=record.timestamp_s,
            step_index=record.step_index,
            current_serving_cell=record.serving_cell,
            selected_target_cell=None,
            decision_type="stay",
            policy_name=self.name,
            policy_parameters=self.parameters,
            serving_measurement_value=serving.rsrp_dbm,
            neighbour_measurements_considered={
                cell.cell_id: cell.rsrp_dbm
                for cell in record.visible_cells
                if cell.cell_id != record.serving_cell
            },
            trigger_condition_result=False,
            time_to_trigger_state={},
            cooldown_state={},
            reason="fake_sparse_policy",
            debug={"decision_source": self.name},
        )


def test_complexity_aware_adapter_routes_sparse_to_a3():
    adapter = ComplexityAwarePolicyAdapter(
        sparse_policy=FakeSparsePolicy(),
        ml_policy=MLPolicyAdapter(ml_base_url="http://ml.local", session=FakeSession()),
    )

    decision = adapter.decide(trace_record())

    assert decision.policy_name == "complexity_aware_ml_a3"
    assert decision.decision_type == "stay"
    assert decision.debug["decision_source"] == "a3_complexity_gate"
    assert decision.debug["delegated_policy"] == "tuned_a3_baseline"
    assert decision.debug["candidate_complexity"]["complexity_bucket"] == "sparse"


def test_complexity_aware_adapter_routes_high_complexity_to_ml():
    adapter = ComplexityAwarePolicyAdapter(
        sparse_policy=FakeSparsePolicy(),
        ml_policy=MLPolicyAdapter(ml_base_url="http://ml.local", session=FakeSession()),
    )

    decision = adapter.decide(high_complexity_trace_record())

    assert decision.policy_name == "complexity_aware_ml_a3"
    assert decision.selected_target_cell == "cell-b"
    assert decision.debug["decision_source"] == "ml_high_complexity"
    assert decision.debug["delegated_policy"] == "ml_policy"
    assert decision.debug["candidate_complexity"]["complexity_bucket"] == "high"


def test_complexity_aware_adapter_routes_high_complexity_to_ranker_ml():
    adapter = ComplexityAwarePolicyAdapter(
        sparse_policy=FakeSparsePolicy(),
        ml_policy=CandidateRankerPolicyAdapter(
            FakeRankerArtifact({"cell-b": 4.0, "cell-c": 1.0, "cell-d": 0.5})
        ),
    )

    decision = adapter.decide(high_complexity_trace_record())

    assert decision.policy_name == "complexity_aware_ml_a3"
    assert decision.selected_target_cell == "cell-b"
    assert decision.debug["decision_source"] == "ml_high_complexity"
    assert decision.debug["delegated_policy"] == "ml_policy"
    assert decision.debug["ml_backend"] == "candidate_ranker"


def test_complexity_aware_adapter_high_complexity_ranker_stay_does_not_fallback_to_a3():
    adapter = ComplexityAwarePolicyAdapter(
        sparse_policy=FakeSparsePolicy(),
        ml_policy=CandidateRankerPolicyAdapter(
            FakeRankerArtifact({"cell-b": 1.0, "cell-c": 1.0, "cell-d": 1.0})
        ),
    )

    decision = adapter.decide(high_complexity_trace_record())

    assert decision.policy_name == "complexity_aware_ml_a3"
    assert decision.decision_type == "stay"
    assert decision.debug["decision_source"] == "ml_high_complexity"
    assert decision.debug["delegated_policy"] == "ml_policy"
