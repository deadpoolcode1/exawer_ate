"""Tests for cli_extractor — mining the EVPN CLI doc into structured commands.

These tests pin the contracts that downstream code depends on:
  - Each config command has a non-empty syntax + mode_path.
  - Default behaviors are extracted where the doc states them.
  - Choice / typed parameters classify correctly so cli_rows.py can
    emit the right validation rows.
  - Show/clear commands are filtered out of `config_commands()`.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ate.planner.cli_extractor import (
    CliCommand,
    config_commands,
    extract_commands,
)

ROOT = Path(__file__).resolve().parents[1]
CLI_DOC = ROOT / "references" / "EVPN" / "EVPN CLI 1.00.docx"


@pytest.fixture(scope="module")
def commands() -> list[CliCommand]:
    return extract_commands(CLI_DOC)


@pytest.fixture(scope="module")
def configs() -> list[CliCommand]:
    return config_commands(CLI_DOC)


def test_extracts_a_useful_number_of_commands(commands: list[CliCommand]) -> None:
    """The CLI doc has ~37 command tables — extractor should recover most."""
    assert len(commands) >= 30


def test_config_commands_are_filtered_from_show_clear(configs, commands) -> None:
    """`config_commands` returns only commands whose mode is configuration —
    show and clear commands belong to other test plan sections."""
    assert len(configs) < len(commands)
    assert all(c.is_config for c in configs)
    # No show/clear leakage
    for c in configs:
        assert not c.name.lower().startswith(("show ", "clear "))


def test_named_commands_present(configs: list[CliCommand]) -> None:
    """Spot-check: a handful of well-known EVPN commands must be extracted
    so cli_rows.py can emit row families for them."""
    names = {c.name for c in configs}
    expected = {
        "ethernet-segment", "identifier", "lacp-key", "lacp-system-mac",
        "load-balancing-mode", "service-carving",
        "advertise-mac", "auto-discovery", "evpn",
        "import-rt", "export-rt", "mac-limit", "mac-aging-time",
    }
    missing = expected - names
    assert not missing, f"missing expected commands: {sorted(missing)}"


def test_syntax_and_mode_are_populated(configs: list[CliCommand]) -> None:
    for c in configs:
        assert c.syntax_lines, f"{c.name} has empty syntax"
        assert c.mode_path, f"{c.name} has empty mode_path"


def test_choice_parameters_for_load_balancing_mode(configs) -> None:
    """`load-balancing-mode single-active | all-active` → both as choice params."""
    lb = next(c for c in configs if c.name == "load-balancing-mode")
    choice_names = {p.name for p in lb.parameters if p.is_choice}
    assert {"single-active", "all-active"} <= choice_names


def test_typed_parameter_for_lacp_key(configs) -> None:
    """`lacp-key key-value` has one integer-ranged parameter."""
    lk = next(c for c in configs if c.name == "lacp-key")
    typed = [p for p in lk.parameters if p.value_spec and not p.is_choice]
    assert len(typed) == 1
    assert "0..65535" in typed[0].value_spec


def test_default_behavior_extraction(configs) -> None:
    """The doc describes `lacp-key` default as the agg-eth interface number;
    `load-balancing-mode` default is single-active.
    """
    lk = next(c for c in configs if c.name == "lacp-key")
    assert "agg-eth" in lk.default_behavior.lower()
    lb = next(c for c in configs if c.name == "load-balancing-mode")
    assert lb.default_behavior == "single-active"


def test_no_form_detection(configs) -> None:
    """Commands whose syntax cell shows `no <command>` must have has_no_form."""
    lk = next(c for c in configs if c.name == "lacp-key")
    assert lk.has_no_form
    # `auto-discovery` is mandatory and the Notes say it cannot be deleted —
    # but the syntax row still lists `no auto-discovery`, so detection is
    # syntax-only. The test plan picks up the real rule via the prerequisite
    # row using the Notes.


def test_related_features_for_service_carving(configs) -> None:
    sc = next(c for c in configs if c.name == "service-carving")
    assert "DF election" in sc.related_features


def test_extractor_is_deterministic(commands) -> None:
    """Two calls return identical objects (no hidden state, no ordering churn)."""
    cmds2 = extract_commands(CLI_DOC)
    assert [c.name for c in commands] == [c.name for c in cmds2]
    assert [c.syntax for c in commands] == [c.syntax for c in cmds2]
