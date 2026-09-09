"""Tests for ate.planner.cli_inheritance — BGP-neighbor sub-configs, read from
Exaware's Command Reference Guide rather than hand-curated.

These tests replace the earlier set, which asserted the *shape* of a curated
table (7 knobs, then de-invented to coarse rows). Both of those properties were
artefacts of not having the base manual. Now that the guide is in
`references/`, the assertions are about faithfulness to it: the right knobs,
the guide's grammar, and the one place the guide and the SFS disagree.
"""
from __future__ import annotations

import pytest

from ate.planner.cli_extractor import CliCommand
from ate.planner.cli_inheritance import (
    DEFAULT_CRG_PATH,
    INHERITANCE_TABLE,
    af_enable_parents,
    document_conflicts,
    expand,
    inheritance_source_for,
    undocumented_knobs,
)
from ate.planner.cli_rows import cli_command_rows

pytestmark = pytest.mark.skipif(
    not DEFAULT_CRG_PATH.exists(),
    reason="Command Reference Guide not present in references/",
)

#: The knobs SFS EVPNS-REQ#20 names AND the base guide documents.
EXPECTED = {
    "allow-as-in", "capability", "inbound-soft-reconfiguration",
    "maximum-prefix", "policy", "private-as", "route-reflector-client",
    "weight",
}


def _make_cmd(name: str, syntax: str = "") -> CliCommand:
    return CliCommand(name=name, kind="config", syntax=syntax or name)


def test_expand_emits_the_req20_knobs_documented_in_the_base_guide() -> None:
    inherited = expand([_make_cmd("af-l2vpn evpn")])
    assert {c.name for c in inherited} == EXPECTED


def test_group_is_reported_as_undocumented_not_invented() -> None:
    """`group` is in EVPNS-REQ#20 and has no section in the guide.

    The failure mode this guards against is filling the gap with a plausible
    guess, which is how the table got fabricated in the first place.
    """
    assert "group" in undocumented_knobs()
    assert "group" not in {c.name for c in expand([_make_cmd("af-l2vpn evpn")])}


def test_expand_produces_nothing_when_parent_absent() -> None:
    assert expand([_make_cmd("ethernet-segment")]) == []


def test_expand_idempotent_on_existing_sub_config() -> None:
    """A sub-config already present in `extracted` is not duplicated."""
    extracted = [_make_cmd("af-l2vpn evpn"),
                 _make_cmd("allow-as-in", syntax="allow-as-in number")]
    inherited = expand(extracted)
    assert "allow-as-in" not in [c.name for c in inherited]
    assert len(inherited) == len(EXPECTED) - 1


# ---------------------------------------------------------------------------
# Faithfulness to the guide — one assertion per element we previously invented
# ---------------------------------------------------------------------------

def _by_name() -> dict[str, CliCommand]:
    return {c.name: c for c in expand([_make_cmd("af-l2vpn evpn")])}


def test_private_as_alternatives_are_remove_and_leave() -> None:
    """The hand-curated table said `remove | replace`. The guide says `leave`.

    This is the canonical example of the invented-grammar failure: confidently
    wrong, and indistinguishable from correct to a reviewer.
    """
    syntax = _by_name()["private-as"].syntax
    assert "remove" in syntax and "leave" in syntax
    assert "replace" not in syntax


def test_policy_takes_direction_before_name() -> None:
    """We had `policy <policy-name> {in | out}`; the guide has it reversed."""
    syntax = _by_name()["policy"].syntax_lines[0]
    assert syntax.index("{in | out}") < syntax.index("policy-name")


def test_maximum_prefix_carries_the_documented_defaults() -> None:
    """Eyal, 2026-07-07: the knob's parameters were "removed, not corrected"."""
    params = {p.name: p for p in _by_name()["maximum-prefix"].parameters}
    assert params["max"].default == "2097152"
    assert params["percent"].default == "75"
    assert {"warn", "terminate"} <= set(params)


