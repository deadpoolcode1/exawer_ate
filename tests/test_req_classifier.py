"""Tests for ate.planner.req_classifier — SFS-vs-RFC relationship classifier."""
from __future__ import annotations

from pathlib import Path

from ate.planner.model import Requirement
from ate.planner.req_classifier import classify, classify_all
from ate.planner.requirements_builder import build_catalog

ROOT = Path(__file__).resolve().parents[1]
EVPN_SPEC = ROOT / "tests/corpus/tier_a/EVPN System Specification 1.00.docx"
RFC7432BIS = ROOT / "references/EVPN/draft-ietf-bess-rfc7432bis-13.txt"
RFC9785 = ROOT / "references/EVPN/rfc9785.txt"


def _sfs(req_id: str, *, description: str = "",
         rfc_refs: tuple[str, ...] = ()) -> Requirement:
    return Requirement(req_id=req_id, title=f"t-{req_id}",
                        description=description, rfc_refs=list(rfc_refs),
                        source="spec")


def test_base_sfs_when_no_rfc_refs() -> None:
    r = _sfs("EVPNS-REQ#10",
             description="The system MUST support EVPN per Exaware spec.")
    kind, links = classify(r, rfc_catalog_ids=set())
    assert kind == "base_sfs"
    assert links == []


def test_delta_when_description_says_replaces() -> None:
    r = _sfs("EVPNS-REQ#190",
             description=("The multihoming procedures MUST be supported. "
                          "The document replaces SHOULD to MUST in the second "
                          "rule in [RFC7432bis], chapter 8.7."),
             rfc_refs=("RFC7432bis ch.8.7",))
    kind, _ = classify(r, rfc_catalog_ids={"RFC7432bis-§8.7"})
    assert kind == "delta"


def test_delta_when_description_says_instead_of() -> None:
    r = _sfs("EVPNS-REQ#X",
             description="The device uses scheme A instead of the RFC default.",
             rfc_refs=("RFC1234 ch.1",))
    kind, _ = classify(r, rfc_catalog_ids=set())
    assert kind == "delta"


def test_overlay_when_description_says_in_addition_to() -> None:
    r = _sfs("EVPNS-REQ#Y",
             description=("In addition to the RFC base behaviour, the device "
                          "MUST also enforce a 256-MAC limit per ES."),
             rfc_refs=("RFC1234 ch.2",))
    kind, _ = classify(r, rfc_catalog_ids=set())
    assert kind == "overlay"


def test_pointer_when_short_with_see_rfc() -> None:
    r = _sfs("EVPNS-REQ#100",
             description=("The Remote MAC learning (see [RFC7432bis], "
                          "chapter 9.2) MUST be supported."),
             rfc_refs=("RFC7432bis ch.9.2",))
    kind, _ = classify(r, rfc_catalog_ids=set())
    assert kind == "pointer"


def test_sfs_with_rfc_context_for_long_descriptions() -> None:
    long_desc = (
        "The route contains the following fields: RD, ESI, ET ID = MAX-ET, "
        "MPLS Label = 0, ESI Label Extended Community Single-Active flag. "
        + "Continued specification text. " * 20
    )
    r = _sfs("EVPNS-REQ#260", description=long_desc,
             rfc_refs=("RFC7432bis ch.8.2.1",))
    kind, _ = classify(r, rfc_catalog_ids=set())
    assert kind == "sfs_with_rfc_context"


def test_rfc_links_resolve_against_catalog() -> None:
    """RFC refs that match a req_id in the catalog become rfc_links;
    refs to missing sections are dropped — we never fabricate links."""
    r = _sfs("EVPNS-REQ#120",
             description="See [RFC7432bis], chapter 8.5 for the default DF algorithm.",
             rfc_refs=("RFC7432bis ch.8.5", "RFC8584 ch.4"))
    # Only §8.5 is in our catalog; §8584 §4 is not (treat as unknown).
    _, links = classify(r,
                        rfc_catalog_ids={"RFC7432bis-§8.5", "RFC7432bis-§9"})
    assert links == ["RFC7432bis-§8.5"]


def test_rfc_source_classified_as_rfc() -> None:
    r = Requirement(req_id="RFC7432bis-§7.2", title="MAC/IP route",
                    source="rfc",
                    description="The route MUST carry RD + ESI.",
                    rfc_refs=["RFC7432bis ch.7.2"])
    kind, _ = classify(r, rfc_catalog_ids={"RFC7432bis-§7.2"})
    assert kind == "rfc"


def test_classify_all_populates_kind_and_links() -> None:
    cat = build_catalog(EVPN_SPEC, rfc_paths=[RFC7432BIS, RFC9785])
    # build_catalog already runs classify_all; every req has a kind.
    assert all(r.kind for r in cat.requirements), (
        "classify_all missed some reqs"
    )
    # Real EVPN signal: REQ#190 is a textbook delta.
    req190 = next(r for r in cat.requirements if r.req_id == "EVPNS-REQ#190")
    assert req190.kind == "delta", (
        f"REQ#190 is documented as a delta but got kind={req190.kind!r}"
    )


def test_classify_idempotent() -> None:
    """Running classify_all twice on the same list keeps the result stable."""
    cat = build_catalog(EVPN_SPEC, rfc_paths=[RFC9785])
    before = [(r.req_id, r.kind, tuple(r.rfc_links))
              for r in cat.requirements]
    classify_all(cat.requirements)
    after = [(r.req_id, r.kind, tuple(r.rfc_links))
             for r in cat.requirements]
    assert before == after
