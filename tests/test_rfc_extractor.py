"""RFC extractor tests — RFC normative clauses → Requirement objects.

Covers the M1-respin requirement: the test plan must trace back to RFC
clauses, not just spec EVPNS-REQ# anchors.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ate.planner.rfc_extractor import (
    _BOILERPLATE_TITLES,
    _short_name,
    extract_rfc_requirements,
)

ROOT = Path(__file__).resolve().parents[1]
RFC7432BIS = ROOT / "references" / "EVPN" / "draft-ietf-bess-rfc7432bis-13.txt"
RFC9785 = ROOT / "references" / "EVPN" / "rfc9785.txt"


# ─── Filename → short name ──────────────────────────────────────────────────

@pytest.mark.parametrize("filename,expected", [
    ("rfc9785.txt", "RFC9785"),
    ("rfc9785.docx", "RFC9785"),
    ("draft-ietf-bess-rfc7432bis-13.txt", "RFC7432bis"),
    ("draft-ietf-bess-rfc7432bis-13.docx", "RFC7432bis"),
])
def test_short_name_strips_draft_prefix_and_revision(filename: str,
                                                     expected: str) -> None:
    assert _short_name(Path(filename)) == expected


# ─── RFC 7432bis ────────────────────────────────────────────────────────────

def test_rfc7432bis_extracts_substantial_normative_set() -> None:
    reqs = extract_rfc_requirements(RFC7432BIS)
    assert len(reqs) >= 30, (
        f"expected ≥30 normative sections from RFC7432bis, got {len(reqs)}"
    )


def test_rfc7432bis_req_ids_use_short_name_and_section() -> None:
    reqs = extract_rfc_requirements(RFC7432BIS)
    for r in reqs:
        assert r.req_id.startswith("RFC7432bis-§"), r.req_id
        section = r.req_id.removeprefix("RFC7432bis-§")
        assert r.section_number == section


def test_rfc7432bis_every_req_has_must_statement() -> None:
    reqs = extract_rfc_requirements(RFC7432BIS)
    assert all(r.must_statements for r in reqs), (
        "extractor returned a section with no MUST/SHALL/REQUIRED clause"
    )


def test_rfc7432bis_carries_rfc_ref_back_to_chapter() -> None:
    reqs = extract_rfc_requirements(RFC7432BIS)
    for r in reqs:
        assert r.rfc_refs == [f"RFC7432bis ch.{r.section_number}"]


# ─── RFC 9785 ───────────────────────────────────────────────────────────────

def test_rfc9785_extracts_at_least_three_requirements() -> None:
    reqs = extract_rfc_requirements(RFC9785)
    assert len(reqs) >= 3, (
        f"RFC9785 should yield ≥3 normative sections, got {len(reqs)}"
    )


def test_rfc9785_section_numbers_are_well_formed() -> None:
    reqs = extract_rfc_requirements(RFC9785)
    import re
    pat = re.compile(r"^[0-9]+(\.[0-9]+)*$")
    for r in reqs:
        assert pat.match(r.section_number or ""), (
            f"bad section number {r.section_number!r}"
        )


# ─── Boilerplate filtering ──────────────────────────────────────────────────

def test_boilerplate_sections_are_skipped() -> None:
    """The "Requirements Language" / "IANA Considerations" sections always
    quote MUST/SHALL but are not testable requirements."""
    for path in (RFC7432BIS, RFC9785):
        reqs = extract_rfc_requirements(path)
        for r in reqs:
            assert r.title.strip().lower() not in _BOILERPLATE_TITLES, (
                f"boilerplate section leaked through: {r.req_id} {r.title!r}"
            )


# ─── Determinism ────────────────────────────────────────────────────────────

def test_rfc_extractor_is_deterministic() -> None:
    a = extract_rfc_requirements(RFC9785)
    b = extract_rfc_requirements(RFC9785)
    assert [r.model_dump_json() for r in a] == [r.model_dump_json() for r in b]


def test_rfc_req_ids_are_unique_within_an_rfc() -> None:
    for path in (RFC7432BIS, RFC9785):
        reqs = extract_rfc_requirements(path)
        ids = [r.req_id for r in reqs]
        assert len(ids) == len(set(ids)), (
            f"duplicate req_ids extracted from {path.name}"
        )


# ─── Tagging ────────────────────────────────────────────────────────────────

def test_rfc_reqs_get_at_least_one_tag() -> None:
    """Without a tag the row would be excluded from category mapping."""
    reqs = extract_rfc_requirements(RFC7432BIS)
    assert all(r.tags for r in reqs), "RFC requirement emitted with empty tags"


# ─── Domain quality guards (regression tests for the M1 review fixes) ──────

def test_rfc_reqs_carry_source_marker() -> None:
    """Generator masks CLI/Mgmt/Upgrade categories using source='rfc'."""
    for path in (RFC7432BIS, RFC9785):
        reqs = extract_rfc_requirements(path)
        assert all(r.source == "rfc" for r in reqs), (
            "an RFC requirement was emitted with source != 'rfc'"
        )


def test_umbrella_parent_sections_are_dropped() -> None:
    """A section that has a child sub-section must not produce a Requirement —
    we keep only leaves so each MUST appears in exactly one row."""
    reqs = extract_rfc_requirements(RFC7432BIS)
    nums = {r.section_number for r in reqs}
    for n in nums:
        for other in nums:
            if other != n and other.startswith(f"{n}."):
                raise AssertionError(
                    f"parent section {n} leaked through; child {other} also present"
                )


def test_problem_statement_section_does_not_leak() -> None:
    """RFC9785 §1.1 'Problem Statement' is narrative — must not produce a row.
    Also covers the family of titles in _BOILERPLATE_TITLES we added during
    the M1 review (Solution Requirements, Use Cases, Background, etc.)."""
    reqs = extract_rfc_requirements(RFC9785)
    titles = {r.title.strip().lower() for r in reqs}
    forbidden = {
        "problem statement", "solution requirements", "solution overview",
        "use cases", "use case", "background", "motivation",
    }
    leaked = titles & forbidden
    assert not leaked, f"narrative section(s) leaked through: {leaked}"
