"""Tests for ate.planner.cli_inheritance — BGP-neighbor sub-config expansion."""
from __future__ import annotations

from ate.planner.cli_extractor import CliCommand
from ate.planner.cli_inheritance import (
    BGP_NEIGHBOR_AF_L2VPN_EVPN,
    INHERITANCE_TABLE,
    expand,
    inheritance_source_for,
)
from ate.planner.cli_rows import cli_command_rows


def _make_cmd(name: str, syntax: str = "") -> CliCommand:
    return CliCommand(name=name, kind="config", syntax=syntax or name)


def test_expand_emits_seven_subconfigs_for_af_l2vpn_evpn() -> None:
    """The BGP-neighbor sub-mode opens 7 standard sub-configs (Eyal's
    review example: allow-as-in / capability / inbound-soft-reconfiguration
    / maximum-prefix / policy / private-as / route-reflector-client)."""
    extracted = [_make_cmd("af-l2vpn evpn")]
    inherited = expand(extracted)
    names = {c.name for c in inherited}
    assert names == {
        "allow-as-in", "capability", "inbound-soft-reconfiguration",
        "maximum-prefix", "policy", "private-as", "route-reflector-client",
    }


def test_expand_produces_nothing_when_parent_absent() -> None:
    """No EVPN CLI = no inheritance. Inheritance fires only when the
    parent command appears in the extracted list."""
    inherited = expand([_make_cmd("ethernet-segment")])
    assert inherited == []


def test_expand_idempotent_on_existing_sub_config() -> None:
    """If a sub-config name is already in `extracted` (e.g. because the
    real BGP CLI doc was integrated), inheritance must skip it — no
    duplicate command rows."""
    extracted = [
        _make_cmd("af-l2vpn evpn"),
        _make_cmd("allow-as-in", syntax="allow-as-in <count>"),
    ]
    inherited = expand(extracted)
    inherited_names = [c.name for c in inherited]
    assert "allow-as-in" not in inherited_names
    assert len(inherited) == 6  # 7 minus the one already present


def test_inherited_commands_round_trip_through_cli_rows() -> None:
    """Each inherited sub-config must produce the standard row family
    (happy-path / range / mutex / default / `no` / persistence / help /
    filter / precondition) without changes to cli_rows.py."""
    inherited = expand([_make_cmd("af-l2vpn evpn")])
    rows = cli_command_rows(inherited)
    assert rows, "cli_command_rows returned no rows for inherited commands"
    # Each command produces multiple PlanRows (family); at minimum
    # happy-path + persistence + help + filter = 4.
    by_subcat: dict[str, int] = {}
    for r in rows:
        by_subcat[r.sub_category] = by_subcat.get(r.sub_category, 0) + 1
    assert all(n >= 4 for n in by_subcat.values()), (
        f"row family too small per command: {by_subcat}"
    )


def test_inheritance_source_for_returns_source_string() -> None:
    src = inheritance_source_for("allow-as-in")
    assert src is not None
    assert "BGP" in src or "hand-curated" in src.lower()
    assert inheritance_source_for("not-a-real-name") is None


def test_inheritance_table_has_documented_provenance() -> None:
    """Each entry in the table must carry a human-readable source string
    so the Synthesized — Review sheet can cite it."""
    assert INHERITANCE_TABLE  # at least the BGP-neighbor entry
    for entry in INHERITANCE_TABLE:
        assert entry.source
        assert entry.sub_configs
        for sub in entry.sub_configs:
            assert sub.kind == "config"
            assert sub.mode_path  # not empty