def test_weight_is_present_and_ranged() -> None:
    """`weight` is in EVPNS-REQ#20 and was missing from the curated table."""
    params = _by_name()["weight"].parameters
    assert params and params[0].value_spec == "0-65535"


def test_capability_options_are_the_address_family_ones() -> None:
    """`orf` and `graceful-restart`, not the invented `orf-prefix-list`."""
    cap = _by_name()["capability"]
    assert "orf-prefix-list" not in cap.syntax
    assert "graceful-restart" in cap.syntax and "orf" in cap.syntax


def test_no_form_is_preserved_for_every_knob() -> None:
    for name, cmd in _by_name().items():
        assert cmd.has_no_form, f"{name} lost its `no` form"
        assert any(ln.startswith("no ") for ln in cmd.syntax_lines)


# ---------------------------------------------------------------------------
# The conflict between the two Exaware documents
# ---------------------------------------------------------------------------

def test_allow_as_in_safi_conflict_is_reported_not_resolved() -> None:
    """The guide scopes `allow-as-in` to SAFIs that exclude l2vpn evpn.

    The SFS says the EVPN address family inherits it. We emit the row (the SFS
    asked for it) and state the conflict in the Notes, so a device settles it.
    Silently dropping the row, or silently keeping it, would both hide that a
    reviewer has a decision to make.
    """
    conflicts = document_conflicts()
    assert "allow-as-in" in conflicts
    assert "unicast" in conflicts["allow-as-in"]

    notes = _by_name()["allow-as-in"].notes
    assert "DOCUMENT CONFLICT" in notes
    assert "EVPNS-REQ#20" in notes


def test_knobs_without_a_conflict_carry_no_conflict_note() -> None:
    for name, cmd in _by_name().items():
        if name == "allow-as-in":
            continue
        assert "DOCUMENT CONFLICT" not in (cmd.notes or ""), name


# ---------------------------------------------------------------------------
# Integration with the row generator and the provenance surfaces
# ---------------------------------------------------------------------------

def test_inherited_commands_round_trip_through_cli_rows() -> None:
    """Each sub-config produces the standard row family with no cli_rows change.

    Config-persistence is a single section-level row (Eyal Ozeri 2026-07-06),
    not one per command, so it is excluded from the per-command floor.
    """
    inherited = expand([_make_cmd("af-l2vpn evpn")])
    cmd_names = {c.name for c in inherited}
    rows = cli_command_rows(inherited)
    assert rows

    by_subcat: dict[str, int] = {}
    for r in rows:
        if r.sub_category in cmd_names:
            by_subcat[r.sub_category] = by_subcat.get(r.sub_category, 0) + 1
    assert by_subcat
    assert all(n >= 4 for n in by_subcat.values()), by_subcat

    persistence = [r for r in rows if "survives reload" in r.expectation]
    assert len(persistence) == 1


def test_mode_path_rehomes_the_knobs_under_af_l2vpn_evpn() -> None:
    """The guide states `… neighbor afi safi`; the plan needs the EVPN family."""
    for cmd in expand([_make_cmd("af-l2vpn evpn")]):
        assert cmd.mode_path[-2:] == ["af-l2vpn", "evpn"], cmd.name


def test_inheritance_source_cites_the_base_guide() -> None:
    src = inheritance_source_for("allow-as-in")
    assert src is not None
    assert "Command Reference Guide" in src
    assert inheritance_source_for("not-a-real-name") is None


def test_af_l2vpn_evpn_is_committable_on_its_own() -> None:
    """Eyal Ozeri 2026-07-07, annotation [13]: the AF enable commits standalone."""
    assert "af-l2vpn evpn" in af_enable_parents()


def test_inheritance_table_has_documented_provenance() -> None:
    assert INHERITANCE_TABLE
    for entry in INHERITANCE_TABLE:
        assert entry.source
        assert entry.sub_configs
        for sub in entry.sub_configs:
            assert sub.kind == "config"
            assert sub.mode_path
