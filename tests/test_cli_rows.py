"""Tests for cli_rows — concrete CLI configuration rows from CliCommand objects.

These pin the per-command row family contract that closes Yossi's
"missing validations, defaults, mutex" review gap. Every row family
must:
  - reference the real command name in setup/action/verify text;
  - emit a range-validation row for each typed parameter;
  - emit a mutex row when ≥2 choice parameters exist;
  - emit a default-behavior row only when the doc names a default;
  - emit a `no` form row only when the syntax shows it;
  - emit a persistence row;
  - emit a prerequisite row when notes describe constraints.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ate.planner.cli_extractor import config_commands
from ate.planner.cli_rows import cli_command_rows, rows_for_command

ROOT = Path(__file__).resolve().parents[1]
CLI_DOC = ROOT / "references" / "EVPN" / "EVPN CLI 1.00.docx"


@pytest.fixture(scope="module")
def configs():
    return config_commands(CLI_DOC)


def test_all_rows_carry_setup_action_verify(configs) -> None:
    """Every row's action_steps must scaffold the three QA stages so the
    reviewer doesn't have to infer procedure (Yossi gap #2)."""
    for cmd in configs:
        for row in rows_for_command(cmd):
            for marker in ("Setup:", "Action:", "Verify:"):
                assert marker in row.action_steps, (
                    f"{cmd.name} / {row.expectation[:40]} missing {marker!r}"
                )


def test_all_rows_carry_pass_criterion(configs) -> None:
    for cmd in configs:
        for row in rows_for_command(cmd):
            assert "Pass:" in row.expectation, (
                f"{cmd.name} expectation lacks measurable Pass criterion"
            )


def test_all_rows_carry_equipment_tag(configs) -> None:
    """Closes Yossi gap #6 (missing IXIA/equipment indication)."""
    for cmd in configs:
        for row in rows_for_command(cmd):
            assert row.equipment, f"{cmd.name} row missing equipment tag"
            assert "DUT" in row.equipment


def test_all_rows_anchor_to_synthetic_cli_req_id(configs) -> None:
    """Each CLI row anchors to a `CLI:<cmd>` traceability id."""
    for cmd in configs:
        for row in rows_for_command(cmd):
            assert row.sfs_requirement_id == f"CLI:{cmd.name}"
            assert row.sub_category == cmd.name


def test_range_validation_row_for_typed_param(configs) -> None:
    """`lacp-key key-value` (integer 0..65535) must produce a validation row
    that names invalid values (above range, below range, non-integer)."""
    lk = next(c for c in configs if c.name == "lacp-key")
    rows = rows_for_command(lk)
    # Find the validation row
    validation = [r for r in rows if "Issue `lacp-key <key-value>`" in r.action_steps]
    assert len(validation) == 1
    txt = validation[0].action_steps
    # Concrete invalid values must appear in the Action line
    assert "65536" in txt and "above range" in txt


def test_mutex_row_for_choice_command(configs) -> None:
    """`load-balancing-mode single-active | all-active` must produce a mutex row."""
    lb = next(c for c in configs if c.name == "load-balancing-mode")
    rows = rows_for_command(lb)
    mutex = [r for r in rows if "Mutually-exclusive" in r.expectation]
    assert len(mutex) == 1
    assert "single-active" in mutex[0].action_steps
    assert "all-active" in mutex[0].action_steps


def test_default_row_only_when_doc_names_default(configs) -> None:
    """`load-balancing-mode` doc names default `single-active` → default row;
    `ethernet-segment` doc has no default phrase → no default row."""
    lb = next(c for c in configs if c.name == "load-balancing-mode")
    lb_rows = rows_for_command(lb)
    assert any("Default behaviour matches" in r.expectation for r in lb_rows)

    es = next(c for c in configs if c.name == "ethernet-segment")
    es_rows = rows_for_command(es)
    assert not any("Default behaviour matches" in r.expectation for r in es_rows)


def test_no_form_row_only_when_syntax_shows_it(configs) -> None:
    lk = next(c for c in configs if c.name == "lacp-key")
    lk_rows = rows_for_command(lk)
    assert any("no lacp-key" in r.action_steps for r in lk_rows)


def test_persistence_row_always_present(configs) -> None:
    """Every config command needs a reload-persistence row."""
    for cmd in configs:
        rows = rows_for_command(cmd)
        assert any("survives reload" in r.expectation for r in rows), (
            f"{cmd.name} missing persistence row"
        )


def test_show_command_returns_no_rows() -> None:
    """`rows_for_command` returns [] for non-config commands so the CLI
    section doesn't accidentally include `show`/`clear` rows."""
    from ate.planner.cli_extractor import CliCommand
    show_cmd = CliCommand(name="show evpn summary", kind="show",
                          syntax="show evpn summary",
                          syntax_lines=["show evpn summary"])
    assert rows_for_command(show_cmd) == []


def test_full_command_set_produces_useful_volume(configs) -> None:
    """21 config commands should produce ≥80 rows in total (each command
    yields 4-7 rows depending on params/choices/defaults)."""
    rows = cli_command_rows(configs)
    assert len(rows) >= 80
