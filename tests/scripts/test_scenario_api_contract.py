"""Scenario payload contract checks for the existing NEF API."""

import re

from scripts.run_enhanced_experiment import SCENARIOS
from scripts.scenarios.highway_handover import (
    DenseHighwayHandoverScenario,
    HighwayHandoverScenario,
)
from scripts.scenarios.smart_city_downtown import SmartCityDowntownScenario


CELL_ID_PATTERN = re.compile(r"^[A-Fa-f0-9]{9}$")
NEF_SPEED_VALUES = {"STATIONARY", "LOW", "HIGH"}
SEEDED_BASIC_IPS = {"10.0.0.1", "10.0.0.2", "10.0.0.3"}
SEEDED_BASIC_MACS = {
    "22-00-00-00-00-01",
    "22-00-00-00-00-02",
    "22-00-00-00-00-03",
}


def _set_nef_env(monkeypatch) -> None:
    monkeypatch.setenv("NEF_URL", "http://localhost:8080")
    monkeypatch.setenv("NEF_USERNAME", "admin@example.com")
    monkeypatch.setenv("NEF_PASSWORD", "local-test-password")


def test_highway_cell_ids_match_nef_schema(monkeypatch):
    _set_nef_env(monkeypatch)

    cells = HighwayHandoverScenario(seed=42).generate_cells()

    assert cells
    assert all(CELL_ID_PATTERN.fullmatch(cell.cell_id) for cell in cells)


def test_dense_highway_is_registered():
    assert SCENARIOS["highway_dense"]["class_"] is DenseHighwayHandoverScenario


def test_dense_highway_has_more_cells_than_standard_highway(monkeypatch):
    _set_nef_env(monkeypatch)

    standard_cells = HighwayHandoverScenario(seed=42).generate_cells()
    dense_cells = DenseHighwayHandoverScenario(seed=42).generate_cells()

    assert len(dense_cells) > len(standard_cells)
    assert all(CELL_ID_PATTERN.fullmatch(cell.cell_id) for cell in dense_cells)


def test_dense_highway_topology_is_deterministic_across_seeds(monkeypatch):
    _set_nef_env(monkeypatch)

    first = DenseHighwayHandoverScenario(seed=51).generate_cells()
    second = DenseHighwayHandoverScenario(seed=61).generate_cells()

    assert [cell.to_api_payload() for cell in first] == [
        cell.to_api_payload() for cell in second
    ]


def test_smart_city_cell_ids_match_nef_schema(monkeypatch):
    _set_nef_env(monkeypatch)

    cells = SmartCityDowntownScenario(seed=42).generate_cells()

    assert cells
    assert all(CELL_ID_PATTERN.fullmatch(cell.cell_id) for cell in cells)


def test_highway_ue_speeds_match_nef_schema(monkeypatch):
    _set_nef_env(monkeypatch)

    ues = HighwayHandoverScenario(seed=42).generate_ues()

    assert ues
    assert all(ue.speed_profile in NEF_SPEED_VALUES for ue in ues)


def test_smart_city_ue_speeds_match_nef_schema(monkeypatch):
    _set_nef_env(monkeypatch)

    ues = SmartCityDowntownScenario(seed=42).generate_ues()

    assert ues
    assert all(ue.speed_profile in NEF_SPEED_VALUES for ue in ues)


def test_highway_ue_identifiers_do_not_collide_with_seeded_basic_scenario(monkeypatch):
    _set_nef_env(monkeypatch)

    ues = HighwayHandoverScenario(seed=42).generate_ues()

    ipv4_values = {ue.ip_address_v4 for ue in ues}
    mac_values = {ue.mac_address for ue in ues}
    assert len(ipv4_values) == len(ues)
    assert len(mac_values) == len(ues)
    assert ipv4_values.isdisjoint(SEEDED_BASIC_IPS)
    assert mac_values.isdisjoint(SEEDED_BASIC_MACS)
