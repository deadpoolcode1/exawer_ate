"""Tests for ate.planner.requirements_builder — three-source catalog merge."""
from __future__ import annotations

from pathlib import Path

from ate.planner.requirements_builder import build_catalog, mark_claimed

ROOT = Path(__file__).resolve().parents[1]
EVPN_SPEC = ROOT / "tests/corpus/tier_a/EVPN System Specification 1.00.docx"
EVPN_CLI = ROOT / "references/EVPN/EVPN CLI 1.00.docx"
RFC7432BIS = ROOT / "references/EVPN/draft-ietf-bess-rfc7432bis-13.txt"
RFC9785 = ROOT / "references/EVPN/rfc9785.txt"


def test_sfs_only_catalog_has_provenance_sfs() -> None:
    cat = build_catalog(EVPN_SPEC)
    assert cat.requirements, "no requirements extracted"
    sfs_count = sum(1 for v in cat.provenance.values() if v == "sfs")
    assert sfs_count >= 30
    assert all(v == "sfs" for v in cat.provenance.values()), (
        "SFS-only catalog should not have non-sfs provenance"
    )
    assert cat.cli_commands == []
    assert cat.synth_anchors == []


def test_rfc_requirements_get_rfc_provenance() -> None:
    cat = build_catalog(EVPN_SPEC, rfc_paths=[RFC9785])
    rfc_ids = [rid for rid, src in cat.provenance.items() if src == "rfc"]
    assert rfc_ids, "no RFC requirements detected"
    assert all(rid.startswith("RFC9785-") for rid in rfc_ids)


#: The BGP-neighbor knobs SFS EVPNS-REQ#20 names AND the base Command
#: Reference Guide documents. `weight` joined the set when the guide arrived
#: (2026-07-13): EVPNS-REQ#20 always listed it, but the hand-curated table
#: predated the guide and had missed it. `group` is in the SFS list and has
#: no command section in the guide, so it is reported rather than emitted.
EXPECTED_INHERITED = {
    "allow-as-in", "capability", "inbound-soft-reconfiguration",
    "maximum-prefix", "policy", "private-as", "route-reflector-client",
    "weight",
}


def test_cli_inheritance_emits_the_req20_bgp_subconfigs() -> None:
    """`af-l2vpn evpn` in the EVPN CLI doc pulls in the inherited BGP knobs."""
    cat = build_catalog(EVPN_SPEC, cli_doc_path=EVPN_CLI)
    assert set(cat.inherited_cmd_names) == EXPECTED_INHERITED
    # And each one shows up in the requirements list with provenance "cli-inherit".
    inherited_anchors = [r for r in cat.requirements
                          if cat.provenance.get(r.req_id) == "cli-inherit"]
    assert len(inherited_anchors) == len(EXPECTED_INHERITED)


def test_mark_claimed_promotes_unclaimed_rfc_to_synth() -> None:
    """An RFC req that no flow claims must become a synth_anchor so
    `generator._planrow_for_rfc_orphan` can emit a first-class PlanRow
    that lands on the main sheet (Yossi 2026-05-21)."""
    cat = build_catalog(EVPN_SPEC, rfc_paths=[RFC7432BIS, RFC9785])
    # Pretend nothing was claimed: every RFC req becomes a synth_anchor.
    mark_claimed(cat, claimed_req_ids=set())
    rfc_reqs = [r for r in cat.requirements if r.source == "rfc"]
    assert len(cat.synth_anchors) == len(rfc_reqs)
    # Pretend everything was claimed: synth_anchors is empty.
    all_ids = {r.req_id for r in cat.requirements}
    mark_claimed(cat, claimed_req_ids=all_ids)
    assert cat.synth_anchors == []


def test_dedupes_repeated_rfc_paths() -> None:
    once = build_catalog(EVPN_SPEC, rfc_paths=[RFC9785])
    twice = build_catalog(EVPN_SPEC, rfc_paths=[RFC9785, RFC9785])
    assert len(once.requirements) == len(twice.requirements)


def test_synth_anchor_only_contains_rfc_sources() -> None:
    """SFS orphans should not become synth_anchors; the Coverage sheet
    handles them as flow-catalog gaps. Only RFC orphans get auto-synth."""
    cat = build_catalog(EVPN_SPEC, rfc_paths=[RFC9785])
    mark_claimed(cat, claimed_req_ids=set())
    assert all(r.source == "rfc" for r in cat.synth_anchors)


# ---------------------------------------------------------------------------
# Plan scoping — an EVPN test plan must not carry VPLS rows
# ---------------------------------------------------------------------------

def test_vpls_only_commands_are_dropped_from_the_evpn_plan() -> None:
    """Eyal Ozeri, 2026-07-07: "the TP is for evpn".

    `mac-address-static (VPLS)` is documented only under `l2-services vpls`,
    so scoping it to EVPN leaves nothing to test and it must not appear.
    """
    cat = build_catalog(EVPN_SPEC, cli_doc_path=EVPN_CLI)
    names = {c.name for c in cat.cli_commands}
    assert "mac-address-static (VPLS)" not in names


def test_dual_mode_commands_keep_only_their_evpn_mode() -> None:
    """A shared command stays — only its VPLS mode path goes.

    This is the distinction an earlier attempt got wrong: it stripped the
    PARAMETERS off shared commands (which Eyal then reported as "removed, not
    corrected") when what had to go was the MODE. `mac-limit` is a real EVPN
    knob and keeps its range and default.
    """
    cat = build_catalog(EVPN_SPEC, cli_doc_path=EVPN_CLI)
    by_name = {c.name: c for c in cat.cli_commands}

    mac_limit = by_name["mac-limit"]
    assert mac_limit.mode_paths, "mac-limit lost its mode paths"
    for path in mac_limit.mode_paths:
        assert "vpls" not in path, path
    assert any("evpn" in p for p in mac_limit.mode_paths)
    assert mac_limit.parameters, "scoping must not strip parameters"


def test_shared_interface_command_is_renamed_to_evpn_only() -> None:
    """`interface (VPLS/EVPN)` must not advertise VPLS in an EVPN plan."""
    names = {c.name for c in
             build_catalog(EVPN_SPEC, cli_doc_path=EVPN_CLI).cli_commands}
    assert "interface (VPLS/EVPN)" not in names
    assert "interface (EVPN)" in names
