"""Guard the hand-curated protocol-construct rows + dependency-RFC relevance map.

Yossi Fridman 2026-06-21: (1) the Default Gateway Extended Community must have a
TP reference and must cross-reference RFC 4360; (2) the non-EVPN RFCs the SFS
cites must be either ingested or explicitly classified. These are deterministic,
so assert the key facts directly.
"""
from ate.planner.curated import (
    CURATED_SOURCE,
    DEPENDENCY_RFC_ROLE,
    curated_requirements_and_rows,
)


def test_curated_rows_present_and_deterministic():
    reqs, rows = curated_requirements_and_rows()
    assert len(reqs) == len(rows) == 3
    by_id = {r.req_id: r for r in reqs}
    # All three curated constructs present, all deterministic (skip enricher).
    assert set(by_id) == {"RFC7432bis-§7.8", "RFC8584-§2.2", "RFC6514-§5"}
    assert all(r.source == CURATED_SOURCE for r in reqs)
    assert all(row.sfs_requirement_id.startswith("RFC") for row in rows)


def test_default_gateway_ec_cross_references_rfc4360():
    _reqs, rows = curated_requirements_and_rows()
    row = next(r for r in rows if r.sfs_requirement_id == "RFC7432bis-§7.8")
    blob = row.action_steps + row.expectation
    assert "RFC 4360" in blob                  # non-EVPN defining RFC
    assert "0x03" in blob and "0x0d" in blob   # exact Type / Sub-Type
    assert "§10.1" in blob                      # best-path procedures


def test_df_election_and_pmsi_encodings():
    _reqs, rows = curated_requirements_and_rows()
    df = next(r for r in rows if r.sfs_requirement_id == "RFC8584-§2.2")
    assert "0x06" in df.action_steps           # DF Election EC Type/Sub-Type
    assert "HRW" in df.action_steps
    pmsi = next(r for r in rows if r.sfs_requirement_id == "RFC6514-§5")
    assert "Ingress Replication" in pmsi.action_steps


def test_relevance_map_classifies_every_cited_dependency_rfc():
    # The non-EVPN RFCs the SFS cites are each classified (no bare "missing").
    for num in ("4360", "8584", "6514", "4364", "4761", "4762", "7209", "8340"):
        assert num in DEPENDENCY_RFC_ROLE
        role, verdict, note = DEPENDENCY_RFC_ROLE[num]
        assert verdict in {"curated", "flow", "reference-only"}
        assert role and note
