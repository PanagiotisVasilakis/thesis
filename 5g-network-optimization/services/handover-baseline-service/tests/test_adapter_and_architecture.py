from pathlib import Path

import pytest

import handover_baseline
from handover_baseline.adapter import (
    BaselineAdapterError,
    existing_nef_reference,
    snapshot_from_feature_vector,
)


def test_adapter_converts_existing_nef_feature_vector_shape():
    snapshot = snapshot_from_feature_vector(
        {
            "ue_id": "ue-1",
            "connected_to": "cell_a",
            "neighbor_rsrp_dbm": {"cell_a": -85.0, "cell_b": -80.0},
            "neighbor_rsrqs": {"cell_a": -9.0, "cell_b": -8.5},
            "neighbor_sinrs": {"cell_a": 10.0, "cell_b": 12.0},
            "neighbor_cell_loads": {"cell_a": 5, "cell_b": 3},
        },
        timestamp_s=12.0,
        step_index=4,
    )

    assert snapshot.ue_id == "ue-1"
    assert snapshot.serving_cell.cell_id == "cell_a"
    assert snapshot.serving_cell.rsrp_dbm == -85.0
    assert snapshot.neighbour_cells[0].cell_id == "cell_b"
    assert snapshot.neighbour_cells[0].rsrq_db == -8.5
    assert snapshot.neighbour_cells[0].sinr_db == 12.0
    assert snapshot.neighbour_cells[0].load == 3.0


@pytest.mark.parametrize(
    "feature_vector, message",
    [
        ({"connected_to": "cell_a", "neighbor_rsrp_dbm": {"cell_a": -85.0}}, "ue_id"),
        ({"ue_id": "ue-1", "neighbor_rsrp_dbm": {"cell_a": -85.0}}, "connected_to"),
        ({"ue_id": "ue-1", "connected_to": "cell_a"}, "neighbor_rsrp_dbm"),
        (
            {
                "ue_id": "ue-1",
                "connected_to": "cell_a",
                "neighbor_rsrp_dbm": {"cell_b": -80.0},
            },
            "serving cell",
        ),
    ],
)
def test_adapter_fails_clearly_when_required_measurements_are_missing(
    feature_vector, message
):
    with pytest.raises(BaselineAdapterError, match=message):
        snapshot_from_feature_vector(feature_vector)


def test_adapter_references_existing_nef_env_without_creating_client():
    reference = existing_nef_reference(
        {"NEF_SCHEME": "http", "NEF_HOST": "localhost", "NEF_PORT": "8080"}
    )

    assert reference.nef_url == "http://localhost:8080"
    assert reference.nef_username_env == "NEF_USERNAME"
    assert not hasattr(reference, "session")
    assert not hasattr(reference, "client")


def test_baseline_module_imports_cleanly_and_stays_separate_from_services():
    assert handover_baseline.FixedA3Policy is not None
    assert Path("5g-network-optimization/services/nef-emulator").is_dir()
    assert Path("5g-network-optimization/services/ml-service").is_dir()
    assert Path("5g-network-optimization/services/handover-baseline-service").is_dir()
    assert not list(Path("scripts").glob("handover_baseline*"))
