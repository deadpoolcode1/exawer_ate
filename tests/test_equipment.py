"""Tests for the equipment classifier — Yossi gap #6 (missing IXIA indication)."""
from __future__ import annotations

from ate.planner.equipment import equipment_for_cli_row, equipment_for_row


def test_cli_row_equipment_tag() -> None:
    eq = equipment_for_cli_row()
    assert "DUT only" in eq
    assert "CLI" in eq


def test_packet_validation_requires_neighbor_pe() -> None:
    eq = equipment_for_row("Packet validation", ["PACKET"])
    assert "IXIA" in eq and "neighbor PE" in eq


def test_basic_functionality_packet_path_uses_neighbor() -> None:
    """A PACKET-tagged requirement's Basic Functionality needs IXIA + peer."""
    eq = equipment_for_row("Basic Functionality", ["PACKET"])
    assert "IXIA" in eq and "neighbor PE" in eq


def test_basic_functionality_config_only_drops_ixia() -> None:
    """A CONFIG-only requirement's Basic Functionality reads back via show —
    no traffic gen needed."""
    eq = equipment_for_row("Basic Functionality", ["CONFIG"])
    assert "IXIA" not in eq
    assert "show" in eq.lower() or "DUT only" in eq


def test_3rd_party_interop_for_rfc_calls_out_conformance() -> None:
    eq = equipment_for_row("3rd Party Interoperability", ["PROTOCOL"], source="rfc")
    assert "RFC conformance" in eq


def test_long_run_requires_continuous_traffic() -> None:
    eq = equipment_for_row("Long run", ["HA"])
    assert "≥ 24" in eq or "continuous" in eq.lower()


def test_robustness_includes_power_cycle() -> None:
    eq = equipment_for_row("Robustness", ["HA"])
    assert "power-cycle" in eq.lower()


def test_management_uses_netconf() -> None:
    eq = equipment_for_row("Management", ["CONFIG"])
    assert "NETCONF" in eq


def test_unknown_category_falls_back_safely() -> None:
    eq = equipment_for_row("Made-up category", ["CONFIG"])
    assert eq == "DUT only"
