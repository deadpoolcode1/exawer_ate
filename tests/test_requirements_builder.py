"""Tests for ate.planner.requirements_builder — three-source catalog merge."""
from __future__ import annotations

from pathlib import Path

from ate.planner.requirements_builder import build_catalog, mark_claimed

ROOT = Path(__file__).resolve().parents[1]
EVPN_SPEC = ROOT / "tests/corpus/tier_a/EVPN System Specification 1.00.docx"
EVPN_CLI = ROOT / "references/EVPN CLI 1.00.docx"
RFC7432BIS = ROOT / "references/draft-ietf-bess-rfc7432bis-13.txt"
RFC9785 = ROOT / "references/rfc9785.txt"


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


def test_cli_inheritance_emits_seven_bgp_subconfigs() -> None:
    """When EVPN CLI doc contains `af-l2vpn evpn`, the inheritance table
    must inject the 7 BGP-neighbor sub-configs Eyal flagged in his review."""
    cat = build_catalog(EVPN_SPEC, cli_doc_path=EVPN_CLI)
    assert "allow-as-in" in cat.inherited_cmd_names
    assert "capability" in cat.inherited_cmd_names
    assert "inbound-soft-reconfiguration" in cat.inherited_cmd_names
    assert "maximum-prefix" in cat.inherited_cmd_names
    assert "policy" in cat.inherited_cmd_names
    assert "private-as" in cat.inherited_cmd_names
    assert "route-reflector-client" in cat.inherited_cmd_names
    assert len(cat.inherited_cmd_names) == 7
    # And each one shows up in the requirements list with provenance "cli-inherit".
    inherited_anchors = [r for r in cat.requirements
                          if cat.provenance.get(r.req_id) == "cli-inherit"]
    assert len(inherited_anchors) == 7


def test_mark_claimed_promotes_unclaimed_rfc_to_synth() -> None:
    """An RFC req that no flow claims must become a synth_anchor (so the
    atomic-row renderer can emit a Synthesized — Review entry for it)."""
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
