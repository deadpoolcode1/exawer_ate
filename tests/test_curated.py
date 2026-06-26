"""Guard the hand-curated protocol-construct rows (curated.py).

Yossi Fridman 2026-06-21: the Default Gateway Extended Community must have a TP
reference and must cross-reference RFC 4360 (where its Opaque-EC type is
defined). These rows are deterministic, so assert their key facts directly.
"""
from ate.planner.curated import CURATED_SOURCE, curated_requirements_and_rows


def test_default_gateway_ec_curated_row_present():
    reqs, rows = curated_requirements_and_rows()
    assert len(reqs) == len(rows) == 1
    req, row = reqs[0], rows[0]

    # Deterministic: must skip the AI enricher.
    assert req.source == CURATED_SOURCE
    # Lands under RFC Protocol Mandates and cites both the EVPN section and the
    # non-EVPN defining RFC.
    assert req.req_id == row.sfs_requirement_id == "RFC7432bis-§7.8"
    assert "Default Gateway Extended Community" in row.sub_category

    blob = row.action_steps + row.expectation
    assert "RFC 4360" in blob          # the non-EVPN RFC the type comes from
    assert "0x03" in blob and "0x0d" in blob   # exact Type / Sub-Type encoding
    assert "§10.1" in blob             # best-path procedures
