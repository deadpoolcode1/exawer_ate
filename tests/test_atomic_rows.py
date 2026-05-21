"""Tests for ate.planner.atomic_rows — PlanRow → AtomicRow decomposition."""
from __future__ import annotations

from ate.planner.atomic_rows import (
    _parse_blob,
    _split_expectation,
    rows_for_plan_row,
)
from ate.planner.model import PlanRow


def test_parse_blob_handles_numbered_steps() -> None:
    blob = (
        "Setup:\n"
        "  1. DUT booted\n"
        "  2. CLI session attached\n"
        "Action:\n"
        "  1. Issue `evpn evi-1`\n"
        "  2. Commit\n"
        "Verify:\n"
        "  1. `show evpn evi` reports up"
    )
    setup, action, verify = _parse_blob(blob)
    assert setup == ["DUT booted", "CLI session attached"]
    assert action == ["Issue `evpn evi-1`", "Commit"]
    assert verify == ["`show evpn evi` reports up"]


def test_parse_blob_handles_inline_one_liners() -> None:
    """Legacy templates render Setup/Action/Verify as `Label:  prose`."""
    blob = (
        "Setup:  DUT booted; no prior config.\n"
        "Action: Configure feature; commit.\n"
        "Verify: `show running-config` includes the feature."
    )
    setup, action, verify = _parse_blob(blob)
    assert setup and "DUT booted" in setup[0]
    assert action and "Configure" in action[0]
    assert verify and "show running-config" in verify[0]


def test_split_expectation_parses_pass_and_fail() -> None:
    exp = "Pass: feature operates per spec\nFail-on: feature fails to come up"
    p, f = _split_expectation(exp)
    assert p == "feature operates per spec"
    assert f == "feature fails to come up"


def test_plan_row_decomposes_to_banner_plus_atomic() -> None:
    row = PlanRow(
        flow_id="FLOW-010",
        flow_name="Single-homed VLAN-Based EVPN bring-up",
        category="Basic Functionality",
        equipment="DUT + IXIA + neighbor PE",
        action_steps=(
            "Setup:\n  1. Two-PE topology\n"
            "Action:\n  1. Configure evpn evi-1\n  2. Send traffic\n"
            "Verify:\n  1. `show evpn evi` reports up"
        ),
        expectation="Pass: EVI up within 10 s\nFail-on: EVI never reaches up",
        covered_req_ids=["EVPNS-REQ#20"],
        sfs_requirement_id="EVPNS-REQ#20",
    )
    atomic = rows_for_plan_row(row)
    # 1 banner + 1 setup + 2 actions = 4 (verify becomes monitor on actions)
    assert any(a.is_banner for a in atomic)
    assert atomic[0].is_banner
    assert "FLOW-010" in atomic[0].topic
    non_banner = [a for a in atomic if not a.is_banner]
    assert all(a.topic == "" for a in non_banner), (
        "continuation rows must leave col A empty (DHCP-snoopy convention)"
    )
    # Action steps end up as one row each.
    action_lines = [a.action for a in non_banner if "Configure evpn" in a.action]
    assert action_lines, "configure step not surfaced as its own action row"
    # Last action carries the full Pass/Fail-on expectation.
    last_action = [a for a in non_banner if "Send traffic" in a.action]
    assert last_action and "Fail-on" in last_action[0].expectation


def test_plan_row_monitor_column_extracts_show_commands() -> None:
    row = PlanRow(
        flow_id="", flow_name="", category="CLI configuration",
        sub_category="evpn",
        action_steps=(
            "Setup:  DUT booted.\n"
            "Action: Issue `evpn evi-1`\n"
            "Verify: `show evpn evi` reports up; `show running-config` includes it."
        ),
        expectation="Pass: feature comes up",
        sfs_requirement_id="CLI:evpn",
        equipment="DUT only",
    )
    atomic = rows_for_plan_row(row)
    monitors = []
    for a in atomic:
        monitors.extend(a.monitor)
    assert "show evpn evi" in monitors
    assert "show running-config" in monitors


def test_provenance_flows_through_to_atomic_rows() -> None:
    row = PlanRow(
        flow_id="", flow_name="",
        category="CLI configuration", sub_category="allow-as-in",
        action_steps="Setup:  DUT in mode.\nAction: Configure.\nVerify: works.",
        expectation="Pass: works",
        sfs_requirement_id="CLI:allow-as-in",
        equipment="DUT only",
    )
    atomic = rows_for_plan_row(row, provenance="cli-inherit")
    assert all(a.provenance == "cli-inherit" for a in atomic)
