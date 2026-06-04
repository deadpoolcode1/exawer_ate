"""Tests for the SFS-vs-ingested RFC cross-check (Aleksey Burger 2026-06-04).

The engine must alert when the SFS references RFCs that were never ingested
(only rfc9785 + rfc7432bis were provided, but the EVPN SFS cites RFC 4364
and several others).
"""
from __future__ import annotations

from pathlib import Path

from ate.parsers import parse
from ate.planner.rfc_crosscheck import (
    cited_numbers,
    format_warning,
    ingested_numbers,
    reconcile,
)

ROOT = Path(__file__).resolve().parents[1]
EVPN_SPEC = ROOT / "tests/corpus/tier_a/EVPN System Specification 1.00.docx"
RFC7432BIS = ROOT / "references" / "EVPN" / "draft-ietf-bess-rfc7432bis-13.txt"
RFC9785 = ROOT / "references" / "EVPN" / "rfc9785.txt"


def test_cited_numbers_normalises_forms() -> None:
    txt = "See RFC 7432, RFC4364, rfc-9785, and draft-ietf-bess-rfc7432bis-13."
    cited = cited_numbers(txt)
    assert set(cited) == {"7432", "4364", "9785"}
    # leading zeros stripped
    assert set(cited_numbers("RFC 0826")) == {"826"}


def test_ingested_numbers_from_filenames() -> None:
    nums = ingested_numbers([str(RFC7432BIS), str(RFC9785)])
    # rfc7432bis filename normalises to bare 7432
    assert nums == {"7432", "9785"}


def test_bis_matches_base_rfc() -> None:
    # SFS citing "RFC 7432" is satisfied by ingesting rfc7432bis.
    cc = reconcile("Built on RFC 7432.", [str(RFC7432BIS)])
    assert cc.covered == ["7432"]
    assert cc.missing == []
    assert not cc.has_gap


def test_missing_and_boilerplate_handling() -> None:
    txt = "RFC 7432, RFC 4364, RFC 4761, RFC2119, rfc9785."
    cc = reconcile(txt, [str(RFC7432BIS), str(RFC9785)])
    assert cc.covered == ["7432", "9785"]
    # 4364/4761 missing; 2119 ignored as BCP-14 boilerplate
    assert cc.missing == ["4364", "4761"]
    assert cc.has_gap
    warn = format_warning(cc)
    assert "RFC4364" in warn and "RFC4761" in warn
    # 2119 may appear inside a context snippet, but never as its own bullet.
    assert not any(ln.lstrip().startswith("• RFC2119")
                   for ln in warn.splitlines())


def test_no_gap_warning_is_empty() -> None:
    cc = reconcile("Only RFC 9785 and RFC 7432 here.",
                   [str(RFC7432BIS), str(RFC9785)])
    assert format_warning(cc) == ""


def test_real_evpn_sfs_flags_rfc4364() -> None:
    """End-to-end against the committed EVPN SFS: RFC 4364 (the source of
    Aleksey's missing EVI-to-EVI topics) must be reported as un-ingested."""
    doc = parse(EVPN_SPEC)
    cc = reconcile(doc.full_text, [str(RFC7432BIS), str(RFC9785)])
    assert "7432" in cc.covered and "9785" in cc.covered
    assert "4364" in cc.missing
    # The two ingested RFCs are never themselves flagged missing.
    assert "7432" not in cc.missing and "9785" not in cc.missing
